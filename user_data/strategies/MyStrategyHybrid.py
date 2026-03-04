"""
MyStrategyHybrid — CombinedBinHAndCluc (A-G) + FreqAI como filtro de régimen

El modelo LightGBM predice el retorno del mercado a 24h. Solo se permiten
entradas cuando el modelo tiene expectativa positiva (mercado en régimen alcista).

Así resolvemos el problema de FreqAI como estrategia independiente:
- Como estrategia sola: 46-49% WR × muchos trades → fees destruyen todo
- Como FILTRO: bloquea entradas en mercados bajistas → menos trades pero mayor WR

Filosofía:
1. MyStrategy (A-G) identifica setups de reversión técnica
2. FreqAI valida que el régimen de mercado sea favorable (expectativa 24h > threshold)
3. Solo cuando AMBOS coinciden se abre posición

Para backtesting (solo pares con historial largo: BTC/ETH/SOL/ADA):
  freqtrade backtesting -c config.json -c config.backtest.freqai.json
    -c config.freqai.json -s MyStrategyHybrid
    --timerange 20240101-20241231 --cache none

NOTA: entrenamiento walk-forward real (train 90d, backtest 30d). Necesita
~3 meses de datos previos al período de backtest.
"""

import numpy as np
import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib
from pandas import DataFrame
from freqtrade.strategy.interface import IStrategy
from freqtrade.strategy import stoploss_from_open, DecimalParameter, IntParameter
from datetime import datetime
from typing import Optional
from freqtrade.persistence import Trade


# ─────────────────────────────────────────────────────────────────────────────
# Constantes (mismas que CombinedBinHAndCluc — mantenidas en sync)
# ─────────────────────────────────────────────────────────────────────────────
FEE_RATE = 0.001
SLIPPAGE_BUFFER = 0.0007
MIN_PROFIT_NET = 7 * FEE_RATE + SLIPPAGE_BUFFER
PEAK_MIN_PROFIT = 0.020
HH_EMA_MIN_PROFIT = 0.025
HARD_TP = 0.50

STOPLOSS_ABS = -0.035
TRAIL_ATR_MULT_LOW = 2.6
TRAIL_ATR_MULT_HIGH = 3.6
TRAIL_DIST_MIN = 0.040
TRAIL_DIST_MAX = 0.120
TRAIL_VERTICAL_MIN = 0.060
ADX_STRONG_TREND = 27
ROC5_VERTICAL = 1.5
FALLBACK_TRAIL_DIST = 0.028

PCT1_MIN = -2.0
PCT3_MIN = -5.0
COOLDOWN_BARS = 8

NO_BUY_BB_MULT = 1.003
NO_BUY_EMA20_MULT = 1.003
NO_BUY_RSI_MIN = 58

DEEP_BB = 0.18
BB_ZONE_OK = 0.55
LOWER_WICK_BODY_RATIO = 1.22

A_LL10_MULT = 1.004
A_RSI_PREV_MAX = 52
C_STOCH_MAX = 25
D_PCT1_MAX = -2.5
D_PCT3_MAX = -5.0
D_BB_PERCENT_MAX = 0.055
D_TAIL_ATR_MULT = 1.15
E_RSI_MIN = 55
E_LL10_MULT = 1.008
E_BB_MID_MULT = 0.996
F_RSI_MAX = 30
G_BB_ZONE = 0.42
G_VOL_MULT = 2.8

REJECT_UPPER_ATR_MULT = 1.05
REJECT_WICK_BODY_RATIO = 1.30
SELL_RSI_PEAK = 74
SELL_RSI_REJECT = 68
SELL_RSI_HH_EMA = 68
SELL_RSI_WICK = 68

CRASH_FAST_DROP_EMA8 = 0.990
CRASH_FAST_DROP_PCT1 = -1.5
CRASH_ATR_BREAK_MULT = 1.55
CRASH_ADX_MIN = 26
CRASH_RSI_MAX = 50

TIMEFRAME = '15m'
TF_MULT = 4
STARTUP_CANDLES = 500

BB40_WINDOW = 180
BB40_STDS = 2.25
BB20_WINDOW = 80
BB20_STDS = 2.25

MAX_PCT_UP_1 = 2.0
MAX_PCT_UP_3 = 5.0
MAX_GREEN_STREAK = 3
BUY_BELOW_EMA20_MULT = 0.998
BUY_BELOW_BB_MID_MULT = 0.998
BB_EXPANDING_HIGH = 0.42
PUMP_VOL_MULT = 1.9
NEAR_HH_DISTANCE = 0.028


