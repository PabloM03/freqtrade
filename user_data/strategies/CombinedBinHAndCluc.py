import talib.abstract as ta
from freqtrade.strategy.interface import IStrategy
from pandas import DataFrame

class SimplePeakRebound(IStrategy):
    timeframe = '5m'
    stoploss = -0.05
    minimal_roi = {"0": 0}

    def populate_indicators(self, df: DataFrame, metadata: dict) -> DataFrame:
        df['rsi'] = ta.RSI(df, timeperiod=14)
        df['ema8'] = ta.EMA(df, timeperiod=8)
        df['ema50'] = ta.EMA(df, timeperiod=50)
        bb = ta.BBANDS(df['close'], timeperiod=20, nbdevup=2, nbdevdn=2)
        df['bb_lower'], df['bb_mid'], df['bb_upper'] = bb
        df['pct_1'] = df['close'].pct_change(1) * 100
        df['pct_3'] = df['close'].pct_change(3) * 100
        return df

    def populate_buy_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        anti_cuchillo = (df['pct_1'] > -1.0) & (df['pct_3'] > -2.0)
        rebote_fuerte = (df['close'] > df['open']) & (df['rsi'] > df['rsi'].shift(1))
        zona_profunda = (df['close'] <= df['bb_lower'] * 1.005)
        df.loc[anti_cuchillo & rebote_fuerte & zona_profunda, 'buy'] = 1
        return df

    def populate_sell_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        pico_optimo = (
            (df['close'] >= df['bb_upper'] * 0.999) &
            (df['rsi'] >= 70) &
            (df['close'] < df['close'].shift(1))
        )
        df.loc[pico_optimo, 'sell'] = 1
        return df
