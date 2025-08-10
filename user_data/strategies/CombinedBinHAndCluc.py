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
    - Entradas: sólo tras barrido de mínimos (sweep) + vela de giro (hammer/engulf) + confirmación.
    - Anti-cuchillos: cooldown tras velón rojo, %B con expansión, DI, % caídas recientes.
    - Salidas: crash-guard + trailing Chandelier por ATR (más holgado). Sin sell-signal estático.
    """

    minimal_roi = {"0": 0.0}
    stoploss = -0.05
    timeframe = '5m'
    startup_candle_count = 100

    # Dejamos correr más: no usamos señales de venta del dataframe
    use_sell_signal = False
    sell_profit_only = True
    ignore_roi_if_buy_signal = False

    # Trailing sólo en custom_stoploss
    trailing_stop = False

    MIN_HOLD_BARS = 4  # se ignora si hay crash

    # ---------------------- INDICADORES ----------------------
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # BinHV45 (compat)
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
        dataframe['bb_width'] = (dataframe['bb_upperband'] - dataframe['bb_lowerband']) / dataframe['bb_middleband'].replace(0, np.nan)
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

        # Stoch RSI (por si lo quieres usar en tests futuros)
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

        # Estructura HL/HH simple y régimen EMAs
        dataframe['hl_ok'] = (dataframe['low'] > dataframe['low'].shift(1)) & (dataframe['close'] > dataframe['high'].shift(1))
        dataframe['trend_ok'] = (dataframe['ema8'] > dataframe['ema_fast']) & (dataframe['ema_fast'] > dataframe['ema_slow'])

        # Velón rojo y cooldown (evitar cuchillos)
        body = (dataframe['close'] - dataframe['open']).abs()
        dataframe['big_red'] = (dataframe['close'] < dataframe['open']) & (body > 1.2 * dataframe['atr'])
        dataframe['cooldown'] = dataframe['big_red'].rolling(6).max()  # ~30 min en 5m

        return dataframe

    # ---------------------- ENTRADAS (sweep + giro) ----------------------
    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        di_edge = dataframe['plus_di'] - dataframe['minus_di']

        anti_knife = (
            (dataframe['pct_1'] > -0.6) &                    # no caida fuerte inmediata
            (dataframe['pct_3'] > -1.3) &                    # ni en 3 velas
            (~dataframe['cooldown'].astype(bool)) &          # sin velón rojo reciente
            (~((dataframe['bb_percent'] < 0) & dataframe['bb_expanding'])) &  # no %B<0 con expansión
            (di_edge >= 0) &
            (dataframe['volume'] > 0)
        )

        # Barrido de mínimos reciente + recuperación pegado a banda baja
        sweep = (
            (dataframe['low'] <= dataframe['low'].rolling(20).min()) &
            (dataframe['close'] > dataframe['low'].shift(1)) &
            (dataframe['bb_percent'] <= 0.10)
        )

        # Martillo (wick inferior grande) o envolvente alcista
        lower_wick = (np.minimum(dataframe['open'], dataframe['close']) - dataframe['low']).abs()
        body = (dataframe['close'] - dataframe['open']).abs()
        hammer = (lower_wick > 1.5 * body) & (dataframe['close'] > dataframe['open'])

        engulf = (
            (dataframe['close'] > dataframe['open']) &
            (dataframe['open'].shift(1) > dataframe['close'].shift(1)) &
            (dataframe['close'] >= dataframe['open'].shift(1)) &
            (dataframe['open'] <= dataframe['close'].shift(1))
        )

        # Confirmación mínima: romper el máximo de la vela previa
        confirm_break = (dataframe['close'] > dataframe['high'].shift(1))

        # Contexto: muy cerca de EMA8 y aún por debajo de EMA50 (rebote "desde abajo")
        near_ema8 = (dataframe['close'] >= dataframe['ema8'] * 0.995)
        below_ema50 = (dataframe['close'] <= dataframe['ema_slow'] * 1.005)

        # Rsi girando desde zona baja
        rsi_turn = (dataframe['rsi_prev'] < 35) & (dataframe['rsi'] > dataframe['rsi_prev'])

        buy_sig = sweep & (hammer | engulf) & confirm_break & near_ema8 & below_ema50 & rsi_turn

        dataframe.loc[
            buy_sig & anti_knife & dataframe['trend_ok'],
            'buy'
        ] = 1

        return dataframe

    # ---------------------- SALIDAS DISCRECIONALES ----------------------
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

        # Deja respirar el trade al menos 6 velas salvo crash
        if self._bars_elapsed(trade, current_time) < max(6, self.MIN_HOLD_BARS):
            return None

        # Pequeño TP opcional para trades lentos
        if current_profit is not None and 0.022 <= current_profit < 0.035:
            return "tp_2_2_percent"

        return None

    # ---------------------- TRAILING DINÁMICO (Chandelier ATR) ----------------------
    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs
    ) -> float:
        # Stop base si aún no hay beneficio suficiente
        if current_profit is None or current_profit < 0.03:  # activa trailing a partir de 3%
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

        # Más aire: 2.6–3.2 ATR y límites 1.6%–3.8%
        k = 3.2 if current_profit > 0.06 else 2.6
        dist = (k * atr) / max(current_rate, 1e-9)
        dist = min(0.038, max(0.016, dist))

        if vertical_rally:
            dist = max(dist, 0.024)
        elif not strong_trend:
            dist = min(dist, 0.022)

        # Entre 3% y 6% de profit, no aprietes demasiado
        if 0.03 <= current_profit < 0.06:
            return stoploss_from_open(current_profit, max(0.018, dist))

        return stoploss_from_open(current_profit, dist)
