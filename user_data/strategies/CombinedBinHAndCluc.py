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
    Basado en tu versión:
    - Entradas igual que las que me diste.
    - Ventas más filtradas: RSI más alto + cruce + volumen.
    """

    minimal_roi = {
        "0": 0.05
    }
    stoploss = -0.05
    timeframe = '5m'
    startup_candle_count = 50  # asegura EMA/BB listos antes de generar señales

    use_sell_signal = True
    sell_profit_only = True
    ignore_roi_if_buy_signal = False

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

        dataframe['ema_slow'] = ta.EMA(dataframe, timeperiod=50)
        dataframe['volume_mean_slow'] = dataframe['volume'].rolling(window=30).mean()

        # RSI para filtrar salidas
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)

        return dataframe

    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                # --- BinHV45 ---
                dataframe['lower'].shift().gt(0) &
                dataframe['bbdelta'].gt(dataframe['close'] * 0.004) &
                dataframe['closedelta'].gt(dataframe['close'] * 0.012) &
                dataframe['tail'].lt(dataframe['bbdelta'] * 0.30) &
                dataframe['close'].lt(dataframe['lower'].shift()) &
                dataframe['close'].le(dataframe['close'].shift())
            )
            |
            (
                # --- Cluc ---
                (dataframe['close'] < dataframe['ema_slow']) &
                (dataframe['close'] < 0.995 * dataframe['bb_lowerband']) &
                (dataframe['volume'] > 0) &
                (dataframe['volume'] < (dataframe['volume_mean_slow'].shift(1) * 4))
            ),
            'buy'
        ] = 1
        return dataframe

    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Mantener filtro técnico, pero sin 'buy_price'
        dataframe.loc[
            (
                (dataframe['close'] > dataframe['bb_middleband']) &
                (dataframe['close'].shift(1) <= dataframe['bb_middleband'].shift(1)) &  # cruce al alza
                (dataframe['rsi'] > 60) &
                (dataframe['volume'] > dataframe['volume_mean_slow'])
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
        Bloquea ventas si el precio actual está por debajo del precio de compra.
        """
        if current_rate < trade.open_rate:
            return None  # No vender todavía

        # Dejar que la lógica de 'populate_sell_trend' se encargue si el precio es >= open_rate
        return None
