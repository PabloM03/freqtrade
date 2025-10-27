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
# 📌 PARÁMETROS GLOBALES AJUSTABLES
# ==========================
# --- Costes y ganancias mínimas ---
FEE_RATE = 0.001
SLIPPAGE_BUFFER = 0.0006
MIN_PROFIT_NET = 6 * FEE_RATE + SLIPPAGE_BUFFER  # ~0.0066
PEAK_MIN_PROFIT = 0.010
HH_EMA_MIN_PROFIT = 0.013
HARD_TP = 0.035

# --- Stoploss y trailing ---
STOPLOSS_ABS = -0.060
TRAIL_ATR_MULT_LOW = 2.2
TRAIL_ATR_MULT_HIGH = 3.4
TRAIL_DIST_MIN = 0.020
TRAIL_DIST_MAX = 0.060
TRAIL_VERTICAL_MIN = 0.028
ADX_STRONG_TREND = 27
ROC5_VERTICAL = 3.5
FALLBACK_TRAIL_DIST = 0.024

# --- Anti-cuchillo ---
PCT1_MIN = -2.5
PCT3_MIN = -5.5
COOLDOWN_BARS = 3

# --- Filtro de compras altas ---
NO_BUY_BB_MULT = 1.000
NO_BUY_EMA20_MULT = 1.000
NO_BUY_RSI_MIN = 55

# --- Zonas de valor para comprar ---
DEEP_BB = 0.16
BB_ZONE_OK = 0.33
LOWER_WICK_BODY_RATIO = 1.30

# --- Reglas de compra específicas ---
# A) Mínimo local
A_LL10_MULT = 1.0035
A_RSI_PREV_MAX = 46
# C) StochRSI en sobreventa
C_STOCH_MAX = 25
# D) Capitulación
D_PCT1_MAX = -2.2
D_PCT3_MAX = -4.8
D_BB_PERCENT_MAX = 0.04
D_TAIL_ATR_MULT = 1.25
# E) Pullback a EMA8
E_RSI_MIN = 44
E_LL10_MULT = 1.006
E_BB_MID_MULT = 0.996
# F) Doble toque en valle
F_BB_PERCENT_MAX = 0.28
F_LL10_UPPER = 1.004
F_LL10_LOWER = 0.992

# --- Ventas ---
REJECT_UPPER_ATR_MULT = 1.00
REJECT_WICK_BODY_RATIO = 1.25
SELL_RSI_PEAK = 72
SELL_RSI_REJECT = 66
SELL_RSI_HH_EMA = 65
SELL_RSI_WICK = 66

# --- Crash-guard ---
CRASH_FAST_DROP_EMA8 = 0.988
CRASH_FAST_DROP_PCT1 = -1.0
CRASH_ATR_BREAK_MULT = 1.6
CRASH_ADX_MIN = 26
CRASH_RSI_MAX = 50

# --- Timeframe y arranque ---
TIMEFRAME = '5m'
STARTUP_CANDLES = 130

# --- Bollinger config ---
BB40_WINDOW = 40
BB40_STDS = 2.2
BB20_WINDOW = 20
BB20_STDS = 2.2

# --- Anti-chase (evitar compras en subidas/picos) ---
MAX_PCT_UP_1 = 0.6       # %
MAX_PCT_UP_3 = 1.8       # %
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


