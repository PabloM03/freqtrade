import freqtrade.vendor.qtpylib.indicators as qtpylib
import numpy as np
import talib.abstract as ta
from freqtrade.strategy.interface import IStrategy
from freqtrade.strategy import stoploss_from_open, DecimalParameter, IntParameter
from pandas import DataFrame
from datetime import datetime
from typing import Optional
from freqtrade.persistence import Trade


def bollinger_bands(stock_price, window_size, num_of_std):
    rolling_mean = stock_price.rolling(window=window_size).mean()
    rolling_std = stock_price.rolling(window=window_size).std()
    lower_band = rolling_mean - (rolling_std * num_of_std)
    return np.nan_to_num(rolling_mean), np.nan_to_num(lower_band)


class claudeStrategy(IStrategy):
    """
    Derivada de CombinedBinHAndCluc con:
    - Corrección de use_custom_stoploss = True (bug en original)
    - API moderna (populate_entry_trend / populate_exit_trend)
    - Espacios hyperopt para todos los parámetros clave
    """

    # ── Hiperparámetros de ENTRADA (buy space) ──────────────────────────────
    # Costes / profit mínimo
    peak_min_profit   = DecimalParameter(0.008, 0.030, default=0.015, decimals=3, space='buy', optimize=True)
    hh_ema_min_profit = DecimalParameter(0.010, 0.035, default=0.018, decimals=3, space='buy', optimize=True)
    hard_tp           = DecimalParameter(0.030, 0.090, default=0.055, decimals=3, space='buy', optimize=True)

    # Anti-cuchillo
    pct1_min    = DecimalParameter(-4.0, -1.0, default=-2.4, decimals=1, space='buy', optimize=True)
    pct3_min    = DecimalParameter(-8.0, -3.0, default=-5.5, decimals=1, space='buy', optimize=True)
    cooldown_bars = IntParameter(1, 5, default=3, space='buy', optimize=True)

    # Filtro "no comprar arriba"
    no_buy_rsi_min = IntParameter(50, 68, default=58, space='buy', optimize=True)

    # Zonas de valor
    deep_bb       = DecimalParameter(0.08, 0.30, default=0.18, decimals=2, space='buy', optimize=True)
    bb_zone_ok    = DecimalParameter(0.20, 0.50, default=0.34, decimals=2, space='buy', optimize=True)
    lower_wick_ratio = DecimalParameter(0.80, 1.80, default=1.22, decimals=2, space='buy', optimize=True)

    # Condición A
    a_ll10_mult   = DecimalParameter(1.000, 1.010, default=1.004, decimals=3, space='buy', optimize=True)
    a_rsi_prev_max = IntParameter(35, 55, default=48, space='buy', optimize=True)

    # Condición C
    c_stoch_max   = IntParameter(15, 40, default=26, space='buy', optimize=True)

    # Condición D
    d_pct1_max    = DecimalParameter(-5.0, -1.5, default=-2.9, decimals=1, space='buy', optimize=True)
    d_pct3_max    = DecimalParameter(-10.0, -4.0, default=-6.5, decimals=1, space='buy', optimize=True)
    d_bb_pct_max  = DecimalParameter(0.02, 0.15, default=0.055, decimals=3, space='buy', optimize=True)
    d_tail_atr    = DecimalParameter(0.70, 1.80, default=1.15, decimals=2, space='buy', optimize=True)

    # Condición E
    e_rsi_min     = IntParameter(45, 68, default=55, space='buy', optimize=True)
    e_ll10_mult   = DecimalParameter(1.000, 1.020, default=1.008, decimals=3, space='buy', optimize=True)
    e_bb_mid_mult = DecimalParameter(0.980, 1.005, default=0.996, decimals=3, space='buy', optimize=True)

    # Condición F
    f_bb_pct_max  = DecimalParameter(0.10, 0.45, default=0.28, decimals=2, space='buy', optimize=True)
    f_ll10_upper  = DecimalParameter(1.000, 1.015, default=1.006, decimals=3, space='buy', optimize=True)
    f_ll10_lower  = DecimalParameter(0.975, 1.000, default=0.990, decimals=3, space='buy', optimize=True)

    # ── Hiperparámetros de SALIDA (sell space) ───────────────────────────────
    sell_rsi_peak   = IntParameter(60, 82, default=74, space='sell', optimize=True)
    sell_rsi_reject = IntParameter(55, 78, default=68, space='sell', optimize=True)
    sell_rsi_hh_ema = IntParameter(55, 78, default=68, space='sell', optimize=True)
    sell_rsi_wick   = IntParameter(55, 78, default=68, space='sell', optimize=True)
    reject_atr_mult = DecimalParameter(0.60, 1.80, default=1.05, decimals=2, space='sell', optimize=True)
    reject_wick_ratio = DecimalParameter(0.80, 2.00, default=1.30, decimals=2, space='sell', optimize=True)

    # ── Hiperparámetros de STOPLOSS / TRAILING ────────────────────────────────
    stoploss = -0.05

    trail_atr_low  = DecimalParameter(1.5, 4.0, default=2.6, decimals=1, space='stoploss', optimize=True)
    trail_atr_high = DecimalParameter(2.0, 5.5, default=3.6, decimals=1, space='stoploss', optimize=True)
    trail_dist_min = DecimalParameter(0.010, 0.040, default=0.022, decimals=3, space='stoploss', optimize=True)
    trail_dist_max = DecimalParameter(0.040, 0.120, default=0.070, decimals=3, space='stoploss', optimize=True)
    trail_vertical_min = DecimalParameter(0.015, 0.060, default=0.030, decimals=3, space='stoploss', optimize=True)
    fallback_trail = DecimalParameter(0.015, 0.050, default=0.028, decimals=3, space='stoploss', optimize=True)
    adx_strong     = IntParameter(18, 40, default=27, space='stoploss', optimize=True)
    roc5_vertical  = DecimalParameter(1.0, 6.0, default=3.0, decimals=1, space='stoploss', optimize=True)

    # ── Crash guard ──────────────────────────────────────────────────────────
    crash_ema_mult  = DecimalParameter(0.975, 0.998, default=0.990, decimals=3, space='sell', optimize=True)
    crash_pct1      = DecimalParameter(-2.0, -0.3, default=-0.8, decimals=1, space='sell', optimize=True)
    crash_atr_mult  = DecimalParameter(1.0, 2.5, default=1.55, decimals=2, space='sell', optimize=True)
    crash_adx_min   = IntParameter(15, 40, default=26, space='sell', optimize=True)
    crash_rsi_max   = IntParameter(35, 65, default=50, space='sell', optimize=True)

    # ── Configuración fija ────────────────────────────────────────────────────
    FEE_RATE        = 0.001
    SLIPPAGE_BUFFER = 0.0007
    MIN_PROFIT_NET  = 7 * 0.001 + 0.0007   # 0.0077

    timeframe              = '5m'
    startup_candle_count   = 160
    minimal_roi            = {"0": 10.0}
    trailing_stop          = False
    use_custom_stoploss    = True   # ← corregido (en original estaba False)
    use_exit_signal        = False
    exit_profit_only       = True
    ignore_roi_if_entry_signal = True
    MIN_HOLD_BARS          = 3

    BB40_WINDOW = 45
    BB40_STDS   = 2.25
    BB20_WINDOW = 20
    BB20_STDS   = 2.25

    MAX_PCT_UP_1       = 0.45
    MAX_PCT_UP_3       = 1.25
    MAX_GREEN_STREAK   = 3
    BUY_BELOW_EMA20    = 0.998
    BUY_BELOW_BB_MID   = 0.998
    BB_EXPANDING_HIGH  = 0.42
    PUMP_VOL_MULT      = 1.9
    NEAR_HH_DISTANCE   = 0.028
    REQUIRE_RED_PULLBACK = True
    NO_BUY_BB_MULT     = 1.003
    NO_BUY_EMA20_MULT  = 1.003

    # ────────────────────────────────────────────────────────────────────────
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        mid, lower = bollinger_bands(
            dataframe['close'], window_size=self.BB40_WINDOW, num_of_std=self.BB40_STDS
        )
        dataframe['lower']     = lower
        dataframe['bbdelta']   = (mid - dataframe['lower']).abs()
        dataframe['closedelta']= (dataframe['close'] - dataframe['close'].shift()).abs()
        dataframe['tail']      = (dataframe['close'] - dataframe['low']).abs()

        tp = qtpylib.typical_price(dataframe)
        bb = qtpylib.bollinger_bands(tp, window=self.BB20_WINDOW, stds=self.BB20_STDS)
        dataframe['bb_lowerband']  = bb['lower']
        dataframe['bb_middleband'] = bb['mid']
        dataframe['bb_upperband']  = bb['upper']
        dataframe['bb_width']      = (dataframe['bb_upperband'] - dataframe['bb_lowerband']) / dataframe['bb_middleband']
        denom = (dataframe['bb_upperband'] - dataframe['bb_lowerband']).replace(0, np.nan)
        dataframe['bb_percent']    = (dataframe['close'] - dataframe['bb_lowerband']) / denom
        dataframe['bb_expanding']  = (dataframe['bb_width'] > dataframe['bb_width'].shift(1))

        dataframe['ema8']           = ta.EMA(dataframe, timeperiod=8)
        dataframe['ema_fast']       = ta.EMA(dataframe, timeperiod=20)
        dataframe['ema_slow']       = ta.EMA(dataframe, timeperiod=50)
        dataframe['volume_mean_slow'] = dataframe['volume'].rolling(window=30).mean()
        dataframe['ema8_slope_up']  = dataframe['ema8'] > dataframe['ema8'].shift(1)

        dataframe['rsi']      = ta.RSI(dataframe, timeperiod=14)
        dataframe['rsi_prev'] = dataframe['rsi'].shift(1)
        dataframe['adx']      = ta.ADX(dataframe, timeperiod=14)
        dataframe['plus_di']  = ta.PLUS_DI(dataframe, timeperiod=14)
        dataframe['minus_di'] = ta.MINUS_DI(dataframe, timeperiod=14)

        stoch = ta.STOCHRSI(dataframe, timeperiod=14, fastk_period=3, fastd_period=3)
        dataframe['stoch_k']      = stoch['fastk']
        dataframe['stoch_d']      = stoch['fastd']
        dataframe['stoch_k_prev'] = dataframe['stoch_k'].shift(1)
        dataframe['stoch_d_prev'] = dataframe['stoch_d'].shift(1)

        macd = ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)
        dataframe['macd']      = macd['macd']
        dataframe['macdsignal']= macd['macdsignal']
        dataframe['macdhist']  = macd['macdhist']

        dataframe['roc5']  = ta.ROC(dataframe, timeperiod=5)
        dataframe['ll_8']  = dataframe['low'].rolling(8).min()
        dataframe['ll_10'] = dataframe['low'].rolling(10).min()
        dataframe['ll_20'] = dataframe['low'].rolling(20).min()
        dataframe['hh_20'] = dataframe['high'].rolling(20).max()

        dataframe['atr']   = ta.ATR(dataframe, timeperiod=14)
        dataframe['pct_1'] = dataframe['close'].pct_change(1) * 100.0
        dataframe['pct_3'] = dataframe['close'].pct_change(3) * 100.0

        body = (dataframe['close'] - dataframe['open']).abs()
        dataframe['big_red']  = (dataframe['close'] < dataframe['open']) & (body > 1.2 * dataframe['atr'])
        dataframe['cooldown'] = dataframe['big_red'].rolling(self.cooldown_bars.value).max()

        dataframe['upper_wick'] = (dataframe['high'] - np.maximum(dataframe['open'], dataframe['close'])).abs()
        dataframe['lower_wick'] = (np.minimum(dataframe['open'], dataframe['close']) - dataframe['low']).abs()
        dataframe['vol_spike']  = dataframe['volume'] > (dataframe['volume_mean_slow'] * 1.15)

        dataframe['loc_peak'] = (
            (dataframe['high'] >= dataframe['high'].rolling(6).max()) &
            (dataframe['high'] >= dataframe['high'].shift(1)) &
            (dataframe['high'] >= dataframe['high'].shift(2))
        )
        dataframe['loc_trough'] = (
            (dataframe['low'] <= dataframe['low'].rolling(6).min()) &
            (dataframe['low'] <= dataframe['low'].shift(1)) &
            (dataframe['low'] <= dataframe['low'].shift(2))
        )

        dataframe['green'] = dataframe['close'] > dataframe['open']
        dataframe['green_streak'] = (
            dataframe['green'].rolling(window=self.MAX_GREEN_STREAK, min_periods=1).sum()
        )
        dataframe['vol_mean_fast'] = dataframe['volume'].rolling(window=10).mean()
        dataframe['pump_vol']      = dataframe['volume'] > (dataframe['vol_mean_fast'] * self.PUMP_VOL_MULT)
        dataframe['near_hh']       = dataframe['close'] >= (dataframe['hh_20'] * (1.0 - self.NEAR_HH_DISTANCE))

        return dataframe

    # ── ENTRADAS ─────────────────────────────────────────────────────────────
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        anti_cuchillo = (
            (dataframe['pct_1'] > self.pct1_min.value) &
            (dataframe['pct_3'] > self.pct3_min.value) &
            (~dataframe['cooldown'].astype(bool)) &
            (~((dataframe['bb_percent'] < 0) & dataframe['bb_expanding'])) &
            (dataframe['minus_di'] <= dataframe['plus_di']) &
            (dataframe['volume'] > 0)
        )

        no_buy_high = (
            (dataframe['close'] > dataframe['bb_middleband'] * self.NO_BUY_BB_MULT) &
            (dataframe['close'] > dataframe['ema_fast'] * self.NO_BUY_EMA20_MULT) &
            (dataframe['rsi'] > self.no_buy_rsi_min.value)
        )

        deep_bb    = (dataframe['bb_percent'] <= self.deep_bb.value)
        bb_zone_ok = (dataframe['bb_percent'] <= self.bb_zone_ok.value)

        lower_wick = dataframe['lower_wick']
        body       = (dataframe['close'] - dataframe['open']).abs()
        hammerish  = lower_wick > self.lower_wick_ratio.value * body

        anti_chase = (
            (dataframe['pct_1'] < self.MAX_PCT_UP_1) &
            (dataframe['pct_3'] < self.MAX_PCT_UP_3) &
            (dataframe['green_streak'] < self.MAX_GREEN_STREAK) &
            (~((dataframe['bb_percent'] >= self.BB_EXPANDING_HIGH) & (dataframe['bb_expanding']))) &
            (~(dataframe['pump_vol'] & (dataframe['pct_1'] > 0.6))) &
            (dataframe['close'] <= dataframe['ema_fast'] * self.BUY_BELOW_EMA20) &
            (dataframe['close'] <= dataframe['bb_middleband'] * self.BUY_BELOW_BB_MID) &
            (~dataframe['near_hh'])
        )

        if self.REQUIRE_RED_PULLBACK:
            anti_chase = anti_chase & (
                (dataframe['close'] <= dataframe['open']) |
                (dataframe['low'] < dataframe['close'].shift(1))
            )

        A = (
            (dataframe['loc_trough']) &
            ((dataframe['low'] <= dataframe['ll_10'] * self.a_ll10_mult.value) | deep_bb) &
            (dataframe['rsi_prev'] < self.a_rsi_prev_max.value) &
            (dataframe['rsi'] > dataframe['rsi_prev']) &
            (dataframe['close'] >= dataframe['open']) &
            (hammerish | dataframe['vol_spike'])
        )

        B = (
            (dataframe['close'].shift(1) < dataframe['bb_lowerband'].shift(1)) &
            (dataframe['close'] > dataframe['bb_lowerband']) &
            (dataframe['rsi'] > dataframe['rsi_prev']) &
            (bb_zone_ok)
        )

        C = (
            (dataframe['stoch_k_prev'] < dataframe['stoch_d_prev']) &
            (dataframe['stoch_k'] > dataframe['stoch_d']) &
            (dataframe['stoch_k'] < self.c_stoch_max.value) &
            (dataframe['stoch_d'] < self.c_stoch_max.value) &
            (dataframe['macdhist'] >= dataframe['macdhist'].shift(1)) &
            (bb_zone_ok)
        )

        D = (
            ((dataframe['pct_1'] <= self.d_pct1_max.value) | (dataframe['pct_3'] <= self.d_pct3_max.value)) &
            (dataframe['bb_percent'] <= self.d_bb_pct_max.value) &
            (dataframe['tail'] >= dataframe['atr'] * self.d_tail_atr.value) &
            (dataframe['close'] >= dataframe['open'])
        )

        E = (
            (dataframe['close'] > dataframe['ema8']) &
            (dataframe['close'].shift(1) <= dataframe['ema8'].shift(1)) &
            (dataframe['ema8_slope_up']) &
            (dataframe['rsi'] >= self.e_rsi_min.value) &
            (dataframe['rsi'] > dataframe['rsi_prev']) &
            ((dataframe['low'] <= dataframe['ll_10'] * self.e_ll10_mult.value) |
             (dataframe['close'] <= dataframe['bb_middleband'] * self.e_bb_mid_mult.value) |
             bb_zone_ok) &
            (dataframe['vol_spike'] | hammerish)
        )

        F = (
            (dataframe['bb_percent'] <= self.f_bb_pct_max.value) &
            (dataframe['low'] <= dataframe['ll_10'] * self.f_ll10_upper.value) &
            (dataframe['low'] >= dataframe['ll_10'].shift(1) * self.f_ll10_lower.value) &
            (dataframe['rsi'] > dataframe['rsi_prev']) &
            (dataframe['close'] >= dataframe['open'])
        )

        dataframe.loc[
            (((A | B | C | D | E | F) & anti_cuchillo & ~no_buy_high & anti_chase) | D),
            'enter_long'
        ] = 1
        return dataframe

    # ── SALIDAS ───────────────────────────────────────────────────────────────
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        reject_upper = (
            (dataframe['upper_wick'] >= dataframe['atr'] * self.reject_atr_mult.value) &
            (dataframe['upper_wick'] > (dataframe['close'] - dataframe['open']).abs() * self.reject_wick_ratio.value) &
            ((dataframe['high'] >= dataframe['bb_upperband'] * 0.999) | (dataframe['close'] >= dataframe['bb_upperband'])) &
            (dataframe['rsi'] >= self.sell_rsi_reject.value)
        )

        dataframe.loc[
            (
                (dataframe['loc_peak']) &
                (dataframe['close'] >= dataframe['bb_upperband'] * 0.999) &
                (dataframe['rsi'] >= self.sell_rsi_peak.value) &
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
                (dataframe['rsi'] >= self.sell_rsi_hh_ema.value) &
                (dataframe['macdhist'] < dataframe['macdhist'].shift(1))
            )
            |
            reject_upper,
            'exit_long'
        ] = 1
        return dataframe

    # ── UTILIDADES ────────────────────────────────────────────────────────────
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

    def _crash_incoming(self, pair: str) -> bool:
        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last = df.iloc[-1]
            prev = df.iloc[-2]
            fast_drop = (
                last['close'] <= last['ema8'] * self.crash_ema_mult.value
            ) and (last['pct_1'] <= self.crash_pct1.value)
            atr_break = (last['low'] < last['ema_fast'] - self.crash_atr_mult.value * last['atr'])
            bb_flush  = (
                (last['bb_percent'] < 0) and
                bool(last['bb_expanding']) and
                (last['macdhist'] < prev['macdhist'])
            )
            di_shift = (
                (last['adx'] > self.crash_adx_min.value) and
                (last['minus_di'] > last['plus_di']) and
                (last['rsi'] < self.crash_rsi_max.value)
            )
            return sum([fast_drop, atr_break, bb_flush or di_shift]) >= 2
        except Exception:
            return False

    # ── CUSTOM EXIT ───────────────────────────────────────────────────────────
    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs
    ) -> Optional[str]:
        if self._crash_incoming(pair):
            if (current_profit is None) or (current_profit > self.MIN_PROFIT_NET):
                return "crash_guard"

        bars = self._bars_elapsed(trade, current_time)
        if bars < self.MIN_HOLD_BARS:
            if not self._strong_bearish_reversal(pair):
                return None

        if current_profit is not None and current_profit >= self.hard_tp.value:
            return "hard_tp"

        if current_profit is None or current_profit < self.MIN_PROFIT_NET:
            return None

        try:
            df   = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last = df.iloc[-1]
            prev = df.iloc[-2]

            near_upper  = (last['close'] >= last['bb_upperband'] * 0.999) or (last['high'] >= last['bb_upperband'])
            loc_peak    = bool(last['high'] >= df['high'].rolling(6).max().iloc[-1])
            rsi_high    = (last['rsi'] >= self.sell_rsi_peak.value)
            bear_candle = (last['close'] < last['open'])
            macd_fade   = (last['macdhist'] < prev['macdhist'])
            ema_break   = (last['close'] < last['ema8'])

            if current_profit >= self.peak_min_profit.value and near_upper and loc_peak and rsi_high and (
                bear_candle or macd_fade or ema_break
            ):
                return "peak_exit_top_optimal"

            if current_profit >= self.hh_ema_min_profit.value and (
                prev['high'] >= df['high'].rolling(20).max().iloc[-2]
            ) and ema_break and macd_fade and (last['rsi'] >= self.sell_rsi_hh_ema.value):
                return "hh_ema8_break_exit"

            upper_wick = float(last['high'] - max(last['open'], last['close']))
            body       = float(abs(last['close'] - last['open']))
            if (current_profit >= self.MIN_PROFIT_NET and near_upper and
                    upper_wick >= last['atr'] * self.reject_atr_mult.value and
                    upper_wick > self.reject_wick_ratio.value * body and
                    last['rsi'] >= self.sell_rsi_wick.value):
                return "upper_wick_reject_exit"

            if current_profit >= (self.MIN_PROFIT_NET + 0.002) and bars >= 6:
                if (last['rsi'] < last['rsi_prev']) and macd_fade and ema_break:
                    return "momentum_fade_exit"

        except Exception:
            pass

        return None

    # ── CUSTOM STOPLOSS (trailing ATR adaptativo) ─────────────────────────────
    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs
    ) -> float:
        if current_profit is None or current_profit < 0.03:
            return self.stoploss

        try:
            df   = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last = df.iloc[-1]
            atr  = float(last['atr'])
            adx  = float(last['adx'])
            roc5 = float(last['roc5'])
        except Exception:
            return stoploss_from_open(current_profit, self.fallback_trail.value)

        strong_trend   = (adx >= self.adx_strong.value and roc5 > 0)
        vertical_rally = (roc5 >= self.roc5_vertical.value)

        k    = self.trail_atr_high.value if current_profit > 0.06 else self.trail_atr_low.value
        dist = (k * atr) / max(current_rate, 1e-9)
        dist = min(self.trail_dist_max.value, max(self.trail_dist_min.value, dist))

        if vertical_rally:
            dist = max(dist, self.trail_vertical_min.value)
        elif not strong_trend:
            dist = min(dist, 0.02)

        if 0.03 <= current_profit < 0.06:
            return stoploss_from_open(current_profit, max(0.018, dist))

        return stoploss_from_open(current_profit, dist)