def bollinger_bands(stock_price, window_size, num_of_std):
    rolling_mean = stock_price.rolling(window=window_size).mean()
    rolling_std = stock_price.rolling(window=window_size).std()
    lower_band = rolling_mean - (rolling_std * num_of_std)
    return np.nan_to_num(rolling_mean), np.nan_to_num(lower_band)


class MyStrategyHybrid(IStrategy):
    """
    MyStrategy A-G conditions + FreqAI market regime filter.
    Only enters when ML model predicts positive expected return in next 24h.
    """

    INTERFACE_VERSION = 3
    timeframe = TIMEFRAME
    startup_candle_count = STARTUP_CANDLES
    stoploss = STOPLOSS_ABS
    trailing_stop = False
    use_custom_stoploss = False
    minimal_roi = {"0": 10.0}
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = True
    process_only_new_candles = True
    MIN_HOLD_BARS = 3

    FEE_RATE = FEE_RATE
    SLIPPAGE_BUFFER = SLIPPAGE_BUFFER
    MIN_PROFIT_NET = MIN_PROFIT_NET
    PEAK_MIN_PROFIT = PEAK_MIN_PROFIT
    HH_EMA_MIN_PROFIT = HH_EMA_MIN_PROFIT
    HARD_TP = HARD_TP
    PCT1_MIN = PCT1_MIN
    PCT3_MIN = PCT3_MIN
    COOLDOWN_BARS = COOLDOWN_BARS
    NO_BUY_BB_MULT = NO_BUY_BB_MULT
    NO_BUY_EMA20_MULT = NO_BUY_EMA20_MULT
    NO_BUY_RSI_MIN = NO_BUY_RSI_MIN
    DEEP_BB = DEEP_BB
    BB_ZONE_OK = BB_ZONE_OK
    LOWER_WICK_BODY_RATIO = LOWER_WICK_BODY_RATIO
    A_LL10_MULT = A_LL10_MULT
    A_RSI_PREV_MAX = A_RSI_PREV_MAX
    C_STOCH_MAX = C_STOCH_MAX
    D_PCT1_MAX = D_PCT1_MAX
    D_PCT3_MAX = D_PCT3_MAX
    D_BB_PERCENT_MAX = D_BB_PERCENT_MAX
    D_TAIL_ATR_MULT = D_TAIL_ATR_MULT
    E_RSI_MIN = E_RSI_MIN
    E_LL10_MULT = E_LL10_MULT
    E_BB_MID_MULT = E_BB_MID_MULT
    F_RSI_MAX = F_RSI_MAX
    REJECT_UPPER_ATR_MULT = REJECT_UPPER_ATR_MULT
    REJECT_WICK_BODY_RATIO = REJECT_WICK_BODY_RATIO
    SELL_RSI_PEAK = SELL_RSI_PEAK
    SELL_RSI_REJECT = SELL_RSI_REJECT
    SELL_RSI_HH_EMA = SELL_RSI_HH_EMA
    SELL_RSI_WICK = SELL_RSI_WICK
    CRASH_FAST_DROP_EMA8 = CRASH_FAST_DROP_EMA8
    CRASH_FAST_DROP_PCT1 = CRASH_FAST_DROP_PCT1
    CRASH_ATR_BREAK_MULT = CRASH_ATR_BREAK_MULT
    CRASH_ADX_MIN = CRASH_ADX_MIN
    CRASH_RSI_MAX = CRASH_RSI_MAX
    TRAIL_ATR_MULT_LOW = TRAIL_ATR_MULT_LOW
    TRAIL_ATR_MULT_HIGH = TRAIL_ATR_MULT_HIGH
    TRAIL_DIST_MIN = TRAIL_DIST_MIN
    TRAIL_DIST_MAX = TRAIL_DIST_MAX
    TRAIL_VERTICAL_MIN = TRAIL_VERTICAL_MIN
    ADX_STRONG_TREND = ADX_STRONG_TREND
    ROC5_VERTICAL = ROC5_VERTICAL
    FALLBACK_TRAIL_DIST = FALLBACK_TRAIL_DIST
    BB40_WINDOW = BB40_WINDOW
    BB40_STDS = BB40_STDS
    BB20_WINDOW = BB20_WINDOW
    BB20_STDS = BB20_STDS

    # ── Hyperopt: mismos params que CombinedBinHAndCluc ──────────────────────
    buy_c_stoch_max      = IntParameter(12, 40, default=25,    space='buy', optimize=True)
    buy_bb_zone_ok       = DecimalParameter(0.38, 0.85, default=0.55, decimals=2, space='buy', optimize=True)
    buy_a_rsi_prev_max   = IntParameter(38, 65, default=52,    space='buy', optimize=True)
    buy_f_rsi_max        = IntParameter(20, 38, default=30,    space='buy', optimize=True)
    buy_ema50_close_pct  = DecimalParameter(0.860, 0.998, default=0.978, decimals=3, space='buy', optimize=True)
    buy_ema50_slope_48h  = DecimalParameter(0.940, 0.998, default=0.985, decimals=3, space='buy', optimize=True)
    buy_ema20_slope_24h  = DecimalParameter(0.945, 0.998, default=0.990, decimals=3, space='buy', optimize=True)
    buy_g_bb_zone        = DecimalParameter(0.18, 0.42, default=0.30, decimals=2, space='buy', optimize=True)
    buy_g_vol_mult       = DecimalParameter(1.4, 2.8, default=1.8, decimals=1, space='buy', optimize=True)
    sell_peak_min_profit = DecimalParameter(0.008, 0.045, default=0.020, decimals=3, space='sell', optimize=True)
    sell_hh_ema_min      = DecimalParameter(0.008, 0.055, default=0.025, decimals=3, space='sell', optimize=True)

    # ── FreqAI filtro de régimen: umbral de predicción ML ────────────────────
    buy_ml_regime_min    = DecimalParameter(-1.0, 2.0, default=0.5, decimals=1, space='buy', optimize=True)

    # ─────────────────────────────────────────────────────────────────────────
    # FreqAI feature engineering
    # ─────────────────────────────────────────────────────────────────────────

    def feature_engineering_expand_all(
        self, dataframe: DataFrame, period: int, metadata: dict, **kwargs
    ) -> DataFrame:
        dataframe["%-rsi-period"]      = ta.RSI(dataframe, timeperiod=period)
        dataframe["%-adx-period"]      = ta.ADX(dataframe, timeperiod=period)
        dataframe["%-mfi-period"]      = ta.MFI(dataframe, timeperiod=period)
        dataframe["%-roc-period"]      = ta.ROC(dataframe, timeperiod=period)
        dataframe["%-macdhist-period"] = ta.MACD(dataframe)["macdhist"]
        dataframe["%-willr-period"]    = ta.WILLR(dataframe, timeperiod=period)
        dataframe["%-cci-period"]      = ta.CCI(dataframe, timeperiod=period)

        bb = ta.BBANDS(dataframe, timeperiod=period)
        upper = bb["upperband"]
        lower = bb["lowerband"]
        mid   = bb["middleband"]
        dataframe["%-bb_pct-period"]   = (dataframe["close"] - lower) / (upper - lower + 1e-8)
        dataframe["%-bb_width-period"] = (upper - lower) / (mid + 1e-8)
        return dataframe

    def feature_engineering_expand_basic(
        self, dataframe: DataFrame, metadata: dict, **kwargs
    ) -> DataFrame:
        dataframe["%-pct_1"]       = dataframe["close"].pct_change(1)
        dataframe["%-pct_4"]       = dataframe["close"].pct_change(4)
        dataframe["%-pct_16"]      = dataframe["close"].pct_change(16)
        dataframe["%-pct_32"]      = dataframe["close"].pct_change(32)
        dataframe["%-vol_ratio"]   = dataframe["volume"] / (dataframe["volume"].rolling(20).mean() + 1e-8)
        dataframe["%-raw_price"]   = dataframe["close"]
        dataframe["%-raw_volume"]  = dataframe["volume"]
        return dataframe

    def feature_engineering_standard(
        self, dataframe: DataFrame, metadata: dict, **kwargs
    ) -> DataFrame:
        ema200 = ta.EMA(dataframe, timeperiod=200)
        ema80  = ta.EMA(dataframe, timeperiod=80)
        ema50  = ta.EMA(dataframe, timeperiod=50)

        dataframe["%-close_ema200"] = dataframe["close"] / (ema200 + 1e-8)
        dataframe["%-close_ema80"]  = dataframe["close"] / (ema80 + 1e-8)
        dataframe["%-close_ema50"]  = dataframe["close"] / (ema50 + 1e-8)
        dataframe["%-ema50_ema200"] = ema50 / (ema200 + 1e-8)
        dataframe["%-ema200_slope"] = ema200 / (ema200.shift(96) + 1e-8)

        atr = ta.ATR(dataframe, timeperiod=14)
        dataframe["%-atr_ratio"] = atr / (dataframe["close"] + 1e-8)

        stoch = ta.STOCHRSI(dataframe, timeperiod=14, fastk_period=3, fastd_period=3)
        dataframe["%-stoch_k"] = stoch["fastk"]
        dataframe["%-stoch_d"] = stoch["fastd"]

        # TARGET: % cambio en 96 velas (24h a 15m)
        dataframe["&-s_target"] = (
            dataframe["close"].shift(-96) / dataframe["close"] - 1
        ) * 100

        return dataframe

    # ─────────────────────────────────────────────────────────────────────────
    # Indicadores (mismos que CombinedBinHAndCluc + llamada a FreqAI)
    # ─────────────────────────────────────────────────────────────────────────
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        m = TF_MULT

        mid, lower = bollinger_bands(
            dataframe['close'], window_size=self.BB40_WINDOW, num_of_std=self.BB40_STDS
        )
        dataframe['lower'] = lower
        dataframe['bbdelta'] = (mid - dataframe['lower']).abs()
        dataframe['closedelta'] = (dataframe['close'] - dataframe['close'].shift()).abs()
        dataframe['tail'] = (dataframe['close'] - dataframe['low']).abs()

        tp = qtpylib.typical_price(dataframe)
        bb = qtpylib.bollinger_bands(tp, window=self.BB20_WINDOW, stds=self.BB20_STDS)
        dataframe['bb_lowerband']  = bb['lower']
        dataframe['bb_middleband'] = bb['mid']
        dataframe['bb_upperband']  = bb['upper']
        dataframe['bb_width'] = (dataframe['bb_upperband'] - dataframe['bb_lowerband']) / dataframe['bb_middleband']
        denom = (dataframe['bb_upperband'] - dataframe['bb_lowerband']).replace(0, np.nan)
        dataframe['bb_percent'] = (dataframe['close'] - dataframe['bb_lowerband']) / denom
        dataframe['bb_expanding'] = (dataframe['bb_width'] > dataframe['bb_width'].shift(1))

        dataframe['ema8']     = ta.EMA(dataframe, timeperiod=8 * m)
        dataframe['ema_fast'] = ta.EMA(dataframe, timeperiod=20 * m)
        dataframe['ema_slow'] = ta.EMA(dataframe, timeperiod=50 * m)
        dataframe['ema50_ht'] = dataframe['ema_slow']
        dataframe['ema20_ht'] = dataframe['ema_fast']
        dataframe['volume_mean_slow'] = dataframe['volume'].rolling(window=30 * m).mean()
        dataframe['ema8_slope_up'] = dataframe['ema8'] > dataframe['ema8'].shift(1)

        dataframe['rsi']      = ta.RSI(dataframe, timeperiod=14)
        dataframe['rsi_prev'] = dataframe['rsi'].shift(1)
        dataframe['adx']      = ta.ADX(dataframe, timeperiod=14 * m)
        dataframe['plus_di']  = ta.PLUS_DI(dataframe, timeperiod=14 * m)
        dataframe['minus_di'] = ta.MINUS_DI(dataframe, timeperiod=14 * m)

        stoch = ta.STOCHRSI(dataframe, timeperiod=14, fastk_period=3, fastd_period=3)
        dataframe['stoch_k'] = stoch['fastk']
        dataframe['stoch_d'] = stoch['fastd']
        dataframe['stoch_k_prev'] = dataframe['stoch_k'].shift(1)
        dataframe['stoch_d_prev'] = dataframe['stoch_d'].shift(1)

        macd = ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)
        dataframe['macd']       = macd['macd']
        dataframe['macdsignal'] = macd['macdsignal']
        dataframe['macdhist']   = macd['macdhist']

        dataframe['roc5'] = ta.ROC(dataframe, timeperiod=5 * m)
        dataframe['ll_8']  = dataframe['low'].rolling(8 * m).min()
        dataframe['ll_10'] = dataframe['low'].rolling(10 * m).min()
        dataframe['ll_20'] = dataframe['low'].rolling(20 * m).min()
        dataframe['hh_20'] = dataframe['high'].rolling(20 * m).max()

        dataframe['atr']   = ta.ATR(dataframe, timeperiod=14 * m)
        dataframe['pct_1'] = dataframe['close'].pct_change(1) * 100.0
        dataframe['pct_3'] = dataframe['close'].pct_change(3) * 100.0

        body = (dataframe['close'] - dataframe['open']).abs()
        dataframe['big_red']  = (dataframe['close'] < dataframe['open']) & (body > 1.2 * dataframe['atr'])
        dataframe['cooldown'] = dataframe['big_red'].rolling(self.COOLDOWN_BARS).max()

        dataframe['upper_wick'] = (dataframe['high'] - np.maximum(dataframe['open'], dataframe['close'])).abs()
        dataframe['lower_wick'] = (np.minimum(dataframe['open'], dataframe['close']) - dataframe['low']).abs()
        dataframe['vol_spike'] = dataframe['volume'] > (dataframe['volume_mean_slow'] * 1.15)

        dataframe['loc_peak'] = (
            (dataframe['high'] >= dataframe['high'].rolling(6 * m).max()) &
            (dataframe['high'] >= dataframe['high'].shift(1)) &
            (dataframe['high'] >= dataframe['high'].shift(2))
        )
        dataframe['loc_trough'] = (
            (dataframe['low'] <= dataframe['low'].rolling(6 * m).min()) &
            (dataframe['low'] <= dataframe['low'].shift(1)) &
            (dataframe['low'] <= dataframe['low'].shift(2))
        )

        dataframe['green'] = dataframe['close'] > dataframe['open']
        dataframe['green_streak'] = dataframe['green'].rolling(window=MAX_GREEN_STREAK, min_periods=1).sum()
        dataframe['vol_mean_fast'] = dataframe['volume'].rolling(window=10 * m).mean()
        dataframe['pump_vol'] = dataframe['volume'] > (dataframe['vol_mean_fast'] * PUMP_VOL_MULT)
        dataframe['near_hh'] = dataframe['close'] >= (dataframe['hh_20'] * (1.0 - NEAR_HH_DISTANCE))

        # FreqAI: añade columna "&-s_target" (predicción del modelo) y "do_predict"
        dataframe = self.freqai.start(dataframe, metadata, self)

        return dataframe

    # ─────────────────────────────────────────────────────────────────────────
    # Entradas (A-G idénticas a CombinedBinHAndCluc + filtro ML)
    # ─────────────────────────────────────────────────────────────────────────
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        anti_cuchillo = (
            (dataframe['pct_1'] > self.PCT1_MIN) &
            (dataframe['pct_3'] > self.PCT3_MIN) &
            (~dataframe['cooldown'].astype(bool)) &
            (~((dataframe['bb_percent'] < 0) & dataframe['bb_expanding'])) &
            (dataframe['minus_di'] <= dataframe['plus_di']) &
            (dataframe['volume'] > 0)
        )

        no_buy_high = (
            (dataframe['close'] > dataframe['bb_middleband'] * self.NO_BUY_BB_MULT) &
            (dataframe['close'] > dataframe['ema_fast'] * self.NO_BUY_EMA20_MULT) &
            (dataframe['rsi'] > self.NO_BUY_RSI_MIN)
        )

        bb_zone_ok = (dataframe['bb_percent'] <= self.buy_bb_zone_ok.value)
        lower_wick = dataframe['lower_wick']
        body       = (dataframe['close'] - dataframe['open']).abs()
        hammerish  = lower_wick > self.LOWER_WICK_BODY_RATIO * body

        anti_chase = (
            (dataframe['pct_1'] < MAX_PCT_UP_1) &
            (dataframe['pct_3'] < MAX_PCT_UP_3) &
            (dataframe['green_streak'] < MAX_GREEN_STREAK) &
            (~((dataframe['bb_percent'] >= BB_EXPANDING_HIGH) & (dataframe['bb_expanding']))) &
            (~(dataframe['pump_vol'] & (dataframe['pct_1'] > 0.6))) &
            (dataframe['close'] <= dataframe['ema_fast'] * BUY_BELOW_EMA20_MULT) &
            (dataframe['close'] <= dataframe['bb_middleband'] * BUY_BELOW_BB_MID_MULT) &
            (~dataframe['near_hh'])
        )

        base_filter = anti_cuchillo & ~no_buy_high & anti_chase

        A = (
            (dataframe['loc_trough']) &
            (dataframe['low'] <= dataframe['ll_10'] * self.A_LL10_MULT) &
            (dataframe['bb_percent'] <= 0.20) &
            (dataframe['rsi_prev'] < self.buy_a_rsi_prev_max.value) &
            (dataframe['rsi'] > dataframe['rsi_prev']) &
            (dataframe['close'] >= dataframe['open']) &
            dataframe['vol_spike'] &
            (dataframe['macdhist'] >= dataframe['macdhist'].shift(1)) &
            (dataframe['macdhist'] > 0)
        )
        B = (
            (dataframe['close'].shift(2) < dataframe['bb_lowerband'].shift(2)) &
            (dataframe['close'].shift(1) < dataframe['bb_lowerband'].shift(1)) &
            (dataframe['close'] > dataframe['bb_lowerband']) &
            (dataframe['rsi'] > dataframe['rsi_prev']) &
            (dataframe['macdhist'] >= dataframe['macdhist'].shift(1)) &
            (bb_zone_ok)
        )
        C = (
            (dataframe['stoch_k_prev'] < dataframe['stoch_d_prev']) &
            (dataframe['stoch_k'] > dataframe['stoch_d']) &
            (dataframe['stoch_k'] < self.buy_c_stoch_max.value) &
            (dataframe['stoch_d'] < self.buy_c_stoch_max.value) &
            (dataframe['macdhist'] >= dataframe['macdhist'].shift(1)) &
            (dataframe['ema_fast'] >= dataframe['ema_fast'].shift(16)) &
            (bb_zone_ok)
        )
        D = (
            ((dataframe['pct_1'] <= self.D_PCT1_MAX) | (dataframe['pct_3'] <= self.D_PCT3_MAX)) &
            (dataframe['bb_percent'] <= self.D_BB_PERCENT_MAX) &
            (dataframe['tail'] >= dataframe['atr'] * self.D_TAIL_ATR_MULT) &
            (dataframe['close'] >= dataframe['open'])
        )
        E = (
            (dataframe['close'] > dataframe['ema8']) &
            (dataframe['close'].shift(1) <= dataframe['ema8'].shift(1)) &
            (dataframe['ema8_slope_up']) &
            (dataframe['rsi'] >= self.E_RSI_MIN) & (dataframe['rsi'] > dataframe['rsi_prev']) &
            ((dataframe['low'] <= dataframe['ll_10'] * self.E_LL10_MULT) |
             (dataframe['close'] <= dataframe['bb_middleband'] * self.E_BB_MID_MULT) |
             bb_zone_ok) &
            (dataframe['vol_spike'] | hammerish)
        )
        F = (
            (dataframe['rsi'] < self.buy_f_rsi_max.value) &
            (dataframe['rsi'] > dataframe['rsi_prev']) &
            (dataframe['macdhist'] >= dataframe['macdhist'].shift(1)) &
            dataframe['vol_spike'] &
            (bb_zone_ok)
        )
        G = (
            hammerish &
            (dataframe['bb_percent'] <= self.buy_g_bb_zone.value) &
            (dataframe['volume'] > dataframe['vol_mean_fast'] * self.buy_g_vol_mult.value) &
            (dataframe['rsi'] > dataframe['rsi_prev']) &
            (dataframe['macdhist'] >= dataframe['macdhist'].shift(1)) &
            (dataframe['close'] >= dataframe['open']) &
            (dataframe['adx'] < 30) &
            (dataframe['minus_di'] <= dataframe['plus_di'])
        )

        ema50_ok = (
            (dataframe['ema50_ht'] >= dataframe['ema50_ht'].shift(192) * self.buy_ema50_slope_48h.value) &
            (dataframe['ema20_ht'] >= dataframe['ema20_ht'].shift(96)  * self.buy_ema20_slope_24h.value) &
            (dataframe['close']    >= dataframe['ema50_ht']            * self.buy_ema50_close_pct.value)
        )

        # ─ FILTRO CLAVE: régimen de mercado ML ────────────────────────────────
        # Solo entrar cuando el modelo predice retorno positivo a 24h
        # Y la predicción es confiable (do_predict == 1)
        ml_regime_ok = (
            (dataframe["&-s_target"] > self.buy_ml_regime_min.value) &
            (dataframe["do_predict"] == 1)
        )

        anti_cuchillo_D = (
            (~dataframe['cooldown'].astype(bool)) &
            (dataframe['volume'] > 0)
        )
        base_filter_D     = anti_cuchillo_D & ~no_buy_high & ema50_ok & ml_regime_ok
        base_filter_trend = base_filter & ema50_ok & ml_regime_ok

        mask_A = A & base_filter_trend
        mask_B = B & base_filter_trend & ~mask_A
        mask_C = C & base_filter_trend & ~mask_A & ~mask_B
        mask_D = D & base_filter_D & ~mask_A & ~mask_B & ~mask_C
        mask_E = E & base_filter_trend & ~mask_A & ~mask_B & ~mask_C & ~mask_D
        mask_F = F & base_filter_trend & ~mask_A & ~mask_B & ~mask_C & ~mask_D & ~mask_E
        mask_G = G & base_filter_trend & ~mask_A & ~mask_B & ~mask_C & ~mask_D & ~mask_E & ~mask_F

        dataframe.loc[mask_A, ['enter_long', 'enter_tag']] = [1, 'A_local_min']
        dataframe.loc[mask_B, ['enter_long', 'enter_tag']] = [1, 'B_bb_reentry']
        dataframe.loc[mask_C, ['enter_long', 'enter_tag']] = [1, 'C_stochrsi']
        dataframe.loc[mask_D, ['enter_long', 'enter_tag']] = [1, 'D_capitulation']
        dataframe.loc[mask_E, ['enter_long', 'enter_tag']] = [1, 'E_ema8_pullback']
        dataframe.loc[mask_F, ['enter_long', 'enter_tag']] = [1, 'F_rsi_extreme']
        dataframe.loc[mask_G, ['enter_long', 'enter_tag']] = [1, 'G_hammer']

        return dataframe

    # ─────────────────────────────────────────────────────────────────────────
    # Salidas (idénticas a CombinedBinHAndCluc)
    # ─────────────────────────────────────────────────────────────────────────
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        reject_upper = (
            (dataframe['upper_wick'] >= dataframe['atr'] * self.REJECT_UPPER_ATR_MULT) &
            (dataframe['upper_wick'] > (dataframe['close'] - dataframe['open']).abs() * self.REJECT_WICK_BODY_RATIO) &
            ((dataframe['high'] >= dataframe['bb_upperband'] * 0.999) | (dataframe['close'] >= dataframe['bb_upperband'])) &
            (dataframe['rsi'] >= self.SELL_RSI_REJECT)
        )
        dataframe.loc[
            (
                (dataframe['loc_peak']) &
                (dataframe['close'] >= dataframe['bb_upperband'] * 0.999) &
                (dataframe['rsi'] >= self.SELL_RSI_PEAK) &
                (
                    (dataframe['macdhist'] < dataframe['macdhist'].shift(1)) |
                    (dataframe['close'] < dataframe['ema8']) |
                    (dataframe['close'] < dataframe['open'])
                )
            )
            |
            (
                (dataframe['high'].shift(1) >= dataframe['hh_20'].shift(1)) &
                (dataframe['close'].shift(1) >= dataframe['ema8'].shift(1)) &
                (dataframe['close'] < dataframe['ema8']) &
                (dataframe['rsi'] >= self.SELL_RSI_HH_EMA) &
                (dataframe['macdhist'] < dataframe['macdhist'].shift(1))
            )
            | reject_upper,
            'exit_long'
        ] = 1
        return dataframe

    def _bars_elapsed(self, trade: Trade, current_time: datetime) -> int:
        tf = self.timeframe
        if tf.endswith('h'):
            tf_minutes = int(tf[:-1]) * 60
        elif tf.endswith('m'):
            tf_minutes = int(tf[:-1])
        else:
            tf_minutes = int(tf)
        return int(max(0, (current_time - trade.open_date_utc).total_seconds()) // (tf_minutes * 60))

    def _strong_bearish_reversal(self, pair: str) -> bool:
        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last = df.iloc[-1]
            return (last['minus_di'] > last['plus_di']) and (last['adx'] > 23) and (last['rsi'] < 55)
        except Exception:
            return False

    def _crash_incoming(self, pair: str) -> bool:
        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last = df.iloc[-1]
            prev = df.iloc[-2]
            fast_drop  = (last['close'] <= last['ema8'] * self.CRASH_FAST_DROP_EMA8) and (last['pct_1'] <= self.CRASH_FAST_DROP_PCT1)
            atr_break  = (last['low'] < last['ema_fast'] - self.CRASH_ATR_BREAK_MULT * last['atr'])
            bb_flush   = (last['bb_percent'] < 0) and bool(last['bb_expanding']) and (last['macdhist'] < prev['macdhist'])
            di_shift   = (last['adx'] > self.CRASH_ADX_MIN) and (last['minus_di'] > last['plus_di']) and (last['rsi'] < self.CRASH_RSI_MAX)
            return sum([fast_drop, atr_break, bb_flush or di_shift]) >= 2
        except Exception:
            return False

    def custom_exit(
        self, pair: str, trade: Trade, current_time: datetime,
        current_rate: float, current_profit: float, **kwargs
    ) -> Optional[str]:
        if self._crash_incoming(pair):
            if (current_profit is None) or (current_profit > self.MIN_PROFIT_NET):
                return "crash_guard"

        bars = self._bars_elapsed(trade, current_time)
        if bars < self.MIN_HOLD_BARS:
            if not self._strong_bearish_reversal(pair):
                return None

        if current_profit is not None and current_profit >= self.HARD_TP:
            return "hard_tp"

        if current_profit is None or current_profit < self.MIN_PROFIT_NET:
            return None

        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last = df.iloc[-1]
            prev = df.iloc[-2]
            near_upper = (last['close'] >= last['bb_upperband'] * 0.999) or (last['high'] >= last['bb_upperband'])
            loc_peak   = bool(last['high'] >= df['high'].rolling(6).max().iloc[-1])
            rsi_high   = (last['rsi'] >= self.SELL_RSI_PEAK)
            bear_candle = (last['close'] < last['open'])
            macd_fade   = (last['macdhist'] < prev['macdhist'])
            ema_break   = (last['close'] < last['ema8'])

            if current_profit >= self.sell_peak_min_profit.value and near_upper and loc_peak and rsi_high and (
                bear_candle or macd_fade or ema_break
            ):
                return "peak_exit_top_optimal"

            if current_profit >= self.sell_hh_ema_min.value and (prev['high'] >= df['high'].rolling(20).max().iloc[-2]) and ema_break and macd_fade and (last['rsi'] >= self.SELL_RSI_HH_EMA):
                return "hh_ema8_break_exit"

            upper_wick = float(last['high'] - max(last['open'], last['close']))
            body_size  = float(abs(last['close'] - last['open']))
            if current_profit >= self.MIN_PROFIT_NET and near_upper and (upper_wick >= last['atr'] * self.REJECT_UPPER_ATR_MULT) and (upper_wick > self.REJECT_WICK_BODY_RATIO * body_size) and (last['rsi'] >= self.SELL_RSI_WICK):
                return "upper_wick_reject_exit"

            if current_profit >= (self.MIN_PROFIT_NET + 0.002) and bars >= 6:
                if (last['rsi'] < last['rsi_prev']) and macd_fade and ema_break:
                    return "momentum_fade_exit"

        except Exception:
            pass
        return None

    def custom_stoploss(
        self, pair: str, trade: Trade, current_time: datetime,
        current_rate: float, current_profit: float, **kwargs
    ) -> float:
        if current_profit is None or current_profit < 0.03:
            return stoploss_from_open(current_profit if current_profit else 0.0, abs(self.stoploss))
        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last = df.iloc[-1]
            atr  = float(last['atr'])
            adx  = float(last['adx'])
            roc5 = float(last['roc5'])
        except Exception:
            return stoploss_from_open(current_profit, self.FALLBACK_TRAIL_DIST)

        strong_trend  = (adx >= self.ADX_STRONG_TREND and roc5 > 0)
        vertical_rally = (roc5 >= self.ROC5_VERTICAL)
        k    = self.TRAIL_ATR_MULT_HIGH if current_profit > 0.06 else self.TRAIL_ATR_MULT_LOW
        dist = (k * atr) / max(current_rate, 1e-9)
        dist = min(self.TRAIL_DIST_MAX, max(self.TRAIL_DIST_MIN, dist))

        if vertical_rally:
            dist = max(dist, self.TRAIL_VERTICAL_MIN)
        elif not strong_trend:
            dist = min(dist, 0.02)

        if 0.03 <= current_profit < 0.06:
            return stoploss_from_open(current_profit, max(0.018, dist))
        return stoploss_from_open(current_profit, dist)
