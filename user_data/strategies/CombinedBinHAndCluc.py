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
    Entradas combinadas (BinHV45 + Cluc + RSI).
    Salidas:
      - Más ventas en picos claros (proximidad a BB superior / RSI alto / giro).
      - Menos 'breakeven exits': evita cerrar justo tras recuperación leve.
      - Trailing stop para dejar correr ganancias.
    """

    minimal_roi = {"0": 0.0}
    stoploss = -0.05
    timeframe = '5m'
    startup_candle_count = 50

    use_sell_signal = True
    sell_profit_only = True
    ignore_roi_if_buy_signal = False

    # Trailing Stop sensible
    trailing_stop = True
    trailing_stop_positive = 0.018          # 1.8% por debajo del máximo
    trailing_stop_positive_offset = 0.04    # se activa a +4%
    trailing_only_offset_is_reached = True

    # Retención mínima y “recuperación”
    MIN_HOLD_BARS = 4
    RECOVERY_BLOCK_BARS = 24       # ~2h en 5m
    RECOVERY_MIN_PROFIT = 0.006    # 0.6%

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # --- BinHV45 ---
        mid, lower = bollinger_bands(dataframe['close'], window_size=40, num_of_std=2)
        dataframe['lower'] = lower
        dataframe['bbdelta'] = (mid - dataframe['lower']).abs()
        dataframe['closedelta'] = (dataframe['close'] - dataframe['close'].shift()).abs()
        dataframe['tail'] = (dataframe['close'] - dataframe['low']).abs()

        # --- Cluc ---
        bollinger = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2)
        dataframe['bb_lowerband'] = bollinger['lower']
        dataframe['bb_middleband'] = bollinger['mid']
        dataframe['bb_upperband'] = bollinger['upper']

        # Medias, RSI, DI/ADX y ATR
        dataframe['ema_slow'] = ta.EMA(dataframe, timeperiod=50)
        dataframe['ema_fast'] = ta.EMA(dataframe, timeperiod=20)
        dataframe['volume_mean_slow'] = dataframe['volume'].rolling(window=30).mean()
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['rsi_prev'] = dataframe['rsi'].shift(1)
        dataframe['adx'] = ta.ADX(dataframe, timeperiod=14)
        dataframe['plus_di'] = ta.PLUS_DI(dataframe, timeperiod=14)
        dataframe['minus_di'] = ta.MINUS_DI(dataframe, timeperiod=14)
        dataframe['atr'] = ta.ATR(dataframe, timeperiod=14)

        # Proximidad a banda superior (para detectar picos)
        dataframe['near_upper'] = (dataframe['close'] >= 0.995 * dataframe['bb_upperband']).astype(int)

        return dataframe

    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                # BinHV45 (moderado)
                dataframe['lower'].shift().gt(0) &
                dataframe['bbdelta'].gt(dataframe['close'] * 0.0033) &
                dataframe['closedelta'].gt(dataframe['close'] * 0.009) &
                dataframe['tail'].lt(dataframe['bbdelta'] * 0.36) &
                dataframe['close'].lt(dataframe['lower'].shift()) &
                dataframe['close'].le(dataframe['close'].shift())
            )
            |
            (
                # Cluc (moderado)
                (dataframe['close'] < dataframe['ema_slow']) &
                (dataframe['close'] < 0.9985 * dataframe['bb_lowerband']) &
                (dataframe['volume'] > 0) &
                (dataframe['volume'] < (dataframe['volume_mean_slow'].shift(1) * 5.5))
            )
            |
            (
                # RSI sobreventa controlada
                (dataframe['rsi'] < 34) &
                (dataframe['close'] < dataframe['ema_slow']) &
                (dataframe['close'] < 1.012 * dataframe['bb_lowerband']) &
                (dataframe['volume'] > 0)
            ),
            'buy'
        ] = 1
        return dataframe

    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                # 1) Pico claro: cerca de BB superior + RSI alto
                (dataframe['near_upper'] == 1) &
                (dataframe['rsi'] >= 68)
            )
            |
            (
                # 2) Giro desde sobrecompra
                (dataframe['rsi_prev'] >= 75) & (dataframe['rsi'] < 75)
            )
            |
            (
                # 3) Pérdida de momentum con filtro ATR (evita ruido)
                (dataframe['close'] < (dataframe['ema_fast'] - 0.5 * dataframe['atr'])) &
                (dataframe['close'].shift(1) >= (dataframe['ema_fast'].shift(1) - 0.5 * dataframe['atr'].shift(1))) &
                (dataframe['rsi'] > 52)
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
        # Nunca forzar venta por debajo del precio de compra
        if current_rate < trade.open_rate:
            return None

        bars = self._bars_elapsed(trade, current_time)

        # 1) Retención mínima salvo giro fuerte
        if bars < self.MIN_HOLD_BARS and not self._strong_bearish_reversal(pair):
            return None

        # 2) Guardado de recuperación: si la operación empezó mal y sólo ha recuperado poco,
        #    evita cerrar con +0.1% / +0.3% – deja margen para pillar tendencia.
        if current_profit is not None and 0.0 <= current_profit < self.RECOVERY_MIN_PROFIT:
            if bars < self.RECOVERY_BLOCK_BARS and not self._strong_bearish_reversal(pair):
                return None

        # 3) TP discreto si ya hay buen tramo y se observa ligera debilidad
        if current_profit is not None and current_profit >= 0.015:
            # pide una pequeña señal de giro para evitar cortar rallies muy fuertes
            try:
                df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
                last = df.iloc[-1]
                if (last['rsi'] < last['rsi_prev']) or (last['close'] < last['bb_upperband']):
                    return "tp_1_5_percent_weakness"
            except Exception:
                # si no hay df, aún así toma beneficio
                return "tp_1_5_percent"

        return None