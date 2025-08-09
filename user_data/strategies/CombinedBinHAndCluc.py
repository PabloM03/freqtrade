# --- Do not remove these libs ---
import freqtrade.vendor.qtpylib.indicators as qtpylib
import numpy as np
# --------------------------------
import talib.abstract as ta
from freqtrade.strategy.interface import IStrategy
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
    Entradas combinadas (BinHV45 + Cluc + RSI) + Breakout fuerte.
    Salidas: trailing + señales técnicas, con retención mínima si no hay giro claro
             y salida por sobreextensión en rallies.
    """

    minimal_roi = {"0": 0.0}
    stoploss = -0.05
    timeframe = '5m'
    startup_candle_count = 50

    use_sell_signal = True
    sell_profit_only = True
    ignore_roi_if_buy_signal = False

    # Trailing Stop
    trailing_stop = True
    trailing_stop_positive = 0.02           # 2% por debajo del máximo
    trailing_stop_positive_offset = 0.05    # se activa a partir de +5%
    trailing_only_offset_is_reached = True

    # Retención mínima
    MIN_HOLD_BARS = 4

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # --- BinHV45 ---
        mid, lower = bollinger_bands(dataframe['close'], window_size=40, num_of_std=2)
        dataframe['lower'] = lower
        dataframe['bbdelta'] = (mid - dataframe['lower']).abs()
        dataframe['closedelta'] = (dataframe['close'] - dataframe['close'].shift()).abs()
        dataframe['tail'] = (dataframe['close'] - dataframe['low']).abs()

        # --- ClucMay72018 ---
        bollinger = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2)
        dataframe['bb_lowerband'] = bollinger['lower']
        dataframe['bb_middleband'] = bollinger['mid']
        dataframe['bb_upperband'] = bollinger['upper']

        # Medias y RSI
        dataframe['ema_slow'] = ta.EMA(dataframe, timeperiod=50)
        dataframe['ema_fast'] = ta.EMA(dataframe, timeperiod=20)
        dataframe['volume_mean_slow'] = dataframe['volume'].rolling(window=30).mean()
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)

        # Fuerza direccional para giros
        dataframe['adx'] = ta.ADX(dataframe, timeperiod=14)
        dataframe['plus_di'] = ta.PLUS_DI(dataframe, timeperiod=14)
        dataframe['minus_di'] = ta.MINUS_DI(dataframe, timeperiod=14)

        return dataframe

    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                # --- BinHV45 (moderado) ---
                dataframe['lower'].shift().gt(0) &
                dataframe['bbdelta'].gt(dataframe['close'] * 0.0035) &
                dataframe['closedelta'].gt(dataframe['close'] * 0.010) &
                dataframe['tail'].lt(dataframe['bbdelta'] * 0.35) &
                dataframe['close'].lt(dataframe['lower'].shift()) &
                dataframe['close'].le(dataframe['close'].shift())
            )
            |
            (
                # --- Cluc (moderado) ---
                (dataframe['close'] < dataframe['ema_slow']) &
                (dataframe['close'] < 0.997 * dataframe['bb_lowerband']) &
                (dataframe['volume'] > 0) &
                (dataframe['volume'] < (dataframe['volume_mean_slow'].shift(1) * 5))
            )
            |
            (
                # --- Sobreventa controlada ---
                (dataframe['rsi'] < 33) &
                (dataframe['close'] < dataframe['ema_slow']) &
                (dataframe['close'] < 1.01 * dataframe['bb_lowerband']) &
                (dataframe['volume'] > 0)
            )
            |
            (
                # --- NUEVO: Breakout fuerte por momentum ---
                (dataframe['close'] > dataframe['bb_upperband']) &                         # rompe banda superior
                (dataframe['close'] > dataframe['close'].shift(1) * 1.01) &               # +1% en la última vela
                (dataframe['volume'] > dataframe['volume_mean_slow'] * 2) &               # volumen elevado
                (dataframe['rsi'] > 60) & (dataframe['rsi'] < 80)                          # fuerza, sin sobrecompra extrema
            ),
            'buy'
        ] = 1
        return dataframe

    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                # 1) Cruce por encima de la banda media + algo de fuerza
                (dataframe['close'] > dataframe['bb_middleband']) &
                (dataframe['close'].shift(1) <= dataframe['bb_middleband'].shift(1)) &
                (dataframe['rsi'] > 60) &
                (dataframe['volume'] > dataframe['volume_mean_slow'])
            )
            |
            (
                # 2) Pérdida de momentum: baja de EMA20 tras estar encima
                (dataframe['close'] < dataframe['ema_fast']) &
                (dataframe['close'].shift(1) >= dataframe['ema_fast'].shift(1)) &
                (dataframe['rsi'] > 53)
            )
            |
            (
                # --- NUEVO: Salida por sobreextensión del rally ---
                (dataframe['rsi'] > 80) &                                                # sobrecompra fuerte
                (dataframe['close'] > dataframe['bb_upperband'] * 1.02) &                # 2% por encima de banda sup.
                (dataframe['close'] < dataframe['close'].shift(1))                       # primera señal de retroceso
            ),
            'sell'
        ] = 1
        return dataframe

    def _bars_elapsed(self, trade: Trade, current_time: datetime) -> int:
        tf_minutes = int(self.timeframe.rstrip('m'))
        seconds = (current_time - trade.open_date_utc).total_seconds()
        return int(max(0, seconds) // (tf_minutes * 60))

    def _strong_bearish_reversal(self, pair: str) -> bool:
        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last = df.iloc[-1]
            return (last['minus_di'] > last['plus_di']) and (last['adx'] > 20) and (last['rsi'] < 55)
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
        """
        1) Nunca forzar venta por debajo del precio de compra.
        2) Retención mínima de 4 velas salvo giro fuerte.
        3) TP discreto si aún no se activó trailing y vamos >= +1.5%.
        """
        if current_rate < trade.open_rate:
            return None

        if self._bars_elapsed(trade, current_time) < self.MIN_HOLD_BARS:
            if not self._strong_bearish_reversal(pair):
                return None

        if current_profit is not None and current_profit >= 0.015:
            return "tp_1_5_percent"

        return None