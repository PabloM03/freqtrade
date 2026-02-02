import freqtrade.vendor.qtpylib.indicators as qtpylib
import numpy as np
import talib.abstract as ta

from freqtrade.strategy.interface import IStrategy
from freqtrade.strategy import stoploss_from_open
from pandas import DataFrame
from datetime import datetime
from typing import Optional
from freqtrade.persistence import Trade


# ==========================
# PARÁMETROS (más "swing intradía")
# ==========================
FEE_RATE = 0.001
SLIPPAGE_BUFFER = 0.0006

# Neto mínimo (2 fees + slippage + margen)
MIN_PROFIT_NET = (2 * FEE_RATE) + SLIPPAGE_BUFFER + 0.006  # ~0.0086 (0.86%)

# objetivos
HARD_TP = 0.060
PEAK_MIN_PROFIT = 0.020
HH_EMA_MIN_PROFIT = 0.028

# stoploss
STOPLOSS_ABS = -0.070

# trailing dinámico
TRAIL_ATR_MULT_LOW = 2.6
TRAIL_ATR_MULT_HIGH = 4.0
TRAIL_DIST_MIN = 0.022
TRAIL_DIST_MAX = 0.080
TRAIL_VERTICAL_MIN = 0.035
ADX_STRONG_TREND = 28
ROC5_VERTICAL = 3.8
FALLBACK_TRAIL_DIST = 0.030

# anti-cuchillo
PCT1_MIN = -2.5
PCT3_MIN = -5.5
COOLDOWN_BARS = 3

# filtro de compras altas
NO_BUY_BB_MULT = 1.000
NO_BUY_EMA20_MULT = 1.000
NO_BUY_RSI_MIN = 55

# zonas BB
DEEP_BB = 0.16
BB_ZONE_OK = 0.33
LOWER_WICK_BODY_RATIO = 1.30

# reglas compra
A_LL10_MULT = 1.0035
A_RSI_PREV_MAX = 46
C_STOCH_MAX = 25
D_PCT1_MAX = -2.2
D_PCT3_MAX = -4.8
D_BB_PERCENT_MAX = 0.04
D_TAIL_ATR_MULT = 1.25
E_RSI_MIN = 44
E_LL10_MULT = 1.006
E_BB_MID_MULT = 0.996
F_BB_PERCENT_MAX = 0.28
F_LL10_UPPER = 1.004
F_LL10_LOWER = 0.992

# ventas
REJECT_UPPER_ATR_MULT = 1.10
REJECT_WICK_BODY_RATIO = 1.35
SELL_RSI_PEAK = 72
SELL_RSI_REJECT = 66
SELL_RSI_HH_EMA = 65
SELL_RSI_WICK = 66

# crash-guard
CRASH_FAST_DROP_EMA8 = 0.988
CRASH_FAST_DROP_PCT1 = -1.0
CRASH_ATR_BREAK_MULT = 1.6
CRASH_ADX_MIN = 26
CRASH_RSI_MAX = 50

TIMEFRAME = '5m'
STARTUP_CANDLES = 130

BB40_WINDOW = 40
BB40_STDS = 2.2
BB20_WINDOW = 20
BB20_STDS = 2.2

# anti-chase
MAX_PCT_UP_1 = 0.6
MAX_PCT_UP_3 = 1.8
MAX_GREEN_STREAK = 2
BUY_BELOW_EMA20_MULT = 0.996
BUY_BELOW_BB_MID_MULT = 0.996
BB_EXPANDING_HIGH = 0.50
PUMP_VOL_MULT = 2.2
NEAR_HH_DISTANCE = 0.0150
REQUIRE_RED_PULLBACK = True


def bollinger_bands(stock_price, window_size, num_of_std):
    rolling_mean = stock_price.rolling(window=window_size).mean()
    rolling_std = stock_price.rolling(window=window_size).std()
    lower_band = rolling_mean - (rolling_std * num_of_std)
    return np.nan_to_num(rolling_mean), np.nan_to_num(lower_band)


