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
    Estrategia optimizada:
    - Compras: más permisivas en mínimos locales y sobreventa.
    - Ventas: más relajadas pero solo en picos claros con beneficio.
    - Filtro de tendencia medio-largo plazo para evitar compras en techos de montaña.
    """

    # Comisiones estimadas
    FEE_RATE = 0.001
    SLIPPAGE_BUFFER = 0.0005
    MIN_PROFIT_NET = 2 * FEE_RATE + SLIPPAGE_BUFFER

    PEAK_MIN_PROFIT = 0.0075  # antes 0.009
    HH_EMA_MIN_PROFIT = 0.006

    minimal_roi = {"0": 0.0}
    stoploss = -0.05
    timeframe = '5m'
    startup_candle_count = 100

    use_sell_signal = True
    sell_profit_only = True
    ignore_roi_if_buy_signal = False
    trailing_stop = False

    MIN_HOLD_BARS = 2

    # ---------------------- INDICADORES ----------------------
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        mid, lower = bollinger_bands(dataframe['close'], 40, 2)
        dataframe['lower'] = lower

        tp = qtpylib.typical_price(dataframe)
        bb = qtpylib.bollinger_bands(tp, 20, 2)
        dataframe['bb_lowerband'] = bb['lower']
        dataframe['bb_middleband'] = bb['mid']
        dataframe['bb_upperband'] = bb['upper']
        dataframe['bb_width'] = (dataframe['bb_upperband'] - dataframe['bb_lowerband']) / dataframe['bb_middleband']
        denom = (dataframe['bb_upperband'] - dataframe['bb_lowerband']).replace(0, np.nan)
        dataframe['bb_percent'] = (dataframe['close'] - dataframe['bb_lowerband']) / denom
        dataframe['bb_expanding'] = (dataframe['bb_width'] > dataframe['bb_width'].shift(1))

        dataframe['ema8'] = ta.EMA(dataframe, 8)
        dataframe['ema_fast'] = ta.EMA(dataframe, 20)
        dataframe['ema_slow'] = ta.EMA(dataframe, 50)
        dataframe['ema_long'] = ta.EMA(dataframe, 100)
        dataframe['volume_mean_slow'] = dataframe['volume'].rolling(30).mean()

        dataframe['rsi'] = ta.RSI(dataframe, 14)
        dataframe['rsi_prev'] = dataframe['rsi'].shift(1)

        dataframe['adx'] = ta.ADX(dataframe, 14)
        dataframe['plus_di'] = ta.PLUS_DI(dataframe, 14)
        dataframe['minus_di'] = ta.MINUS_DI(dataframe, 14)

        stoch = ta.STOCHRSI(dataframe, 14, 3, 3)
        dataframe['stoch_k'] = stoch['fastk']
        dataframe['stoch_d'] = stoch['fastd']
        dataframe['stoch_k_prev'] = dataframe['stoch_k'].shift(1)
        dataframe['stoch_d_prev'] = dataframe['stoch_d'].shift(1)

        macd = ta.MACD(dataframe, 12, 26, 9)
        dataframe['macd'] = macd['macd']
        dataframe['macdsignal'] = macd['macdsignal']
        dataframe['macdhist'] = macd['macdhist']

        dataframe['roc5'] = ta.ROC(dataframe, 5)
        dataframe['ll_10'] = dataframe['low'].rolling(10).min()
        dataframe['hh_20'] = dataframe['high'].rolling(20).max()
        dataframe['ll_20'] = dataframe['low'].rolling(20).min()

        dataframe['atr'] = ta.ATR(dataframe, 14)
        dataframe['pct_1'] = dataframe['close'].pct_change(1) * 100.0
        dataframe['pct_3'] = dataframe['close'].pct_change(3) * 100.0

        dataframe['hl_ok'] = (dataframe['low'] > dataframe['low'].shift(1)) & (dataframe['close'] > dataframe['high'].shift(1))
        dataframe['trend_ok'] = (dataframe['ema8'] > dataframe['ema_fast']) & (dataframe['ema_fast'] > dataframe['ema_slow'])

        body = (dataframe['close'] - dataframe['open']).abs()
        dataframe['big_red'] = (dataframe['close'] < dataframe['open']) & (body > 1.2 * dataframe['atr'])
        dataframe['cooldown'] = dataframe['big_red'].rolling(5).max()

        # Sesgo de tendencia medio-largo plazo
        dataframe['trend_bias'] = np.where(
            (dataframe['ema_slow'] > dataframe['ema_long']) & (dataframe['close'] > dataframe['ema_slow']),
            1,  # alcista
            np.where(
                (dataframe['ema_slow'] < dataframe['ema_long']) & (dataframe['close'] < dataframe['ema_slow']),
                -1,  # bajista
                0    # neutro
            )
        )

        return dataframe

    # ---------------------- COMPRAS ----------------------
    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        anti_cuchillo = (
            (dataframe['pct_1'] > -1.0) &
            (dataframe['pct_3'] > -2.0) &
            (~dataframe['cooldown'].astype(bool)) &
            (~((dataframe['bb_percent'] < 0) & dataframe['bb_expanding'])) &
            (dataframe['minus_di'] <= dataframe['plus_di']) &
            (dataframe['volume'] > 0)
        )

        deep_bb = (dataframe['bb_percent'] <= 0.20)
        lower_wick = (np.minimum(dataframe['open'], dataframe['close']) - dataframe['low']).abs()
        body = (dataframe['close'] - dataframe['open']).abs()
        hammerish = lower_wick > 1.1 * body

        A = (
            ((dataframe['low'] <= dataframe['ll_20'] * 1.008) | deep_bb) &
            hammerish &
            (dataframe['rsi_prev'] < 48) &
            (dataframe['rsi'] > dataframe['rsi_prev']) &
            (dataframe['close'] >= dataframe['open'])
        )

        # Compras incluso en tendencia bajista si sobreventa extrema
        A = A & (
            (dataframe['trend_bias'] == 1) |
            ((dataframe['trend_bias'] == -1) & (dataframe['rsi'] < 30) & deep_bb)
        )

        dataframe.loc[A & anti_cuchillo, 'buy'] = 1
        return dataframe

    # ---------------------- VENTAS ----------------------
    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe['close'] >= dataframe['bb_upperband'] * 0.997) &
                (dataframe['rsi'] >= 70) &
                (
                    (dataframe['macdhist'] < dataframe['macdhist'].shift(1)) |
                    (dataframe['close'] < dataframe['ema8'])
                )
            ),
            'sell'
        ] = 1
        return dataframe