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
    - Compras: rebote en mínimos locales (ligeramente más permisivo) + capitulación.
    - Ventas: SOLO en picos punteros (HH + banda superior + RSI alto + giro), con buen beneficio.
    - Crash-guard y trailing moderado.
    """

    # Comisiones estimadas (ajusta a tu exchange)
    FEE_RATE = 0.001           # 0.10% por lado
    SLIPPAGE_BUFFER = 0.0005   # 0.05%
    MIN_PROFIT_NET = 2 * FEE_RATE + SLIPPAGE_BUFFER  # ~0.25% neto para permitir venta

    # Beneficios mínimos desde la compra para vender (además de MIN_PROFIT_NET)
    PEAK_MIN_PROFIT = 0.011    # 1.1% para picos punteros
    HARD_TP = 0.018            # 1.8%: TP de seguridad si no hay señal pero hay gran tramo

    minimal_roi = {"0": 0.0}
    stoploss = -0.05
    timeframe = '5m'
    startup_candle_count = 100

    # Señales de venta + exits discrecionales (muy selectivas)
    use_sell_signal = True
    sell_profit_only = True
    ignore_roi_if_buy_signal = False
    trailing_stop = False

    MIN_HOLD_BARS = 2

    # ---------------------- INDICADORES ----------------------
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # BinHV45
        mid, lower = bollinger_bands(dataframe['close'], window_size=40, num_of_std=2)
        dataframe['lower'] = lower
        dataframe['bbdelta'] = (mid - dataframe['lower']).abs()
        dataframe['closedelta'] = (dataframe['close'] - dataframe['close'].shift()).abs()
        dataframe['tail'] = (dataframe['close'] - dataframe['low']).abs()

        # Bollinger
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

        # RSI / ADX / DI
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['rsi_prev'] = dataframe['rsi'].shift(1)
        dataframe['adx'] = ta.ADX(dataframe, timeperiod=14)
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
        dataframe['macd'] = macd['macd']
        dataframe['macdsignal'] = macd['macdsignal']
        dataframe['macdhist'] = macd['macdhist']

        # Momentum/extremos
        dataframe['roc5'] = ta.ROC(dataframe, timeperiod=5)
        dataframe['ll_10'] = dataframe['low'].rolling(10).min()
        dataframe['hh_20'] = dataframe['high'].rolling(20).max()
        dataframe['ll_20'] = dataframe['low'].rolling(20).min()
        dataframe['ll_8']  = dataframe['low'].rolling(8).min()   # nuevo: mínimo local más corto

        # ATR y variaciones
        dataframe['atr'] = ta.ATR(dataframe, timeperiod=14)
        dataframe['pct_1'] = dataframe['close'].pct_change(1) * 100.0
        dataframe['pct_3'] = dataframe['close'].pct_change(3) * 100.0

        # Estructura HL/HH y cooldown
        dataframe['hl_ok'] = (dataframe['low'] > dataframe['low'].shift(1)) & (dataframe['close'] > dataframe['high'].shift(1))
        dataframe['trend_ok'] = (dataframe['ema8'] > dataframe['ema_fast']) & (dataframe['ema_fast'] > dataframe['ema_slow'])

        body = (dataframe['close'] - dataframe['open']).abs()
        dataframe['big_red'] = (dataframe['close'] < dataframe['open']) & (body > 1.2 * dataframe['atr'])
        dataframe['cooldown'] = dataframe['big_red'].rolling(5).max()

        return dataframe

    # ---------------------- COMPRAS ----------------------
    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        anti_cuchillo = (
            (dataframe['pct_1'] > -0.8) &
            (dataframe['pct_3'] > -1.6) &
            (~dataframe['cooldown'].astype(bool)) &
            (~((dataframe['bb_percent'] < 0) & dataframe['bb_expanding'])) &
            (dataframe['minus_di'] <= dataframe['plus_di']) &
            (dataframe['volume'] > 0)
        )

        # Ligeramente más permisivo para capturar mínimos locales
        deep_bb = (dataframe['bb_percent'] <= 0.18)
        lower_wick = (np.minimum(dataframe['open'], dataframe['close']) - dataframe['low']).abs()
        body = (dataframe['close'] - dataframe['open']).abs()
        hammerish = lower_wick > 1.1 * body

        A = (
            (
                (dataframe['low'] <= dataframe['ll_20'] * 1.006) |     # antes 1.005
                (dataframe['low'] <= dataframe['ll_10'] * 1.003) |     # nuevo pequeño empuje
                deep_bb
            ) &
            (hammerish) &
            (dataframe['rsi_prev'] < 46) & (dataframe['rsi'] > dataframe['rsi_prev']) &  # antes 44
            (dataframe['close'] >= dataframe['open']) &
            (dataframe['close'] >= dataframe['ema8'] * 0.994)                                # antes 0.995
        )

        B = (
            (dataframe['close'].shift(1) < dataframe['ema8'].shift(1)) &
            (dataframe['close'] > dataframe['ema8']) &
            (dataframe['close'] < dataframe['ema_slow']) &
            (dataframe['close'] <= dataframe['bb_lowerband'] * 1.03)    # antes 1.025
        )

        C = (
            (dataframe['stoch_k_prev'] < dataframe['stoch_d_prev']) &
            (dataframe['stoch_k'] > dataframe['stoch_d']) &
            (dataframe['stoch_k'] < 34) & (dataframe['stoch_d'] < 34) &  # antes 32
            (dataframe['macdhist'] >= dataframe['macdhist'].shift(1)) &
            deep_bb
        )

        D = (
            (dataframe['bb_width'] < dataframe['bb_width'].rolling(100).quantile(0.30)) &
            (dataframe['macdhist'] > 0) &
            deep_bb
        )

        # Mínimo local claro (8 velas) + giro RSI + vela verde
        E_MIN = (
            (dataframe['low'] <= dataframe['ll_8'] * 1.002) &
            (dataframe['rsi'] > dataframe['rsi_prev']) &
            (dataframe['close'] >= dataframe['open']) &
            (dataframe['bb_percent'] <= 0.20)
        )

        # Capitulación extrema (igual que antes)
        E_CAP = (
            ((dataframe['pct_1'] <= -1.8) | (dataframe['pct_3'] <= -3.5)) &
            (dataframe['bb_percent'] <= 0) &
            (dataframe['tail'] >= dataframe['atr'] * 1.0) &
            (dataframe['close'] >= dataframe['open'])
        )

        dataframe.loc[((A | B | C | D | E_MIN) & anti_cuchillo) | E_CAP, 'buy'] = 1
        return dataframe

    # ---------------------- VENTAS: SOLO picos punteros ----------------------
    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Picos punteros: nuevo HH + toque/roce banda superior + RSI alto + giro claro.
        (Luego custom_exit exige beneficio mínimo.)
        """
        dataframe.loc[
            (
                (dataframe['high'] >= dataframe['hh_20'] * 0.999) &      # máximo local
                (dataframe['close'] >= dataframe['bb_upperband'] * 0.999) &  # muy arriba
                (dataframe['rsi'] >= 74) &                                # RSI alto
                (dataframe['close'] < dataframe['open']) &                # vela roja
                (
                    (dataframe['macdhist'] < dataframe['macdhist'].shift(1)) |   # debilidad
                    (dataframe['close'] < dataframe['ema8'])
                )
            ),
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

    # ---------------------- EXITS (beneficio mínimo + picos punteros) ----------------------
    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs
    ) -> Optional[str]:
        # Crash: fuera incluso algo en rojo
        if self._crash_incoming(pair):
            if current_profit is None or current_profit > -0.01:
                return "crash_guard"

        bars = self._bars_elapsed(trade, current_time)
        if bars < self.MIN_HOLD_BARS:
            if not self._strong_bearish_reversal(pair):
                return None

        # TP duro (muy ocasional) si no hay señal pero ya hay gran tramo
        if current_profit is not None and current_profit >= self.HARD_TP:
            return "hard_tp"

        # Solo si hay beneficio neto
        if current_profit is None or current_profit < self.MIN_PROFIT_NET:
            return None

        # Vende únicamente en picos punteros con beneficio >= 1.1%
        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last  = df.iloc[-1]
            prev  = df.iloc[-2]

            near_hh    = (last['high'] >= last['hh_20'] * 0.999) or (prev['high'] >= prev['hh_20'] * 0.999)
            near_upper = (last['close'] >= last['bb_upperband'] * 0.999)
            rsi_high   = (last['rsi'] >= 74)
            bear_candle= (last['close'] < last['open'])
            macd_fade  = (last['macdhist'] < prev['macdhist'])
            ema_break  = (last['close'] < last['ema8'])

            if current_profit >= self.PEAK_MIN_PROFIT and near_hh and near_upper and rsi_high and bear_candle and (macd_fade or ema_break):
                return "peak_exit_top"
        except Exception:
            # Fallback prudente: no vender salvo TP fuerte
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
        # Trailing moderado cuando ya hay recorrido
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