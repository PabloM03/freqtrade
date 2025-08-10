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
    - Entradas solo en rebote/confirmación (no en mitad de caída).
    - Salidas anticipadas ante desplomes (crash guard).
    - Trailing dinámico tipo Chandelier por ATR.
    """

    minimal_roi = {"0": 0.0}
    stoploss = -0.05
    timeframe = '5m'
    startup_candle_count = 100

    use_sell_signal = True
    sell_profit_only = True
    ignore_roi_if_buy_signal = False
    trailing_stop = False  # usamos custom_stoploss

    MIN_HOLD_BARS = 4

    # ---------------------- INDICADORES ----------------------
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # BinHV45
        mid, lower = bollinger_bands(dataframe['close'], window_size=40, num_of_std=2)
        dataframe['lower'] = lower
        dataframe['bbdelta'] = (mid - dataframe['lower']).abs()
        dataframe['closedelta'] = (dataframe['close'] - dataframe['close'].shift()).abs()
        dataframe['tail'] = (dataframe['close'] - dataframe['low']).abs()

        # Bollinger (TP)
        bb = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2)
        dataframe['bb_lowerband']  = bb['lower']
        dataframe['bb_middleband'] = bb['mid']
        dataframe['bb_upperband']  = bb['upper']
        dataframe['bb_width'] = (dataframe['bb_upperband'] - dataframe['bb_lowerband']) / dataframe['bb_middleband']
        dataframe['bb_percent'] = (dataframe['close'] - dataframe['bb_lowerband']) / (
            (dataframe['bb_upperband'] - dataframe['bb_lowerband']).replace(0, np.nan)
        )
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

        # ATR y variaciones (para anti-cuchillo y crash guard)
        dataframe['atr'] = ta.ATR(dataframe, timeperiod=14)
        dataframe['pct_1'] = dataframe['close'].pct_change(1) * 100.0
        dataframe['pct_3'] = dataframe['close'].pct_change(3) * 100.0

        # Estructura HL/HH simple y regimen de EMAs
        dataframe['hl_ok'] = (dataframe['low'] > dataframe['low'].shift(1)) & (dataframe['close'] > dataframe['high'].shift(1))
        dataframe['trend_ok'] = (dataframe['ema8'] > dataframe['ema_fast']) & (dataframe['ema_fast'] > dataframe['ema_slow'])

        # Velón rojo y cooldown (evitar cuchillos)
        body = (dataframe['close'] - dataframe['open']).abs()
        dataframe['big_red'] = (dataframe['close'] < dataframe['open']) & (body > 1.2 * dataframe['atr'])
        dataframe['cooldown'] = dataframe['big_red'].rolling(6).max()  # ~30 min en 5m

        return dataframe

    # ---------------------- ENTRADAS ----------------------
    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        anti_cuchillo = (
            (dataframe['pct_1'] > -0.6) &                      # última vela no es caída fuerte
            (dataframe['pct_3'] > -1.2) &                      # 3 velas sin sangría
            (~dataframe['cooldown'].astype(bool)) &            # no venimos de velón rojo
            (~((dataframe['bb_percent'] < 0) & dataframe['bb_expanding'])) &  # no %B<0 con expansión
            (dataframe['minus_di'] <= dataframe['plus_di']) &  # DI- no domina
            (dataframe['volume'] > 0)
        )

        # (A) Rebote tras tocar zona muy baja (casi mínimo local) + confirmación básica
        A = (
            (dataframe['low'] <= dataframe['ll_10'] * 1.002) &                 # muy cerca del mínimo local
            (dataframe['close'] <= dataframe['bb_lowerband'] * 1.005) &        # pegado a banda baja
            (dataframe['rsi_prev'] < 35) & (dataframe['rsi'] > dataframe['rsi_prev']) &
            (dataframe['close'] > dataframe['open']) &
            (dataframe['hl_ok'])
        )

        # (B) Cruce de EMA8 al alza en zona baja (obligatorio estar bajo)
        B = (
            (dataframe['close'].shift(1) < dataframe['ema8'].shift(1)) &
            (dataframe['close'] > dataframe['ema8']) &
            (dataframe['close'] < dataframe['ema_slow']) &
            (dataframe['close'] <= dataframe['bb_lowerband'] * 1.01)
        )

        # (C) StochRSI profundo + MACD acompañando (algo más permisivo en sobreventa)
        C = (
            (dataframe['stoch_k_prev'] < dataframe['stoch_d_prev']) &
            (dataframe['stoch_k'] > dataframe['stoch_d']) &
            (dataframe['stoch_k'] < 25) & (dataframe['stoch_d'] < 25) &
            (dataframe['macd'] >= dataframe['macdsignal']) &
            (dataframe['minus_di'] <= dataframe['plus_di'])
        )

        # (D) Ruptura tras compresión con volumen
        D = (
            (dataframe['bb_width'] < dataframe['bb_width'].rolling(100).quantile(0.25)) &
            (dataframe['close'] > dataframe['bb_middleband']) &
            (dataframe['macdhist'] > 0) &
            (dataframe['volume'] > dataframe['volume_mean_slow'])
        )

        dataframe.loc[
            (A | B | C | D) & anti_cuchillo & dataframe['trend_ok'],
            'buy'
        ] = 1

        return dataframe

    # ---------------------- SALIDAS CLÁSICAS ----------------------
    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                # (1) Máximo local + vela de reversión
                (dataframe['high'].shift(1) >= dataframe['hh_20'].shift(1)) &
                (dataframe['close'] < dataframe['low'].shift(1)) &
                (dataframe['rsi'] > 55)
            )
            |
            (
                # (2) Cruce por debajo de EMA8 tras HH
                (dataframe['high'].shift(1) >= dataframe['hh_20'].shift(1)) &
                (dataframe['close'].shift(1) >= dataframe['ema8'].shift(1)) &
                (dataframe['close'] < dataframe['ema8']) &
                (dataframe['rsi'] > 50)
            )
            |
            (
                # (3) Sobrecompra y giro
                (dataframe['rsi_prev'] >= 80) & (dataframe['rsi'] < 77)
            )
            |
            (
                # (4) Pico claro: toca/roza máximos recientes con RSI alto
                (dataframe['high'] >= dataframe['hh_20']) &
                (dataframe['rsi'] > 75)
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

    # ---------------------- EXITS DISCRECIONALES ----------------------
    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs
    ) -> Optional[str]:
        # Protección por crash: sal rápido aunque el profit sea pequeño
        if self._crash_incoming(pair):
            if current_profit is None or current_profit > -0.005:
                return "crash_guard"

        if current_rate < trade.open_rate:
            return None

        # Mínimo de barras salvo giro feo
        if self._bars_elapsed(trade, current_time) < self.MIN_HOLD_BARS:
            if not self._strong_bearish_reversal(pair):
                return None

        # Si no hay gran impulso, toma un 1.2%
        if current_profit is not None and 0.012 <= current_profit < 0.03:
            return "tp_1_2_percent"

        return None

    # ---------------------- TRAILING DINÁMICO (Chandelier + contexto) ----------------------
    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs
    ) -> float:
        # Stop base si no hay datos o profit bajo
        if current_profit is None or current_profit < 0.02:
            return self.stoploss

        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last = df.iloc[-1]
            atr = float(last['atr'])
            adx = float(last['adx'])
            roc5 = float(last['roc5'])
        except Exception:
            return stoploss_from_open(current_profit, 0.015)

        strong_trend = (adx >= 25 and roc5 > 0)
        vertical_rally = (roc5 >= 3)

        # Chandelier distance (en % desde open)
        k = 2.5 if current_profit > 0.05 else 2.0
        chandelier_dist = max(0.012, min(0.03, (k * atr) / max(current_rate, 1e-9)))

        # Afinado por contexto
        if vertical_rally:
            chandelier_dist = max(chandelier_dist, 0.022)
        elif not strong_trend:
            chandelier_dist = min(chandelier_dist, 0.018)

        # Si profit entre 3% y 6%, aprieta un poco más
        if 0.03 <= current_profit < 0.06:
            return stoploss_from_open(current_profit, max(0.015, chandelier_dist * 0.9))

        return stoploss_from_open(current_profit, chandelier_dist)
