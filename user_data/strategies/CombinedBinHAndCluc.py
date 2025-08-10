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
    Estrategia combinada:
    - Compras por BinHV45, Cluc, RSI sobreventa y confirmación MACD/tendencia.
    - Ventas por momentum / reversión y trailing dinámico (custom_stoploss).
    - Mantiene un hold mínimo corto salvo giro bajista claro.
    """

    minimal_roi = {"0": 0.0}
    stoploss = -0.05
    timeframe = '5m'
    startup_candle_count = 50

    use_sell_signal = True
    sell_profit_only = True
    ignore_roi_if_buy_signal = False

    # Desactivamos trailing estático; usamos custom_stoploss dinámico
    trailing_stop = False

    # Retención mínima de velas (5m) para no cerrar “al rebote” si no hay giro feo
    MIN_HOLD_BARS = 4

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # --- BinHV45 básicos ---
        mid, lower = bollinger_bands(dataframe['close'], window_size=40, num_of_std=2)
        dataframe['lower'] = lower
        dataframe['bbdelta'] = (mid - dataframe['lower']).abs()
        dataframe['closedelta'] = (dataframe['close'] - dataframe['close'].shift()).abs()
        dataframe['tail'] = (dataframe['close'] - dataframe['low']).abs()

        # --- Bollinger clásicos ---
        bb = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2)
        dataframe['bb_lowerband'] = bb['lower']
        dataframe['bb_middleband'] = bb['mid']
        dataframe['bb_upperband'] = bb['upper']
        # Anchura de banda (compresión/expansión)
        dataframe['bb_width'] = (dataframe['bb_upperband'] - dataframe['bb_lowerband']) / dataframe['bb_middleband']

        # Medias y fuerza
        dataframe['ema_fast'] = ta.EMA(dataframe, timeperiod=20)
        dataframe['ema_slow'] = ta.EMA(dataframe, timeperiod=50)
        dataframe['volume_mean_slow'] = dataframe['volume'].rolling(window=30).mean()

        # RSI / ADX / DI
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['rsi_prev'] = dataframe['rsi'].shift(1)
        dataframe['adx'] = ta.ADX(dataframe, timeperiod=14)
        dataframe['plus_di'] = ta.PLUS_DI(dataframe, timeperiod=14)
        dataframe['minus_di'] = ta.MINUS_DI(dataframe, timeperiod=14)

        # MACD
        macd = ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)
        dataframe['macd'] = macd['macd']
        dataframe['macdsignal'] = macd['macdsignal']
        dataframe['macdhist'] = macd['macdhist']

        # Pendiente / momentum (ROC 5 velas)
        dataframe['roc5'] = ta.ROC(dataframe, timeperiod=5)

        # Máximo local reciente (para reversión)
        dataframe['hh_20'] = dataframe['high'].rolling(20).max()

        return dataframe

    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                # --- BinHV45 (ligeramente más laxo que el original) ---
                dataframe['lower'].shift().gt(0) &
                dataframe['bbdelta'].gt(dataframe['close'] * 0.0033) &
                dataframe['closedelta'].gt(dataframe['close'] * 0.009) &
                dataframe['tail'].lt(dataframe['bbdelta'] * 0.36) &
                dataframe['close'].lt(dataframe['lower'].shift()) &
                dataframe['close'].le(dataframe['close'].shift())
            )
            |
            (
                # --- Cluc (moderado) ---
                (dataframe['close'] < dataframe['ema_slow']) &
                (dataframe['close'] < 0.9985 * dataframe['bb_lowerband']) &
                (dataframe['volume'] > 0) &
                (dataframe['volume'] < (dataframe['volume_mean_slow'].shift(1) * 5.5))
            )
            |
            (
                # --- Sobreventa controlada ---
                (dataframe['rsi'] < 34) &
                (dataframe['close'] < dataframe['ema_slow']) &
                (dataframe['close'] < 1.012 * dataframe['bb_lowerband']) &
                (dataframe['volume'] > 0)
            )
            |
            (
                # --- Confirmación de tendencia con MACD + pullback suave ---
                (dataframe['ema_fast'] > dataframe['ema_slow']) &
                (dataframe['macd'] > dataframe['macdsignal']) &
                (dataframe['close'] >= dataframe['ema_fast'] * 0.995) &   # compra “un pelín” antes pero no persigue
                (dataframe['rsi'] > 45)
            )
            |
            (
                # --- Ruptura tras compresión (BBWidth bajo -> expansión) ---
                (dataframe['bb_width'] < dataframe['bb_width'].rolling(100).quantile(0.25)) &
                (dataframe['close'] > dataframe['bb_middleband']) &
                (dataframe['macdhist'] > 0) &
                (dataframe['volume'] > dataframe['volume_mean_slow'])
            ),
            'buy'
        ] = 1
        return dataframe

    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                # 1) Cruce alcista de la banda media + fuerza (take profit técnico)
                (dataframe['close'] > dataframe['bb_middleband']) &
                (dataframe['close'].shift(1) <= dataframe['bb_middleband'].shift(1)) &
                (dataframe['rsi'] > 60) &
                (dataframe['volume'] > dataframe['volume_mean_slow'])
            )
            |
            (
                # 2) Sobrecompra y giro (menos nervioso que antes)
                (dataframe['rsi_prev'] >= 78) & (dataframe['rsi'] < 75)
            )
            |
            (
                # 3) Pérdida de momentum: cruce por debajo de EMA20 con RSI no débil
                (dataframe['close'] < dataframe['ema_fast']) &
                (dataframe['close'].shift(1) >= dataframe['ema_fast'].shift(1)) &
                (dataframe['rsi'] < 60) & (dataframe['rsi'] > 48)
            )
            |
            (
                # 4) Reversión cerca de máximos: cierra por debajo del mínimo previo tras marcar HH
                (dataframe['high'].shift(1) >= dataframe['hh_20'].shift(1)) &
                (dataframe['close'] < dataframe['low'].shift(1)) &
                (dataframe['rsi'] > 55)
            ),
            'sell'
        ] = 1
        return dataframe

    # --------- Utilidades de salida ---------

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
        2) Hold mínimo salvo giro bajista claro.
        3) Pequeño TP discreto si aún no hay gran tendencia.
        """
        if current_rate < trade.open_rate:
            return None

        # Hold mínimo de velas salvo giro feo
        if self._bars_elapsed(trade, current_time) < self.MIN_HOLD_BARS:
            if not self._strong_bearish_reversal(pair):
                return None

        # TP discreto para no dejar escapar beneficios pequeños cuando no hay impulso
        if current_profit is not None and 0.012 <= current_profit < 0.03:
            return "tp_1_2_percent"

        return None

    # --------- Trailing dinámico (desde beneficio) ----------
    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs
    ) -> float:
        """
        Trailing dinámico según la fuerza/pediente:
        - Profit < 3%: mantener SL amplio (usa stoploss base).
        - Profit 3–6%: trailing ~2.0% si la tendencia es normal; 2.5% si el rally es muy fuerte.
        - Profit > 6%: aflojamos si ADX/pediente son altos para dejar correr; si se debilita, lo estrechamos.
        """
        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last = df.iloc[-1]
            adx = float(last['adx'])
            roc5 = float(last['roc5'])
        except Exception:
            # Sin datos: usa SL base
            return self.stoploss

        # Sin ganancia: SL base
        if current_profit is None or current_profit < 0.03:
            return self.stoploss

        # Definimos trailing (distancia desde el máximo) en función de fuerza (ADX) y pendiente (ROC5)
        # Nota: stoploss_from_open simula trailing desde beneficio acumulado.
        # Rallies fuertes -> trailing más holgado para exprimir subida
        strong_trend = (adx >= 25 and roc5 > 0)
        vertical_rally = (roc5 >= 3)  # % en 5 velas aprox.

        if 0.03 <= current_profit < 0.06:
            trail = 0.020 if not vertical_rally else 0.025
            return stoploss_from_open(current_profit, trail)

        # > 6% de beneficio
        if strong_trend:
            trail = 0.022 if vertical_rally else 0.018  # aflojamos un poco si va “en cohete”
        else:
            trail = 0.015  # más ceñido si la fuerza cae

        return stoploss_from_open(current_profit, trail)