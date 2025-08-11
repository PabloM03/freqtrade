# --- Do not remove these libs ---
import freqtrade.vendor.qtpylib.indicators as qtpylib
import numpy as np
# --------------------------------
import talib.abstract as ta
from freqtrade.strategy.interface import IStrategy
from freqtrade.strategy import stoploss_from_open
from pandas import DataFrame
from datetime import datetime
from typing import Optional
from freqtrade.persistence import Trade


def bollinger_bands(stock_price, window_size, num_of_std):
    rolling_mean = stock_price.rolling(window=window_size).mean()
    rolling_std = stock_price.rolling(window=window_size).std()
    lower_band = rolling_mean - (rolling_std * num_of_std)
    return np.nan_to_num(rolling_mean), np.nan_to_num(lower_band)


class CombinedBinHAndCluc(IStrategy):
    """
    - Compras: en bajadas óptimas (mínimo local claro + capitulación/giro), no en mitad de subida.
    - Ventas: en picos óptimos (máximo local claro + rechazo/giro).
    - Crash-guard y trailing moderado.
    """

    # Costes estimados
    FEE_RATE = 0.001
    SLIPPAGE_BUFFER = 0.0005
    MIN_PROFIT_NET = 2 * FEE_RATE + SLIPPAGE_BUFFER  # ~0.25% neto

    # Profits mínimos para exits discrecionales
    PEAK_MIN_PROFIT = 0.0065
    HH_EMA_MIN_PROFIT = 0.008
    HARD_TP = 0.018

    minimal_roi = {"0": 0.0}
    stoploss = -0.05
    timeframe = '5m'
    startup_candle_count = 100

    use_sell_signal = True
    sell_profit_only = True
    ignore_roi_if_buy_signal = False
    trailing_stop = False

    MIN_HOLD_BARS = 1

    # ---------------------- INDICADORES ----------------------
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # BinHV45
        mid, lower = bollinger_bands(dataframe['close'], window_size=40, num_of_std=2)
        dataframe['lower'] = lower
        dataframe['bbdelta'] = (mid - dataframe['lower']).abs()
        dataframe['closedelta'] = (dataframe['close'] - dataframe['close'].shift()).abs()
        dataframe['tail'] = (dataframe['close'] - dataframe['low']).abs()

        # Bollinger 20
        tp = qtpylib.typical_price(dataframe)
        bb = qtpylib.bollinger_bands(tp, window=20, stds=2)
        dataframe['bb_lowerband']  = bb['lower']
        dataframe['bb_middleband'] = bb['mid']
        dataframe['bb_upperband']  = bb['upper']
        dataframe['bb_width'] = (dataframe['bb_upperband'] - dataframe['bb_lowerband']) / dataframe['bb_middleband']
        denom = (dataframe['bb_upperband'] - dataframe['bb_lowerband']).replace(0, np.nan)
        dataframe['bb_percent'] = (dataframe['close'] - dataframe['bb_lowerband']) / denom
        dataframe['bb_expanding'] = (dataframe['bb_width'] > dataframe['bb_width'].shift(1))

        # EMAs / fuerza
        dataframe['ema8']     = ta.EMA(dataframe, timeperiod=8)
        dataframe['ema_fast'] = ta.EMA(dataframe, timeperiod=20)
        dataframe['ema_slow'] = ta.EMA(dataframe, timeperiod=50)
        dataframe['volume_mean_slow'] = dataframe['volume'].rolling(window=30).mean()
        dataframe['ema8_slope_up'] = dataframe['ema8'] > dataframe['ema8'].shift(1)

        # RSI / ADX / DI
        dataframe['rsi']      = ta.RSI(dataframe, timeperiod=14)
        dataframe['rsi_prev'] = dataframe['rsi'].shift(1)
        dataframe['adx']      = ta.ADX(dataframe, timeperiod=14)
        dataframe['plus_di']  = ta.PLUS_DI(dataframe, timeperiod=14)
        dataframe['minus_di'] = ta.MINUS_DI(dataframe, timeperiod=14)

        # StochRSI
        stoch = ta.STOCHRSI(dataframe, timeperiod=14, fastk_period=3, fastd_period=3)
        dataframe['stoch_k'] = stoch['fastk']
        dataframe['stoch_d'] = stoch['fastd']
        dataframe['stoch_k_prev'] = dataframe['stoch_k'].shift(1)
        dataframe['stoch_d_prev'] = dataframe['stoch_d'].shift(1)

        # MACD
        macd = ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)
        dataframe['macd']      = macd['macd']
        dataframe['macdsignal']= macd['macdsignal']
        dataframe['macdhist']  = macd['macdhist']

        # Momentum/extremos
        dataframe['roc5'] = ta.ROC(dataframe, timeperiod=5)
        dataframe['ll_8']  = dataframe['low'].rolling(8).min()
        dataframe['ll_10'] = dataframe['low'].rolling(10).min()
        dataframe['ll_20'] = dataframe['low'].rolling(20).min()
        dataframe['hh_20'] = dataframe['high'].rolling(20).max()

        # ATR y variaciones
        dataframe['atr']  = ta.ATR(dataframe, timeperiod=14)
        dataframe['pct_1']= dataframe['close'].pct_change(1) * 100.0
        dataframe['pct_3']= dataframe['close'].pct_change(3) * 100.0

        # Estructura / cooldown
        body = (dataframe['close'] - dataframe['open']).abs()
        dataframe['big_red']  = (dataframe['close'] < dataframe['open']) & (body > 1.2 * dataframe['atr'])
        dataframe['cooldown'] = dataframe['big_red'].rolling(5).max()

        # Mechas
        dataframe['upper_wick'] = (dataframe['high'] - np.maximum(dataframe['open'], dataframe['close'])).abs()
        dataframe['lower_wick'] = (np.minimum(dataframe['open'], dataframe['close']) - dataframe['low']).abs()

        # Volumen relativo
        dataframe['vol_spike'] = dataframe['volume'] > (dataframe['volume_mean_slow'] * 1.15)

        # Máximo/mínimo local reciente (ventanas cortas) para “picos/vales óptimos”
        dataframe['loc_peak'] = (
            (dataframe['high'] >= dataframe['high'].rolling(6).max()) &
            (dataframe['high'] >= dataframe['high'].shift(1)) &
            (dataframe['high'] >= dataframe['high'].shift(2))
        )
        dataframe['loc_trough'] = (
            (dataframe['low'] <= dataframe['low'].rolling(6).min()) &
            (dataframe['low'] <= dataframe['low'].shift(1)) &
            (dataframe['low'] <= dataframe['low'].shift(2))
        )

        return dataframe

    # ---------------------- COMPRAS (bajadas más óptimas) ----------------------
    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        anti_cuchillo = (
            (dataframe['pct_1'] > -1.2) &
            (dataframe['pct_3'] > -2.4) &
            (~dataframe['cooldown'].astype(bool)) &
            (~((dataframe['bb_percent'] < 0) & dataframe['bb_expanding'])) &
            (dataframe['minus_di'] <= dataframe['plus_di']) &
            (dataframe['volume'] > 0)
        )

        # Evitar compras “arriba”
        no_buy_high = (
            (dataframe['close'] > dataframe['bb_middleband'] * 1.02) &
            (dataframe['close'] > dataframe['ema_fast']) &
            (dataframe['rsi'] > 57)
        )

        # Zonas de valor (un poco más estrictas para que sean “bajadas óptimas”)
        deep_bb    = (dataframe['bb_percent'] <= 0.20)
        bb_zone_ok = (dataframe['bb_percent'] <= 0.35)

        lower_wick = dataframe['lower_wick']
        body       = (dataframe['close'] - dataframe['open']).abs()
        hammerish  = lower_wick > 1.15 * body

        # A) Mínimo local + giro RSI + martillo/volumen (bajada óptima)
        A = (
            (dataframe['loc_trough']) &
            ((dataframe['low'] <= dataframe['ll_10'] * 1.004) | deep_bb) &
            (dataframe['rsi_prev'] < 45) & (dataframe['rsi'] > dataframe['rsi_prev']) &
            (dataframe['close'] >= dataframe['open']) &
            (hammerish | dataframe['vol_spike'])
        )

        # B) Re-entrada tras cerrar fuera de banda inferior y volver dentro (clásico y muy abajo)
        B = (
            (dataframe['close'].shift(1) < dataframe['bb_lowerband'].shift(1)) &
            (dataframe['close'] > dataframe['bb_lowerband']) &
            (dataframe['rsi'] > dataframe['rsi_prev']) &
            (bb_zone_ok)
        )

        # C) StochRSI cruce en sobreventa + MACD no empeora + en zona baja BB
        C = (
            (dataframe['stoch_k_prev'] < dataframe['stoch_d_prev']) &
            (dataframe['stoch_k'] > dataframe['stoch_d']) &
            (dataframe['stoch_k'] < 35) & (dataframe['stoch_d'] < 35) &
            (dataframe['macdhist'] >= dataframe['macdhist'].shift(1)) &
            (bb_zone_ok)
        )

        # D) Capitulación: vela muy roja previa / colas largas + rebote verde
        D = (
            ((dataframe['pct_1'] <= -1.8) | (dataframe['pct_3'] <= -3.5)) &
            (dataframe['bb_percent'] <= 0.05) &
            (dataframe['tail'] >= dataframe['atr'] * 1.0) &
            (dataframe['close'] >= dataframe['open'])
        )

        # E) Pullback controlado a EMA8 ascendente en zona media-baja
        E = (
            (dataframe['close'] > dataframe['ema8']) &
            (dataframe['close'].shift(1) <= dataframe['ema8'].shift(1)) &
            (dataframe['ema8_slope_up']) &
            (dataframe['rsi'] >= 45) & (dataframe['rsi'] > dataframe['rsi_prev']) &
            ((dataframe['low'] <= dataframe['ll_10'] * 1.01) | (dataframe['close'] <= dataframe['bb_middleband'] * 1.01) | bb_zone_ok) &
            (dataframe['vol_spike'] | hammerish)
        )

        # F) Doble toque / higher-low sutil en zona baja (confirmación de valle)
        F = (
            (dataframe['bb_percent'] <= 0.30) &
            (dataframe['low'] <= dataframe['ll_10'] * 1.005) &
            (dataframe['low'] >= dataframe['ll_10'].shift(1) * 0.992) &
            (dataframe['rsi'] > dataframe['rsi_prev']) &
            (dataframe['close'] >= dataframe['open'])
        )

        dataframe.loc[
            (((A | B | C | D | E | F) & anti_cuchillo & ~no_buy_high) | D),  # D (capitulación) siempre permitida
            'buy'
        ] = 1
        return dataframe

    # ---------------------- VENTAS (picos más óptimos) ----------------------
    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Rechazo fuerte cerca de banda superior (mecha y RSI alto)
        reject_upper = (
            (dataframe['upper_wick'] >= dataframe['atr'] * 0.9) &
            (dataframe['upper_wick'] > (dataframe['close'] - dataframe['open']).abs() * 1.2) &
            ((dataframe['high'] >= dataframe['bb_upperband'] * 0.999) | (dataframe['close'] >= dataframe['bb_upperband'])) &
            (dataframe['rsi'] >= 60)
        )

        # Pico óptimo: máximo local + proximidad a banda sup + RSI alto + giro (MACD/EMA/vela)
        dataframe.loc[
            (
                (dataframe['loc_peak']) &
                (dataframe['close'] >= dataframe['bb_upperband'] * 0.999) &
                (dataframe['rsi'] >= 70) &
                (
                    (dataframe['macdhist'] < dataframe['macdhist'].shift(1)) |
                    (dataframe['close'] < dataframe['ema8']) |
                    (dataframe['close'] < dataframe['open'])
                )
            )
            |
            (
                # Máximo del rango + ruptura EMA8 posterior con MACD debilitando
                (dataframe['high'].shift(1) >= dataframe['hh_20'].shift(1)) &
                (dataframe['close'].shift(1) >= dataframe['ema8'].shift(1)) &
                (dataframe['close'] < dataframe['ema8']) &
                (dataframe['rsi'] >= 62) &
                (dataframe['macdhist'] < dataframe['macdhist'].shift(1))
            )
            |
            reject_upper,
            'sell'
        ] = 1
        return dataframe

    # ---------------------- UTILIDADES ----------------------
    def _bars_elapsed(self, trade: Trade, current_time: datetime) -> int:
        tf_minutes = int(self.timeframe.rstrip('m'))
        seconds = (current_time - trade.open_date_utc).total_seconds()
        return int(max(0, seconds) // (tf_minutes * 60))

    def _strong_bearish_reversal(self, pair: str) -> bool:
        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last = df.iloc[-1]
            return (last['minus_di'] > last['plus_di']) and (last['adx'] > 23) and (last['rsi'] < 55)
        except Exception:
            return False

    def _crash_incoming(self, pair: str) -> bool:
        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last = df.iloc[-1]
            prev = df.iloc[-2]
            fast_drop = (last['close'] <= last['ema8'] * 0.992) and (last['pct_1'] <= -0.7)
            atr_break = (last['low'] < last['ema_fast'] - 1.6 * last['atr'])
            bb_flush = (last['bb_percent'] < 0) and bool(last['bb_expanding']) and (last['macdhist'] < prev['macdhist'])
            di_shift = (last['adx'] > 22) and (last['minus_di'] > last['plus_di']) and (last['rsi'] < 48)
            return sum([fast_drop, atr_break, bb_flush or di_shift]) >= 2
        except Exception:
            return False

    # ---------------------- EXITS (alineadas con picos/vales óptimos) ----------------------
    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs
    ) -> Optional[str]:
        # Crash guard
        if self._crash_incoming(pair):
            if current_profit is None or current_profit > -0.01:
                return "crash_guard"

        bars = self._bars_elapsed(trade, current_time)
        if bars < self.MIN_HOLD_BARS:
            if not self._strong_bearish_reversal(pair):
                return None

        # TP duro
        if current_profit is not None and current_profit >= self.HARD_TP:
            return "hard_tp"

        # Requiere beneficio neto
        if current_profit is None or current_profit < self.MIN_PROFIT_NET:
            return None

        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last  = df.iloc[-1]
            prev  = df.iloc[-2]

            near_upper = (last['close'] >= last['bb_upperband'] * 0.999) or (last['high'] >= last['bb_upperband'])
            loc_peak   = bool(last['high'] >= df['high'].rolling(6).max().iloc[-1])
            rsi_high   = (last['rsi'] >= 70)
            bear_candle= (last['close'] < last['open'])
            macd_fade  = (last['macdhist'] < prev['macdhist'])
            ema_break  = (last['close'] < last['ema8'])

            # Pico óptimo: banda sup + máximo local + giro claro
            if current_profit >= self.PEAK_MIN_PROFIT and near_upper and loc_peak and rsi_high and (
                bear_candle or macd_fade or ema_break
            ):
                return "peak_exit_top_optimal"

            # HH + ruptura EMA8 + MACD debilitando (clásico)
            if current_profit >= self.HH_EMA_MIN_PROFIT and (prev['high'] >= df['high'].rolling(20).max().iloc[-2]) and ema_break and macd_fade and (last['rsi'] >= 62):
                return "hh_ema8_break_exit"

            # Rechazo de mecha grande en zona alta
            upper_wick = float(last['high'] - max(last['open'], last['close']))
            body = float(abs(last['close'] - last['open']))
            if current_profit >= self.MIN_PROFIT_NET and near_upper and (upper_wick >= last['atr'] * 0.9) and (upper_wick > 1.1 * body) and (last['rsi'] >= 61):
                return "upper_wick_reject_exit"

            # Pérdida de momentum tras varias velas en verde
            if current_profit >= (self.MIN_PROFIT_NET + 0.002) and bars >= 6:
                if (last['rsi'] < last['rsi_prev']) and macd_fade and ema_break:
                    return "momentum_fade_exit"

        except Exception:
            pass

        return None

    # ---------------------- TRAILING ----------------------
    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs
    ) -> float:
        if current_profit is None or current_profit < 0.03:
            return self.stoploss

        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last = df.iloc[-1]
            atr = float(last['atr'])
            adx = float(last['adx'])
            roc5 = float(last['roc5'])
        except Exception:
            return stoploss_from_open(current_profit, 0.018)

        strong_trend = (adx >= 25 and roc5 > 0)
        vertical_rally = (roc5 >= 3)

        k = 2.4 if current_profit > 0.06 else 2.0
        dist = (k * atr) / max(current_rate, 1e-9)
        dist = min(0.032, max(0.016, dist))

        if vertical_rally:
            dist = max(dist, 0.022)
        elif not strong_trend:
            dist = min(dist, 0.02)

        if 0.03 <= current_profit < 0.06:
            return stoploss_from_open(current_profit, max(0.018, dist))

        return stoploss_from_open(current_profit, dist)