class CombinedBinHAndCluc(IStrategy):
    """
    Compras: en bajadas óptimas (mínimo local + capitulación/giro), evitando persecuciones.
    Ventas: en picos y rechazos claros. Crash-guard y trailing dinámico moderado.
    """

    # === Mapeo de parámetros globales ===
    FEE_RATE = FEE_RATE
    SLIPPAGE_BUFFER = SLIPPAGE_BUFFER
    MIN_PROFIT_NET = MIN_PROFIT_NET
    PEAK_MIN_PROFIT = PEAK_MIN_PROFIT
    HH_EMA_MIN_PROFIT = HH_EMA_MIN_PROFIT
    HARD_TP = HARD_TP

    # --- Núcleo de estrategia (nombres actuales, sin deprecations) ---
    stoploss = STOPLOSS_ABS
    timeframe = TIMEFRAME
    startup_candle_count = STARTUP_CANDLES

    use_exit_signal = False                 # (antes use_sell_signal)
    exit_profit_only = True                 # (antes sell_profit_only)
    ignore_roi_if_entry_signal = False      # (antes ignore_roi_if_buy_signal)

    # ROI realista (evita cierre instantáneo a 0%)
    minimal_roi = {
        "0": 0.03,      # 3% si se da rápido
        "60": 0.01      # 1% tras 60 min
    }

    # Trailing (habilitado)
    trailing_stop = True
    trailing_stop_positive = 0.01
    trailing_stop_positive_offset = 0.02
    trailing_only_offset_is_reached = True

    MIN_HOLD_BARS = 1

    # Anti-cuchillo / filtros
    PCT1_MIN = PCT1_MIN
    PCT3_MIN = PCT3_MIN
    COOLDOWN_BARS = COOLDOWN_BARS

    NO_BUY_BB_MULT = NO_BUY_BB_MULT
    NO_BUY_EMA20_MULT = NO_BUY_EMA20_MULT
    NO_BUY_RSI_MIN = NO_BUY_RSI_MIN

    DEEP_BB = DEEP_BB
    BB_ZONE_OK = BB_ZONE_OK
    LOWER_WICK_BODY_RATIO = LOWER_WICK_BODY_RATIO

    # Reglas compra
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
    F_BB_PERCENT_MAX = F_BB_PERCENT_MAX
    F_LL10_UPPER = F_LL10_UPPER
    F_LL10_LOWER = F_LL10_LOWER

    # Ventas
    REJECT_UPPER_ATR_MULT = REJECT_UPPER_ATR_MULT
    REJECT_WICK_BODY_RATIO = REJECT_WICK_BODY_RATIO
    SELL_RSI_PEAK = SELL_RSI_PEAK
    SELL_RSI_REJECT = SELL_RSI_REJECT
    SELL_RSI_HH_EMA = SELL_RSI_HH_EMA
    SELL_RSI_WICK = SELL_RSI_WICK

    # Crash
    CRASH_FAST_DROP_EMA8 = CRASH_FAST_DROP_EMA8
    CRASH_FAST_DROP_PCT1 = CRASH_FAST_DROP_PCT1
    CRASH_ATR_BREAK_MULT = CRASH_ATR_BREAK_MULT
    CRASH_ADX_MIN = CRASH_ADX_MIN
    CRASH_RSI_MAX = CRASH_RSI_MAX

    # Trailing dinámico
    TRAIL_ATR_MULT_LOW = TRAIL_ATR_MULT_LOW
    TRAIL_ATR_MULT_HIGH = TRAIL_ATR_MULT_HIGH
    TRAIL_DIST_MIN = TRAIL_DIST_MIN
    TRAIL_DIST_MAX = TRAIL_DIST_MAX
    TRAIL_VERTICAL_MIN = TRAIL_VERTICAL_MIN
    ADX_STRONG_TREND = ADX_STRONG_TREND
    ROC5_VERTICAL = ROC5_VERTICAL
    FALLBACK_TRAIL_DIST = FALLBACK_TRAIL_DIST

    # BB config
    BB40_WINDOW = BB40_WINDOW
    BB40_STDS = BB40_STDS
    BB20_WINDOW = BB20_WINDOW
    BB20_STDS = BB20_STDS

    # ---------------------- INDICADORES ----------------------
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # BinHV45 (BB40)
        mid, lower = bollinger_bands(
            dataframe['close'], window_size=self.BB40_WINDOW, num_of_std=self.BB40_STDS
        )
        dataframe['lower'] = lower
        dataframe['bbdelta'] = (mid - dataframe['lower']).abs()
        dataframe['closedelta'] = (dataframe['close'] - dataframe['close'].shift()).abs()
        dataframe['tail'] = (dataframe['close'] - dataframe['low']).abs()

        # Bollinger 20
        tp = qtpylib.typical_price(dataframe)
        bb = qtpylib.bollinger_bands(tp, window=self.BB20_WINDOW, stds=self.BB20_STDS)
        dataframe['bb_lowerband']  = bb['lower']
        dataframe['bb_middleband'] = bb['mid']
        dataframe['bb_upperband']  = bb['upper']
        dataframe['bb_width'] = (dataframe['bb_upperband'] - dataframe['bb_lowerband']) / dataframe['bb_middleband']
        denom = (dataframe['bb_upperband'] - dataframe['bb_lowerband']).replace(0, np.nan)
        dataframe['bb_percent'] = (dataframe['close'] - dataframe['bb_lowerband']) / denom
        dataframe['bb_expanding'] = (dataframe['bb_width'] > dataframe['bb_width'].shift(1))

        # EMAs / fuerza
        dataframe['ema8']     = ta.EMA(dataframe, timeperiod=8)
        dataframe['ema_fast'] = ta.EMA(dataframe, timeperiod=20)
        dataframe['ema_slow'] = ta.EMA(dataframe, timeperiod=50)
        dataframe['volume_mean_slow'] = dataframe['volume'].rolling(window=30).mean()
        dataframe['ema8_slope_up'] = dataframe['ema8'] > dataframe['ema8'].shift(1)

        # RSI / ADX / DI
        dataframe['rsi']      = ta.RSI(dataframe, timeperiod=14)
        dataframe['rsi_prev'] = dataframe['rsi'].shift(1)
        dataframe['adx']      = ta.ADX(dataframe, timeperiod=14)
        dataframe['plus_di']  = ta.PLUS_DI(dataframe, timeperiod=14)
        dataframe['minus_di'] = ta.MINUS_DI(dataframe, timeperiod=14)

        # StochRSI
        stoch = ta.STOCHRSI(dataframe, timeperiod=14, fastk_period=3, fastd_period=3)
        dataframe['stoch_k'] = stoch['fastk']
        dataframe['stoch_d'] = stoch['fastd']
        dataframe['stoch_k_prev'] = dataframe['stoch_k'].shift(1)
        dataframe['stoch_d_prev'] = dataframe['stoch_d'].shift(1)

        # MACD
        macd = ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)
        dataframe['macd']      = macd['macd']
        dataframe['macdsignal']= macd['macdsignal']
        dataframe['macdhist']  = macd['macdhist']

        # Momentum/extremos
        dataframe['roc5'] = ta.ROC(dataframe, timeperiod=5)
        dataframe['ll_8']  = dataframe['low'].rolling(8).min()
        dataframe['ll_10'] = dataframe['low'].rolling(10).min()
        dataframe['ll_20'] = dataframe['low'].rolling(20).min()
        dataframe['hh_20'] = dataframe['high'].rolling(20).max()

        # ATR y variaciones
        dataframe['atr']  = ta.ATR(dataframe, timeperiod=14)
        dataframe['pct_1']= dataframe['close'].pct_change(1) * 100.0
        dataframe['pct_3']= dataframe['close'].pct_change(3) * 100.0

        # Estructura / cooldown
        body = (dataframe['close'] - dataframe['open']).abs()
        dataframe['big_red']  = (dataframe['close'] < dataframe['open']) & (body > 1.2 * dataframe['atr'])
        dataframe['cooldown'] = dataframe['big_red'].rolling(self.COOLDOWN_BARS).max()

        # Mechas
        dataframe['upper_wick'] = (dataframe['high'] - np.maximum(dataframe['open'], dataframe['close'])).abs()
        dataframe['lower_wick'] = (np.minimum(dataframe['open'], dataframe['close']) - dataframe['low']).abs()

        # Volumen relativo
        dataframe['vol_spike'] = dataframe['volume'] > (dataframe['volume_mean_slow'] * 1.15)

        # Máximo/mínimo local reciente
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

        # Anti-chase helpers
        dataframe['green'] = dataframe['close'] > dataframe['open']
        dataframe['green_streak'] = (
            dataframe['green'].rolling(window=MAX_GREEN_STREAK, min_periods=1).sum()
        )
        dataframe['vol_mean_fast'] = dataframe['volume'].rolling(window=10).mean()
        dataframe['pump_vol'] = dataframe['volume'] > (dataframe['vol_mean_fast'] * PUMP_VOL_MULT)
        dataframe['near_hh'] = dataframe['close'] >= (dataframe['hh_20'] * (1.0 - NEAR_HH_DISTANCE))

        return dataframe

    # ---------------------- COMPRAS ----------------------
    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        anti_cuchillo = (
            (dataframe['pct_1'] > self.PCT1_MIN) &
            (dataframe['pct_3'] > self.PCT3_MIN) &
            (~dataframe['cooldown'].astype(bool)) &
            (~((dataframe['bb_percent'] < 0) & dataframe['bb_expanding'])) &
            (dataframe['minus_di'] <= dataframe['plus_di']) &
            (dataframe['volume'] > 0)
        )

        # Evitar compras “arriba” (requiere las 3 a la vez)
        no_buy_high = (
            (dataframe['close'] > dataframe['bb_middleband'] * self.NO_BUY_BB_MULT) &
            (dataframe['close'] > dataframe['ema_fast'] * self.NO_BUY_EMA20_MULT) &
            (dataframe['rsi'] > self.NO_BUY_RSI_MIN)
        )

        # Zonas de valor
        deep_bb    = (dataframe['bb_percent'] <= self.DEEP_BB)
        bb_zone_ok = (dataframe['bb_percent'] <= self.BB_ZONE_OK)

        lower_wick = dataframe['lower_wick']
        body       = (dataframe['close'] - dataframe['open']).abs()
        hammerish  = lower_wick > self.LOWER_WICK_BODY_RATIO * body

        # Anti-chase (no perseguir subidones)
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

        # A) Mínimo local + giro RSI + martillo/volumen
        A = (
            (dataframe['loc_trough']) &
            ((dataframe['low'] <= dataframe['ll_10'] * self.A_LL10_MULT) | deep_bb) &
            (dataframe['rsi_prev'] < self.A_RSI_PREV_MAX) & (dataframe['rsi'] > dataframe['rsi_prev']) &
            (dataframe['close'] >= dataframe['open']) &
            (hammerish | dataframe['vol_spike'])
        )

        # B) Re-entrada tras cerrar fuera de BB inferior y volver dentro
        B = (
            (dataframe['close'].shift(1) < dataframe['bb_lowerband'].shift(1)) &
            (dataframe['close'] > dataframe['bb_lowerband']) &
            (dataframe['rsi'] > dataframe['rsi_prev']) &
            (bb_zone_ok)
        )

        # C) StochRSI cruce en sobreventa + MACD no empeora + zona baja BB
        C = (
            (dataframe['stoch_k_prev'] < dataframe['stoch_d_prev']) &
            (dataframe['stoch_k'] > dataframe['stoch_d']) &
            (dataframe['stoch_k'] < self.C_STOCH_MAX) & (dataframe['stoch_d'] < self.C_STOCH_MAX) &
            (dataframe['macdhist'] >= dataframe['macdhist'].shift(1)) &
            (bb_zone_ok)
        )

        # D) Capitulación
        D = (
            ((dataframe['pct_1'] <= self.D_PCT1_MAX) | (dataframe['pct_3'] <= self.D_PCT3_MAX)) &
            (dataframe['bb_percent'] <= self.D_BB_PERCENT_MAX) &
            (dataframe['tail'] >= dataframe['atr'] * self.D_TAIL_ATR_MULT) &
            (dataframe['close'] >= dataframe['open'])
        )

        # E) Pullback a EMA8 ascendente en zona media-baja
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

        # F) Doble toque en valle
        F = (
            (dataframe['bb_percent'] <= self.F_BB_PERCENT_MAX) &
            (dataframe['low'] <= dataframe['ll_10'] * self.F_LL10_UPPER) &
            (dataframe['low'] >= dataframe['ll_10'].shift(1) * self.F_LL10_LOWER) &
            (dataframe['rsi'] > dataframe['rsi_prev']) &
            (dataframe['close'] >= dataframe['open'])
        )

        dataframe.loc[
            (((A | B | C | D | E | F) & anti_cuchillo & ~no_buy_high & anti_chase) | D),
            'buy'
        ] = 1
        return dataframe

    # ---------------------- VENTAS (señales, por si activas use_exit_signal=True) ----------------------
    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
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
            |
            reject_upper,
            'sell'
        ] = 1
        return dataframe

    # ---------------------- UTILIDADES ----------------------
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
            fast_drop = (last['close'] <= last['ema8'] * self.CRASH_FAST_DROP_EMA8) and (last['pct_1'] <= self.CRASH_FAST_DROP_PCT1)
            atr_break = (last['low'] < last['ema_fast'] - self.CRASH_ATR_BREAK_MULT * last['atr'])
            bb_flush = (last['bb_percent'] < 0) and bool(last['bb_expanding']) and (last['macdhist'] < prev['macdhist'])
            di_shift = (last['adx'] > self.CRASH_ADX_MIN) and (last['minus_di'] > last['plus_di']) and (last['rsi'] < self.CRASH_RSI_MAX)
            return sum([fast_drop, atr_break, bb_flush or di_shift]) >= 2
        except Exception:
            return False

    # ---------------------- EXITS PERSONALIZADOS ----------------------
    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs
    ) -> Optional[str]:

        # Crash guard
        if self._crash_incoming(pair):
            if (current_profit is None) or (current_profit > self.MIN_PROFIT_NET):
                return "crash_guard"

        bars = self._bars_elapsed(trade, current_time)
        if bars < self.MIN_HOLD_BARS:
            if not self._strong_bearish_reversal(pair):
                return None

        # TP duro
        if current_profit is not None and current_profit >= self.HARD_TP:
            return "hard_tp"

        # Requiere beneficio neto
        if current_profit is None or current_profit < self.MIN_PROFIT_NET:
            return None

        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last  = df.iloc[-1]
            prev  = df.iloc[-2]

            near_upper = (last['close'] >= last['bb_upperband'] * 0.999) or (last['high'] >= last['bb_upperband'])
            loc_peak   = bool(last['high'] >= df['high'].rolling(6).max().iloc[-1])
            rsi_high   = (last['rsi'] >= self.SELL_RSI_PEAK)
            bear_candle= (last['close'] < last['open'])
            macd_fade  = (last['macdhist'] < prev['macdhist'])
            ema_break  = (last['close'] < last['ema8'])

            # Pico óptimo: banda sup + máximo local + giro claro
            if current_profit >= self.PEAK_MIN_PROFIT and near_upper and loc_peak and rsi_high and (
                bear_candle or macd_fade or ema_break
            ):
                return "peak_exit_top_optimal"

            # HH + ruptura EMA8 + MACD debilitando
            if current_profit >= self.HH_EMA_MIN_PROFIT and (prev['high'] >= df['high'].rolling(20).max().iloc[-2]) and ema_break and macd_fade and (last['rsi'] >= self.SELL_RSI_HH_EMA):
                return "hh_ema8_break_exit"

            # Rechazo de mecha grande en zona alta
            upper_wick = float(last['high'] - max(last['open'], last['close']))
            body = float(abs(last['close'] - last['open']))
            if current_profit >= self.MIN_PROFIT_NET and near_upper and (upper_wick >= last['atr'] * self.REJECT_UPPER_ATR_MULT) and (upper_wick > self.REJECT_WICK_BODY_RATIO * body) and (last['rsi'] >= self.SELL_RSI_WICK):
                return "upper_wick_reject_exit"

            # Pérdida de momentum tras varias velas verdes
            if current_profit >= (self.MIN_PROFIT_NET + 0.002) and bars >= 6:
                if (last['rsi'] < last['rsi_prev']) and macd_fade and ema_break:
                    return "momentum_fade_exit"

        except Exception:
            pass

        return None

    # ---------------------- TRAILING DINÁMICO ----------------------
    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs
    ) -> float:
        # Hasta 3% de beneficio, usa stoploss fijo
        if current_profit is None or current_profit < 0.03:
            return self.stoploss

        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last = df.iloc[-1]
            atr = float(last['atr'])
            adx = float(last['adx'])
            roc5 = float(last['roc5'])
        except Exception:
            # Fallback si no hay datos
            return stoploss_from_open(current_profit, self.FALLBACK_TRAIL_DIST)

        strong_trend = (adx >= self.ADX_STRONG_TREND and roc5 > 0)
        vertical_rally = (roc5 >= self.ROC5_VERTICAL)

        k = self.TRAIL_ATR_MULT_HIGH if current_profit > 0.06 else self.TRAIL_ATR_MULT_LOW
        dist = (k * atr) / max(current_rate, 1e-9)
        dist = min(self.TRAIL_DIST_MAX, max(self.TRAIL_DIST_MIN, dist))

        if vertical_rally:
            dist = max(dist, self.TRAIL_VERTICAL_MIN)
        elif not strong_trend:
            dist = min(dist, 0.02)

        if 0.03 <= current_profit < 0.06:
            return stoploss_from_open(current_profit, max(0.018, dist))

        return stoploss_from_open(current_profit, dist)
