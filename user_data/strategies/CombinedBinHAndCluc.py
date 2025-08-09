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
    Entradas combinadas (BinHV45 + Cluc + RSI) con filtros moderados.
    Salidas: trailing stop sensible + tomas de beneficio y señal técnica por debilidad.
    """

    # Deja correr ganancias (sin ROI fijo)
    minimal_roi = {"0": 0.0}
    stoploss = -0.05
    timeframe = '5m'
    startup_candle_count = 50

    use_sell_signal = True
    sell_profit_only = True
    ignore_roi_if_buy_signal = False

    # Trailing Stop - menos agresivo (reduce cierres prematuros)
    trailing_stop = True
    trailing_stop_positive = 0.025          # antes 0.02
    trailing_stop_positive_offset = 0.07    # antes 0.05 (activa trailing a partir de +7%)
    trailing_only_offset_is_reached = True

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
        dataframe['rsi_prev'] = dataframe['rsi'].shift(1)

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
            ),
            'buy'
        ] = 1
        return dataframe

    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Salidas con debilitamiento (reduce “demasiadas ventas”)
        dataframe.loc[
            (
                # 1) Cruce por encima de la banda media PERO con RSI debilitándose
                (dataframe['close'] > dataframe['bb_middleband']) &
                (dataframe['close'].shift(1) <= dataframe['bb_middleband'].shift(1)) &
                (dataframe['rsi'] > 62) &                     # era 60
                (dataframe['rsi'] < dataframe['rsi_prev']) &  # RSI bajando (confirmación de debilidad)
                (dataframe['volume'] > dataframe['volume_mean_slow'])
            )
            |
            (
                # 2) Take profit por debilidad: RSI cruza abajo desde zona alta
                (dataframe['rsi_prev'] >= 72) & (dataframe['rsi'] < 68) &     # más exigente
                (dataframe['close'] < dataframe['bb_upperband'])
            )
            |
            (
                # 3) Pérdida de momentum: EMA20 cruce bajista + RSI no fuerte
                (dataframe['close'] < dataframe['ema_fast']) &
                (dataframe['close'].shift(1) >= dataframe['ema_fast'].shift(1)) &
                (dataframe['rsi'] < 60)                                        # antes >50
            ),
            'sell'
        ] = 1
        return dataframe

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
        2) TP discreto algo más alto para evitar cierres demasiado rápidos.
        """
        # 1) No vender con pérdida desde aquí (stoploss/trailing siguen funcionando)
        if current_rate < trade.open_rate:
            return None

        # 2) TP discreto moderado (subido para vender menos)
        if current_profit is not None and current_profit >= 0.025:  # antes 0.015
            return "tp_2_5_percent"

        return None