class CombinedBinHAndCluc_ProHold(IStrategy):
    """
    ProHold blindada:
    - Bloquea microsalidas (ROI/exit_signal/trailing) por debajo de MIN_PROFIT_NET
    - Fuerza hold mínimo (MIN_HOLD_BARS)
    - Trailing dinámico real (custom_stoploss activo)
    """

    timeframe = TIMEFRAME
    startup_candle_count = STARTUP_CANDLES
    process_only_new_candles = True

    stoploss = STOPLOSS_ABS

    # Guardarraíl alto: si sale por ROI, que sea ya algo decente.
    minimal_roi = {
        "0": 0.050,
        "60": 0.035,
        "180": 0.020,
        "360": 0.012
    }

    use_exit_signal = False
    exit_profit_only = True
    ignore_roi_if_entry_signal = False

    # IMPORTANTE: activar custom_stoploss
    use_custom_stoploss = True

    # NO usar trailing del core (para que no pelee con custom_stoploss)
    trailing_stop = False

    MIN_HOLD_BARS = 6  # 30 min en 5m

    # ---------------------- INDICADORES ----------------------
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        mid, lower = bollinger_bands(
            dataframe['close'], window_size=BB40_WINDOW, num_of_std=BB40_STDS
        )
        dataframe['lower'] = lower
        dataframe['bbdelta'] = (mid - dataframe['lower']).abs()
        dataframe['closedelta'] = (dataframe['close'] - dataframe['close'].shift()).abs()
        dataframe['tail'] = (dataframe['close'] - dataframe['low']).abs()

        tp = qtpylib.typical_price(dataframe)
        bb = qtpylib.bollinger_bands(tp, window=BB20_WINDOW, stds=BB20_STDS)
        dataframe['bb_lowerband'] = bb['lower']
        dataframe['bb_middleband'] = bb['mid']
        dataframe['bb_upperband'] = bb['upper']
        dataframe['bb_width'] = (dataframe['bb_upperband'] - dataframe['bb_lowerband']) / dataframe['bb_middleband']
        denom = (dataframe['bb_upperband'] - dataframe['bb_lowerband']).replace(0, np.nan)
        dataframe['bb_percent'] = (dataframe['close'] - dataframe['bb_lowerband']) / denom
        dataframe['bb_expanding'] = (dataframe['bb_width'] > dataframe['bb_width'].shift(1))

        dataframe['ema8'] = ta.EMA(dataframe, timeperiod=8)
        dataframe['ema_fast'] = ta.EMA(dataframe, timeperiod=20)
        dataframe['ema_slow'] = ta.EMA(dataframe, timeperiod=50)
        dataframe['ema8_slope_up'] = dataframe['ema8'] > dataframe['ema8'].shift(1)

        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['rsi_prev'] = dataframe['rsi'].shift(1)
        dataframe['adx'] = ta.ADX(dataframe, timeperiod=14)
        dataframe['plus_di'] = ta.PLUS_DI(dataframe, timeperiod=14)
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
        dataframe['ll_8'] = dataframe['low'].rolling(8).min()
        dataframe['ll_10'] = dataframe['low'].rolling(10).min()
        dataframe['ll_20'] = dataframe['low'].rolling(20).min()
        dataframe['hh_20'] = dataframe['high'].rolling(20).max()

        dataframe['atr'] = ta.ATR(dataframe, timeperiod=14)
        dataframe['pct_1'] = dataframe['close'].pct_change(1) * 100.0
        dataframe['pct_3'] = dataframe['close'].pct_change(3) * 100.0

        body = (dataframe['close'] - dataframe['open']).abs()
        dataframe['big_red'] = (dataframe['close'] < dataframe['open']) & (body > 1.2 * dataframe['atr'])
        dataframe['cooldown'] = dataframe['big_red'].rolling(COOLDOWN_BARS).max()

        dataframe['upper_wick'] = (dataframe['high'] - np.maximum(dataframe['open'], dataframe['close'])).abs()
        dataframe['lower_wick'] = (np.minimum(dataframe['open'], dataframe['close']) - dataframe['low']).abs()

        dataframe['volume_mean_slow'] = dataframe['volume'].rolling(window=30).mean()
        dataframe['vol_spike'] = dataframe['volume'] > (dataframe['volume_mean_slow'] * 1.15)

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
        dataframe['green_streak'] = dataframe['green'].rolling(window=MAX_GREEN_STREAK, min_periods=1).sum()
        dataframe['vol_mean_fast'] = dataframe['volume'].rolling(window=10).mean()
        dataframe['pump_vol'] = dataframe['volume'] > (dataframe['vol_mean_fast'] * PUMP_VOL_MULT)
        dataframe['near_hh'] = dataframe['close'] >= (dataframe['hh_20'] * (1.0 - NEAR_HH_DISTANCE))

        dataframe['trend_ok'] = (dataframe['adx'] > 22) & (dataframe['plus_di'] > dataframe['minus_di']) & dataframe['ema8_slope_up']
        dataframe['trend_strong'] = (dataframe['adx'] >= ADX_STRONG_TREND) & (dataframe['plus_di'] > dataframe['minus_di']) & dataframe['ema8_slope_up']

        return dataframe

    # ---------------------- COMPRAS ----------------------
    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        anti_cuchillo = (
            (dataframe['pct_1'] > PCT1_MIN) &
            (dataframe['pct_3'] > PCT3_MIN) &
            (~dataframe['cooldown'].astype(bool)) &
            (~((dataframe['bb_percent'] < 0) & dataframe['bb_expanding'])) &
            (dataframe['minus_di'] <= dataframe['plus_di']) &
            (dataframe['volume'] > 0)
        )

        no_buy_high = (
            (dataframe['close'] > dataframe['bb_middleband'] * NO_BUY_BB_MULT) &
            (dataframe['close'] > dataframe['ema_fast'] * NO_BUY_EMA20_MULT) &
            (dataframe['rsi'] > NO_BUY_RSI_MIN)
        )

        deep_bb = (dataframe['bb_percent'] <= DEEP_BB)
        bb_zone_ok = (dataframe['bb_percent'] <= BB_ZONE_OK)

        lower_wick = dataframe['lower_wick']
        body = (dataframe['close'] - dataframe['open']).abs()
        hammerish = lower_wick > LOWER_WICK_BODY_RATIO * body

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
        if REQUIRE_RED_PULLBACK:
            anti_chase = anti_chase & (
                (dataframe['close'] <= dataframe['open']) |
                (dataframe['low'] < dataframe['close'].shift(1))
            )

        A = (
            (dataframe['loc_trough']) &
            ((dataframe['low'] <= dataframe['ll_10'] * A_LL10_MULT) | deep_bb) &
            (dataframe['rsi_prev'] < A_RSI_PREV_MAX) & (dataframe['rsi'] > dataframe['rsi_prev']) &
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
            (dataframe['stoch_k'] < C_STOCH_MAX) & (dataframe['stoch_d'] < C_STOCH_MAX) &
            (dataframe['macdhist'] >= dataframe['macdhist'].shift(1)) &
            (bb_zone_ok)
        )

        D = (
            ((dataframe['pct_1'] <= D_PCT1_MAX) | (dataframe['pct_3'] <= D_PCT3_MAX)) &
            (dataframe['bb_percent'] <= D_BB_PERCENT_MAX) &
            (dataframe['tail'] >= dataframe['atr'] * D_TAIL_ATR_MULT) &
            (dataframe['close'] >= dataframe['open'])
        )

        E = (
            (dataframe['close'] > dataframe['ema8']) &
            (dataframe['close'].shift(1) <= dataframe['ema8'].shift(1)) &
            (dataframe['ema8_slope_up']) &
            (dataframe['rsi'] >= E_RSI_MIN) & (dataframe['rsi'] > dataframe['rsi_prev']) &
            ((dataframe['low'] <= dataframe['ll_10'] * E_LL10_MULT) |
             (dataframe['close'] <= dataframe['bb_middleband'] * E_BB_MID_MULT) |
             bb_zone_ok) &
            (dataframe['vol_spike'] | hammerish)
        )

        F = (
            (dataframe['bb_percent'] <= F_BB_PERCENT_MAX) &
            (dataframe['low'] <= dataframe['ll_10'] * F_LL10_UPPER) &
            (dataframe['low'] >= dataframe['ll_10'].shift(1) * F_LL10_LOWER) &
            (dataframe['rsi'] > dataframe['rsi_prev']) &
            (dataframe['close'] >= dataframe['open'])
        )

        dataframe.loc[(((A | B | C | D | E | F) & anti_cuchillo & ~no_buy_high & anti_chase) | D), 'buy'] = 1
        return dataframe

    # ---------------------- UTIL ----------------------
    def _bars_elapsed(self, trade: Trade, current_time: datetime) -> int:
        tf_minutes = int(self.timeframe.rstrip('m'))
        seconds = (current_time - trade.open_date_utc).total_seconds()
        return int(max(0, seconds) // (tf_minutes * 60))

    def _crash_incoming(self, pair: str) -> bool:
        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last = df.iloc[-1]
            prev = df.iloc[-2]
            fast_drop = (last['close'] <= last['ema8'] * CRASH_FAST_DROP_EMA8) and (last['pct_1'] <= CRASH_FAST_DROP_PCT1)
            atr_break = (last['low'] < last['ema_fast'] - CRASH_ATR_BREAK_MULT * last['atr'])
            bb_flush = (last['bb_percent'] < 0) and bool(last['bb_expanding']) and (last['macdhist'] < prev['macdhist'])
            di_shift = (last['adx'] > CRASH_ADX_MIN) and (last['minus_di'] > last['plus_di']) and (last['rsi'] < CRASH_RSI_MAX)
            return sum([fast_drop, atr_break, bb_flush or di_shift]) >= 2
        except Exception:
            return False

    # ---------------------- EXIT (inteligente) ----------------------
    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs
    ) -> Optional[str]:

        # crash guard: permite salir aunque no hayas llegado a neto
        if self._crash_incoming(pair):
            if (current_profit is None) or (current_profit >= 0.0):
                return "crash_guard"

        if current_profit is None:
            return None

        bars = self._bars_elapsed(trade, current_time)

        if current_profit < MIN_PROFIT_NET:
            return None

        if bars < self.MIN_HOLD_BARS:
            return None

        if current_profit >= HARD_TP:
            return "hard_tp"

        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last = df.iloc[-1]
            prev = df.iloc[-2]

            trend_ok = bool(last.get('trend_ok', False))
            trend_strong = bool(last.get('trend_strong', False))

            near_upper = (last['close'] >= last['bb_upperband'] * 0.999) or (last['high'] >= last['bb_upperband'])
            loc_peak = bool(last['loc_peak'])
            bear_candle = (last['close'] < last['open'])
            macd_fade = (last['macdhist'] < prev['macdhist'])
            ema_break = (last['close'] < last['ema8'])

            upper_wick = float(last['high'] - max(last['open'], last['close']))
            body = float(abs(last['close'] - last['open']))

            # Tendencia fuerte: deja correr, vende solo si rompe + se apaga
            if trend_strong:
                if current_profit >= 0.040 and ema_break and macd_fade:
                    return "trend_strong_fade_exit"
                return None

            # Pico óptimo
            if current_profit >= PEAK_MIN_PROFIT and near_upper and loc_peak and (last['rsi'] >= SELL_RSI_PEAK) and (bear_candle or macd_fade or ema_break):
                return "peak_exit"

            # Rechazo por mecha grande
            if near_upper and (upper_wick >= last['atr'] * REJECT_UPPER_ATR_MULT) and (upper_wick > REJECT_WICK_BODY_RATIO * body) and (last['rsi'] >= SELL_RSI_WICK):
                if trend_ok and current_profit < 0.020:
                    return None
                return "upper_wick_reject_exit"

            # Pérdida de momentum
            if current_profit >= 0.018 and (last['rsi'] < last['rsi_prev']) and macd_fade and ema_break:
                return "momentum_fade_exit"

        except Exception:
            pass

        return None

    # ---------------------- BLOQUEO DE MICROSALIDAS ----------------------
    def confirm_trade_exit(
        self,
        pair: str,
        trade: Trade,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        exit_reason: str,
        current_time: datetime,
        **kwargs
    ) -> bool:
        """
        Veta cierres cutres:
        - Bloquea ROI / exit_signal / trailing / force_exit si no se cumple neto mínimo
        - Bloquea cualquier salida antes del hold mínimo (excepto crash_guard)
        """
        # crash_guard siempre permitido
        if exit_reason == "crash_guard":
            return True

        # calcula bars y profit actual estimado si viene en kwargs
        bars = self._bars_elapsed(trade, current_time)

        # Freqtrade suele pasar current_profit en kwargs en versiones recientes
        current_profit = kwargs.get("current_profit", None)

        # si no viene, no bloquees a ciegas por profit, pero sí por tiempo mínimo
        if bars < self.MIN_HOLD_BARS:
            return False

        if current_profit is not None and current_profit < MIN_PROFIT_NET:
            # aquí es donde matas el 0.03% “roi”
            return False

        return True

    # ---------------------- STOPLOSS dinámico ----------------------
    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs
    ) -> float:

        if current_profit is None or current_profit < 0.025:
            return self.stoploss

        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last = df.iloc[-1]
            atr = float(last['atr'])
            adx = float(last['adx'])
            roc5 = float(last['roc5'])
        except Exception:
            return stoploss_from_open(current_profit, FALLBACK_TRAIL_DIST)

        strong_trend = (adx >= ADX_STRONG_TREND and roc5 > 0)
        vertical_rally = (roc5 >= ROC5_VERTICAL)

        k = TRAIL_ATR_MULT_HIGH if current_profit > 0.08 else TRAIL_ATR_MULT_LOW
        dist = (k * atr) / max(current_rate, 1e-9)
        dist = min(TRAIL_DIST_MAX, max(TRAIL_DIST_MIN, dist))

        if vertical_rally:
            dist = max(dist, TRAIL_VERTICAL_MIN)
        elif not strong_trend:
            dist = min(dist, 0.026)

        return stoploss_from_open(current_profit, dist)
