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
    - Compras: rebote en mínimos locales con filtro anti-cuchillo inteligente.
    - Ventas: en picos locales óptimos.
    """

    FEE_RATE = 0.001
    SLIPPAGE_BUFFER = 0.0005
    MIN_PROFIT_NET = 2 * FEE_RATE + SLIPPAGE_BUFFER
    PEAK_MIN_PROFIT = 0.0085
    HH_EMA_MIN_PROFIT = 0.008
    HARD_TP = 0.018

    minimal_roi = {"0": 0.0}
    stoploss = -0.05
    timeframe = '5m'
    startup_candle_count = 100

    use_sell_signal = True
    sell_profit_only = True
    ignore_roi_if_buy_signal = False
    trailing_stop = False

    MIN_HOLD_BARS = 2

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        mid, lower = bollinger_bands(dataframe['close'], 40, 2)
        dataframe['lower'] = lower
        dataframe['bbdelta'] = (mid - dataframe['lower']).abs()
        dataframe['closedelta'] = (dataframe['close'] - dataframe['close'].shift()).abs()
        dataframe['tail'] = (dataframe['close'] - dataframe['low']).abs()

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
        dataframe['volume_mean_slow'] = dataframe['volume'].rolling(30).mean()
        dataframe['ema8_slope_up'] = dataframe['ema8'] > dataframe['ema8'].shift(1)

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
        dataframe['ll_8'] = dataframe['low'].rolling(8).min()

        dataframe['atr'] = ta.ATR(dataframe, 14)
        dataframe['pct_1'] = dataframe['close'].pct_change(1) * 100.0
        dataframe['pct_3'] = dataframe['close'].pct_change(3) * 100.0

        body = (dataframe['close'] - dataframe['open']).abs()
        dataframe['big_red'] = (dataframe['close'] < dataframe['open']) & (body > 1.2 * dataframe['atr'])
        dataframe['cooldown'] = dataframe['big_red'].rolling(5).max()

        dataframe['upper_wick'] = (dataframe['high'] - np.maximum(dataframe['open'], dataframe['close'])).abs()
        dataframe['vol_spike'] = dataframe['volume'] > (dataframe['volume_mean_slow'] * 1.15)

        return dataframe

    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Anti-cuchillo inteligente
        knife = (dataframe['pct_1'] <= -1.0) & (dataframe['pct_3'] <= -2.0)
        rebound = (
            (dataframe['close'] > dataframe['open']) &
            (dataframe['rsi'] > dataframe['rsi_prev']) &
            ((dataframe['close'] - dataframe['low']) >= 0.005 * dataframe['close'])
        )
        anti_cuchillo = (~knife) | (knife & rebound)

        deep_bb = (dataframe['bb_percent'] <= 0.15)
        bb_zone_low = (dataframe['bb_percent'] <= 0.30)
        lower_wick = (np.minimum(dataframe['open'], dataframe['close']) - dataframe['low']).abs()
        body = (dataframe['close'] - dataframe['open']).abs()
        hammerish = lower_wick > 1.1 * body

        A = (
            ((dataframe['low'] <= dataframe['ll_20'] * 1.005) | deep_bb) &
            hammerish &
            (dataframe['rsi_prev'] < 45) & (dataframe['rsi'] > dataframe['rsi_prev']) &
            (dataframe['close'] >= dataframe['open'])
        )

        B = (
            (dataframe['close'].shift(1) < dataframe['ema8'].shift(1)) &
            (dataframe['close'] > dataframe['ema8']) &
            (dataframe['close'] <= dataframe['bb_lowerband'] * 1.02)
        )

        C = (
            (dataframe['stoch_k_prev'] < dataframe['stoch_d_prev']) &
            (dataframe['stoch_k'] > dataframe['stoch_d']) &
            (dataframe['stoch_k'] < 33) & (dataframe['stoch_d'] < 33) &
            deep_bb
        )

        dataframe.loc[((A | B | C) & anti_cuchillo), 'buy'] = 1
        return dataframe

    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        reject_upper = (
            (dataframe['upper_wick'] >= dataframe['atr'] * 0.9) &
            ((dataframe['high'] >= dataframe['bb_upperband'] * 0.998) | (dataframe['close'] >= dataframe['bb_upperband'])) &
            (dataframe['rsi'] >= 60)
        )
        dataframe.loc[
            (
                (dataframe['high'] >= dataframe['hh_20'] * 0.999) &
                (dataframe['close'] >= dataframe['bb_upperband'] * 0.997) &
                (dataframe['rsi'] >= 70) &
                ((dataframe['close'] < dataframe['open']) | (dataframe['macdhist'] < dataframe['macdhist'].shift(1)))
            )
            |
            reject_upper,
            'sell'
        ] = 1
        return dataframe