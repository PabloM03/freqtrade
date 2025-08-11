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
        df['atr'] = ta.ATR(df, timeperiod=14)
        return df

    def populate_buy_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        # Anti-cuchillo estricto
        anti_cuchillo = (df['pct_1'] > -0.9) & (df['pct_3'] > -1.8)

        # Excepción: capitulación con rebote claro
        cap_rebote = (
            ((df['pct_1'] <= -1.8) | (df['pct_3'] <= -3.5)) &
            (df['close'] > df['open']) &
            (df['rsi'] > df['rsi'].shift(1)) &
            ((df['open'] - df['low']) > df['atr'] * 0.8)
        )

        # Zona óptima para comprar
        zona_profunda = (df['close'] <= df['bb_lower'] * 1.004)
        rebote_fuerte = (df['close'] > df['open']) & (df['rsi'] > df['rsi'].shift(1))

        df.loc[(zona_profunda & rebote_fuerte & anti_cuchillo) | cap_rebote, 'buy'] = 1
        return df

    def populate_sell_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        # Pico óptimo con confirmación de giro
        pico_optimo = (
            (df['close'] >= df['bb_upper'] * 0.998) &
            (df['rsi'] >= 69) &
            (df['close'] < df['close'].shift(1))
        )
        df.loc[pico_optimo, 'sell'] = 1
        return df
