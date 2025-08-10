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
    Entradas con confirmación (evitar picos y cuchillos).
    Ventas en picos + trailing adaptativo.
    Pánico: salida inmediata ante velón de caída / ruptura de mínimos.
    """

    minimal_roi = {"0": 0.0}
    stoploss = -0.05
    timeframe = '5m'
    startup_candle_count = 50

    use_sell_signal = True
    sell_profit_only = True
    ignore_roi_if_buy_signal = False

    trailing_stop = False  # usamos custom_stoploss

    MIN_HOLD_BARS = 4

    # ==== INDICADORES ====
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        mid, lower = bollinger_bands(dataframe['close'], window_size=40, num_of_std=2)
        dataframe['lower'] = lower
        dataframe['bbdelta'] = (mid - dataframe['lower']).abs()
        dataframe['closedelta'] = (dataframe['close'] - dataframe['close'].shift()).abs()
        dataframe['tail'] = (dataframe['close'] - dataframe['low']).abs()

        bb = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2)
        dataframe['bb_lowerband']  = bb['lower']
        dataframe['bb_middleband'] = bb['mid']
        dataframe['bb_upperband']  = bb['upper']
        dataframe['bb_width'] = (dataframe['bb_upperband'] - dataframe['bb_lowerband']) / dataframe['bb_middleband']

        dataframe['ema8']   = ta.EMA(dataframe, timeperiod=8)
        dataframe['ema20']  = ta.EMA(dataframe, timeperiod=20)
        dataframe['ema_fast'] = dataframe['ema20']
        dataframe['ema_slow'] = ta.EMA(dataframe, timeperiod=50)

        dataframe['volume_mean_slow'] = dataframe['volume'].rolling(window=30).mean()

        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['rsi_prev'] = dataframe['rsi'].shift(1)
        dataframe['rsi_change'] = dataframe['rsi'] - dataframe['rsi_prev']

        dataframe['adx'] = ta.ADX(dataframe, timeperiod=14)
        dataframe['adx_prev'] = dataframe['adx'].shift(1)
        dataframe['plus_di']  = ta.PLUS_DI(dataframe, timeperiod=14)
        dataframe['minus_di'] = ta.MINUS_DI(dataframe, timeperiod=14)

        stoch = ta.STOCHRSI(dataframe, timeperiod=14, fastk_period=3, fastd_period=3)
        dataframe['stoch_k'] = stoch['fastk']
        dataframe['stoch_d'] = stoch['fastd']
        dataframe['stoch_k_prev'] = dataframe['stoch_k'].shift(1)
        dataframe['stoch_d_prev'] = dataframe['stoch_d'].shift(1)

        macd = ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)
        dataframe['macd'] = macd['macd']
        dataframe['macdsignal'] = macd['macdsignal']
        dataframe['macdhist'] = macd['macdhist']

        dataframe['roc5'] = ta.ROC(dataframe, timeperiod=5)
        dataframe['atr'] = ta.ATR(dataframe, timeperiod=14)
        dataframe['ll_10'] = dataframe['low'].rolling(10).min()
        dataframe['hh_20'] = dataframe['high'].rolling(20).max()

        # Flags de “cuchillo cayendo / pico”
        body = (dataframe['close'] - dataframe['open']).abs()
        dataframe['big_red'] = (dataframe['close'] < dataframe['open']) & ((body > 0.8 * dataframe['atr']) | ((body / dataframe['close']) >= 0.01))
        dataframe['broke_ll'] = dataframe['close'] < dataframe['low'].rolling(10).min().shift(1)
        dataframe['at_peak'] = (dataframe['close'] > dataframe['bb_middleband']) | (dataframe['rsi'] > 60)

        return dataframe

    # ==== COMPRAS (menos y mejores) ====
    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Filtro de tendencia: NO comprar si microtendencia bajista
        downtrend = (
            (dataframe['ema8'] < dataframe['ema20']) |
            (dataframe['minus_di'] > dataframe['plus_di']) |
            (dataframe['roc5'] < 0)
        )

        # NO comprar en picos ni cuchillos ni tras romper mínimos
        no_buy_zone = dataframe['at_peak'] | dataframe['big_red'] | dataframe['big_red'].shift(1).fillna(False) | dataframe['broke_ll']

        dataframe.loc[
            (~downtrend) & (~no_buy_zone) & (
                # (A) Giro válido desde sobreventa + cruce EMA8
                (
                    (dataframe['low'] <= dataframe['ll_10']) &
                    (dataframe['rsi_prev'] < 32) & (dataframe['rsi'] > dataframe['rsi_prev']) &
                    (dataframe['close'].shift(1) < dataframe['ema8'].shift(1)) &
                    (dataframe['close'] > dataframe['ema8']) &
                    (dataframe['stoch_k_prev'] < dataframe['stoch_d_prev']) &
                    (dataframe['stoch_k'] > dataframe['stoch_d']) &
                    (dataframe['stoch_k'] < 30) & (dataframe['stoch_d'] < 30) &
                    (dataframe['volume'] > 0)
                )
                |
                # (B) Ruptura tras compresión (entrada de continuación)
                (
                    (dataframe['bb_width'] < dataframe['bb_width'].rolling(100).quantile(0.25)) &
                    (dataframe['close'] > dataframe['bb_middleband']) &
                    (dataframe['macdhist'] > 0) &
                    (dataframe['volume'] > dataframe['volume_mean_slow'])
                )
            ),
            'buy'
        ] = 1
        return dataframe

    # ==== VENTAS TÉCNICAS (conservadoras) ====
    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                # Reversión tras máximo local
                (dataframe['high'].shift(1) >= dataframe['hh_20'].shift(1)) &
                (dataframe['close'] < dataframe['low'].shift(1)) &
                (dataframe['rsi'] > 55)
            )
            |
            (
                # Cruce por debajo de EMA8 tras HH
                (dataframe['high'].shift(1) >= dataframe['hh_20'].shift(1)) &
                (dataframe['close'].shift(1) >= dataframe['ema8'].shift(1)) &
                (dataframe['close'] < dataframe['ema8']) &
                (dataframe['rsi'] > 50)
            )
            |
            (
                # Sobrecompra y giro
                (dataframe['rsi_prev'] >= 80) & (dataframe['rsi'] < 77)
            ),
            'sell'
        ] = 1
        return dataframe

    # ==== Helpers ====
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

    def _panic_drop(self, pair: str) -> bool:
        """Velón rojo + ruptura/cross bajistas -> salida inmediata."""
        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last = df.iloc[-1]
            body = abs(last['close'] - last['open'])
            perc = body / last['close'] if last['close'] else 0.0
            big_red = (last['close'] < last['open']) and (body > 0.7 * last['atr'] or perc >= 0.009)  # un pelín más sensible
            broke_ll = last['close'] < df['low'].rolling(10).min().iloc[-2]
            rsi_dump = (last['rsi'] < 45 and last['rsi'] < last['rsi_prev']) or ((last['rsi'] - last['rsi_prev']) <= -6)
            ema_break = (last['close'] < last['ema8']) and (last['close'] < last['ema20'])
            macd_down = last['macd'] < last['macdsignal']
            di_trend = (last['minus_di'] > last['plus_di']) and (last['adx'] > last['adx_prev'])

            return (big_red and ema_break) and (broke_ll or rsi_dump or macd_down or di_trend)
        except Exception:
            return False

    # ==== Exits discrecionales ====
    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs
    ) -> Optional[str]:
        if current_rate < trade.open_rate:
            return None

        # Venta inmediata ante caída repentina
        if self._panic_drop(pair):
            return "panic_drop"

        # Mantener mínimo de velas salvo giro feo
        if self._bars_elapsed(trade, current_time) < self.MIN_HOLD_BARS:
            if not self._strong_bearish_reversal(pair):
                return None

        # Pequeño TP para dar algo de salida cuando aún no hay rally
        if current_profit is not None and 0.012 <= current_profit < 0.03:
            return "tp_1_2_percent"

        return None

    # ==== Trailing adaptativo ====
    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs
    ) -> float:
        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last = df.iloc[-1]
            adx = float(last['adx'])
            roc5 = float(last['roc5'])
        except Exception:
            return self.stoploss

        # Pánico: apretar mucho para salir
        if self._panic_drop(pair):
            if current_profit is not None and current_profit > 0:
                return stoploss_from_open(current_profit, 0.006)  # ~0.6%
            return self.stoploss

        if current_profit is None or current_profit < 0.03:
            return self.stoploss

        strong_trend = (adx >= 25 and roc5 > 0)
        vertical_rally = (roc5 >= 3)

        if 0.03 <= current_profit < 0.06:
            trail = 0.020 if not vertical_rally else 0.025
            return stoploss_from_open(current_profit, trail)

        if strong_trend:
            trail = 0.022 if vertical_rally else 0.018
        else:
            trail = 0.015

        return stoploss_from_open(current_profit, trail)