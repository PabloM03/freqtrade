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
    - Entradas: rebote/confirmación (evita mitad de caída).
    - Exits: crash-guard + trailing amplio para dejar correr.
    - Bloqueo de ventas: no cierres si el beneficio no supera comisiones + colchón.
    - Menos operaciones / más tiempo en mercado en tramos buenos.
    """

    # ======== Parámetros generales / comisiones ========
    # Comisión estimada por lado (e.g. Binance spot ~0.1% -> 0.001)
    FEE_RATE = 0.001
    # Colchón por deslizamiento (0.05%):
    SLIPPAGE_BUFFER = 0.0005
    # Beneficio mínimo para permitir cualquier salida "por beneficio"
    MIN_PROFIT = 2 * FEE_RATE + SLIPPAGE_BUFFER  # ida+vuelta + colchón (~0.25%)

    minimal_roi = {"0": 0.0}
    stoploss = -0.05
    timeframe = '5m'
    startup_candle_count = 100

    # Control de ventas: sólo desde custom_exit/custom_stoploss
    use_sell_signal = False
    sell_profit_only = True
    ignore_roi_if_buy_signal = False

    trailing_stop = False  # usamos custom_stoploss

    # Aguanta más tiempo (24 velas * 5m ≈ 2h)
    MIN_HOLD_BARS = 24

    # ---------------------- INDICADORES ----------------------
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # BinHV45
        mid, lower = bollinger_bands(dataframe['close'], window_size=40, num_of_std=2)
        dataframe['lower'] = lower
        dataframe['bbdelta'] = (mid - dataframe['lower']).abs()
        dataframe['closedelta'] = (dataframe['close'] - dataframe['close'].shift()).abs()
        dataframe['tail'] = (dataframe['close'] - dataframe['low']).abs()

        # Bollinger (TP)
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

        # Stoch RSI (K/D)
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

        # Momentum/pendiente y extremos locales
        dataframe['roc5'] = ta.ROC(dataframe, timeperiod=5)
        dataframe['ll_10'] = dataframe['low'].rolling(10).min()
        dataframe['hh_20'] = dataframe['high'].rolling(20).max()
        dataframe['ll_20'] = dataframe['low'].rolling(20).min()

        # ATR y variaciones (para anti-cuchillo y crash guard)
        dataframe['atr'] = ta.ATR(dataframe, timeperiod=14)
        dataframe['pct_1'] = dataframe['close'].pct_change(1) * 100.0
        dataframe['pct_3'] = dataframe['close'].pct_change(3) * 100.0

        # Estructura HL/HH simple y régimen de EMAs
        dataframe['hl_ok'] = (dataframe['low'] > dataframe['low'].shift(1)) & (dataframe['close'] > dataframe['high'].shift(1))
        dataframe['trend_ok'] = (dataframe['ema8'] > dataframe['ema_fast']) & (dataframe['ema_fast'] > dataframe['ema_slow'])

        # Velón rojo y cooldown (evitar cuchillos)
        body = (dataframe['close'] - dataframe['open']).abs()
        dataframe['big_red'] = (dataframe['close'] < dataframe['open']) & (body > 1.2 * dataframe['atr'])
        dataframe['cooldown'] = dataframe['big_red'].rolling(5).max()  # un poco más permisivo que 6

        return dataframe

    # ---------------------- ENTRADAS ----------------------
    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        anti_cuchillo = (
            (dataframe['pct_1'] > -0.8) &                      # más permisivo que -0.6
            (dataframe['pct_3'] > -1.6) &
            (~dataframe['cooldown'].astype(bool)) &
            (~((dataframe['bb_percent'] < 0) & dataframe['bb_expanding'])) &
            (dataframe['minus_di'] <= dataframe['plus_di']) &
            (dataframe['volume'] > 0)
        )

        A = (
            (dataframe['low'] <= dataframe['ll_10']) &
            (dataframe['rsi_prev'] < 32) & (dataframe['rsi'] > dataframe['rsi_prev']) &
            (dataframe['close'] > dataframe['open']) &
            (dataframe['close'] >= dataframe['ema8'] * 0.998) &
            (dataframe['hl_ok'])
        )

        B = (
            (dataframe['close'].shift(1) < dataframe['ema8'].shift(1)) &
            (dataframe['close'] > dataframe['ema8']) &
            (dataframe['close'] < dataframe['ema_slow']) &
            (dataframe['close'] <= dataframe['bb_lowerband'] * 1.02)   # 1.02 para permitir rebote bajo
        )

        C = (
            (dataframe['stoch_k_prev'] < dataframe['stoch_d_prev']) &
            (dataframe['stoch_k'] > dataframe['stoch_d']) &
            (dataframe['stoch_k'] < 20) & (dataframe['stoch_d'] < 20) &
            (dataframe['macd'] >= dataframe['macdsignal']) &
            (dataframe['minus_di'] <= dataframe['plus_di'])
        )

        D = (
            (dataframe['bb_width'] < dataframe['bb_width'].rolling(100).quantile(0.25)) &
            (dataframe['close'] > dataframe['bb_middleband']) &
            (dataframe['macdhist'] > 0) &
            (dataframe['volume'] > dataframe['volume_mean_slow'])
        )

        E = (
            (dataframe['low'] <= dataframe['ll_20'] * 1.002) &
            (dataframe['bb_percent'] <= 0.08) &
            (dataframe['rsi_prev'] < 38) & (dataframe['rsi'] > dataframe['rsi_prev']) &
            (dataframe['tail'] >= dataframe['atr'] * 0.8) &
            (dataframe['close'] > dataframe['open'])
        )

        trend_ok_relajado = (
            (dataframe['ema_fast'] > dataframe['ema_slow']) &
            (dataframe['close'] > dataframe['ema_fast'] * 0.995)
        )

        dataframe.loc[
            ((A | B | C | D | E) & anti_cuchillo & (dataframe['trend_ok'] | (E & trend_ok_relajado))),
            'buy'
        ] = 1

        return dataframe

    # ---------------------- SALIDAS (se ignoran señales de dataframe: use_sell_signal=False) ----------------------
    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Se mantiene por compatibilidad, pero no se usa para cerrar (control 100% en custom_exit/stoploss)
        dataframe['sell'] = 0
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
        """
        Detecta señales de desplome inminente. Activa si se cumplen >=2 condiciones.
        """
        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last = df.iloc[-1]
            prev = df.iloc[-2]

            fast_drop = (last['close'] <= last['ema8'] * 0.992) and (last['pct_1'] <= -0.7)
            atr_break = (last['low'] < last['ema_fast'] - 1.6 * last['atr'])
            bb_flush = (last['bb_percent'] < 0) and bool(last['bb_expanding']) and (last['macdhist'] < prev['macdhist'])
            di_shift = (last['adx'] > 22) and (last['minus_di'] > last['plus_di']) and (last['rsi'] < 48)

            signals = sum([fast_drop, atr_break, bb_flush or di_shift])
            return signals >= 2
        except Exception:
            return False

    # ---------------------- EXITS DISCRECIONALES (largo/medio plazo) ----------------------
    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs
    ) -> Optional[str]:
        # 1) Crash guard: si pinta feo, sal aunque el profit sea pequeño/ligeramente rojo
        if self._crash_incoming(pair):
            if current_profit is None or current_profit > -0.01:
                return "crash_guard"

        # 2) Respeta un mínimo de tiempo en mercado (para capturar tramos)
        if self._bars_elapsed(trade, current_time) < self.MIN_HOLD_BARS:
            if not self._strong_bearish_reversal(pair):
                return None

        # 3) No cierres si el beneficio no cubre comisiones + colchón
        if current_profit is not None and current_profit < self.MIN_PROFIT:
            return None

        # 4) Salida por pico técnico (cuando ya hay beneficio suficiente)
        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last = df.iloc[-1]
            prev = df.iloc[-2]
            at_peak = (last['close'] >= last['bb_upperband'] * 0.998) and (last['rsi'] >= 74)
            momentum_fading = last['macdhist'] < prev['macdhist']
            if (current_profit is not None and current_profit >= self.MIN_PROFIT) and (at_peak and momentum_fading):
                return "peak_rollover"
        except Exception:
            pass

        # 5) TP opcional si se queda lateral pero con beneficio decente (swing light)
        if current_profit is not None and 0.035 <= current_profit < 0.06:
            return "tp_3_5_to_6_percent"

        return None

    # ---------------------- TRAILING DINÁMICO (Chandelier amplio) ----------------------
    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs
    ) -> float:
        # Activa trailing más tarde para dejar correr
        if current_profit is None or current_profit < 0.05:  # 5% antes de empezar a trail
            return self.stoploss

        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last = df.iloc[-1]
            atr = float(last['atr'])
            adx = float(last['adx'])
            roc5 = float(last['roc5'])
        except Exception:
            return stoploss_from_open(current_profit, 0.02)

        strong_trend = (adx >= 25 and roc5 > 0)
        vertical_rally = (roc5 >= 3)

        # Chandelier más holgado (mejor para swing): 2.6–3.4 ATR, 2.0%–4.5%
        k = 3.4 if current_profit > 0.08 else 2.6
        dist = (k * atr) / max(current_rate, 1e-9)
        dist = min(0.045, max(0.02, dist))

        if vertical_rally:
            dist = max(dist, 0.028)  # deja respirar los pumps
        elif not strong_trend:
            dist = min(dist, 0.025)

        # Entre 5% y 8% de profit, no aprietes mucho todavía
        if 0.05 <= current_profit < 0.08:
            return stoploss_from_open(current_profit, max(0.022, dist))

        return stoploss_from_open(current_profit, dist)
