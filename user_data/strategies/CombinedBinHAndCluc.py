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
    Compras combinadas (BinHV45 + Cluc + RSI).
    Ventas MUY conservadoras: deja correr beneficios y solo cierra en picos claros o giro fuerte.
    """

    minimal_roi = {"0": 0.0}
    stoploss = -0.05
    timeframe = '5m'
    startup_candle_count = 50

    use_sell_signal = True
    sell_profit_only = True
    ignore_roi_if_buy_signal = False

    # Trailing menos agresivo (deja correr más)
    trailing_stop = True
    trailing_stop_positive = 0.030        # 3% bajo el máximo
    trailing_stop_positive_offset = 0.070 # activa a partir de +7%
    trailing_only_offset_is_reached = True

    # Retención mínima de velas (aguanta más antes de evaluar ventas discrecionales)
    MIN_HOLD_BARS = 6

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # --- BinHV45 ---
        mid, lower = bollinger_bands(dataframe['close'], window_size=40, num_of_std=2)
        dataframe['lower'] = lower
        dataframe['bbdelta'] = (mid - dataframe['lower']).abs()
        dataframe['closedelta'] = (dataframe['close'] - dataframe['close'].shift()).abs()
        dataframe['tail'] = (dataframe['close'] - dataframe['low']).abs()

        # --- Bollinger completo ---
        boll = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2)
        dataframe['bb_lowerband'] = boll['lower']
        dataframe['bb_middleband'] = boll['mid']
        dataframe['bb_upperband'] = boll['upper']

        # Medias / fuerza / volatilidad
        dataframe['ema_slow'] = ta.EMA(dataframe, timeperiod=50)
        dataframe['ema_fast'] = ta.EMA(dataframe, timeperiod=20)
        dataframe['volume_mean_slow'] = dataframe['volume'].rolling(window=30).mean()

        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['rsi_prev'] = dataframe['rsi'].shift(1)

        dataframe['adx'] = ta.ADX(dataframe, timeperiod=14)
        dataframe['plus_di'] = ta.PLUS_DI(dataframe, timeperiod=14)
        dataframe['minus_di'] = ta.MINUS_DI(dataframe, timeperiod=14)

        dataframe['atr'] = ta.ATR(dataframe, timeperiod=14)

        # muy cerca de banda superior
        dataframe['near_upper'] = (dataframe['close'] >= dataframe['bb_upperband'] * 0.997).astype(int)

        return dataframe

    # ————— ENTRADAS (igual que antes, ligerísimamente activas) —————
    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                dataframe['lower'].shift().gt(0) &
                dataframe['bbdelta'].gt(dataframe['close'] * 0.0035) &
                dataframe['closedelta'].gt(dataframe['close'] * 0.010) &
                dataframe['tail'].lt(dataframe['bbdelta'] * 0.35) &
                dataframe['close'].lt(dataframe['lower'].shift()) &
                dataframe['close'].le(dataframe['close'].shift())
            )
            |
            (
                (dataframe['close'] < dataframe['ema_slow']) &
                (dataframe['close'] < 0.997 * dataframe['bb_lowerband']) &
                (dataframe['volume'] > 0) &
                (dataframe['volume'] < (dataframe['volume_mean_slow'].shift(1) * 5))
            )
            |
            (
                (dataframe['rsi'] < 33) &
                (dataframe['close'] < dataframe['ema_slow']) &
                (dataframe['close'] < 1.01 * dataframe['bb_lowerband']) &
                (dataframe['volume'] > 0)
            ),
            'buy'
        ] = 1
        return dataframe

    # ————— VENTAS (mucho menos frecuentes) —————
    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                # Pico claro: muy cerca de la banda superior y RSI muy alto
                (dataframe['near_upper'] == 1) &
                (dataframe['rsi'] >= 78)
            )
            |
            (
                # Giro desde sobrecompra EXTREMA con tendencia (evita ruido)
                (dataframe['rsi_prev'] >= 82) & (dataframe['rsi'] < 82) &
                (dataframe['adx'] > 22)
            )
            |
            (
                # Reversal real: cruza por debajo de EMA20 - 1*ATR y DI- > DI+
                (dataframe['close'] < (dataframe['ema_fast'] - 1.0 * dataframe['atr'])) &
                (dataframe['close'].shift(1) >= (dataframe['ema_fast'].shift(1) - 1.0 * dataframe['atr'].shift(1))) &
                (dataframe['minus_di'] > dataframe['plus_di']) &
                (dataframe['rsi'] > 55)
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
            return (last['minus_di'] > last['plus_di']) and (last['adx'] > 22) and (last['rsi'] < 55)
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
        # No vender por debajo del precio de compra
        if current_rate < trade.open_rate:
            return None

        # Retención mínima salvo giro fuerte
        if self._bars_elapsed(trade, current_time) < self.MIN_HOLD_BARS:
            if not self._strong_bearish_reversal(pair):
                return None

        # TP discreto aún más alto para evitar cierres tempranos
        if current_profit is not None and current_profit >= 0.028:
            try:
                df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
                last = df.iloc[-1]
                # Solo tomar TP si hay señales de debilidad
                if (last['rsi'] < last['rsi_prev']) or (last['minus_di'] > last['plus_di']):
                    return "tp_2_8_percent_weakness"
            except Exception:
                return "tp_2_8_percent"

        return None