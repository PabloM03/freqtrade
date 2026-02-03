import freqtrade.vendor.qtpylib.indicators as qtpylib
import numpy as np
import talib.abstract as ta

from freqtrade.strategy.interface import IStrategy
from freqtrade.strategy import stoploss_from_open
from freqtrade.strategy import DecimalParameter, IntParameter
from pandas import DataFrame
from datetime import datetime
from typing import Optional
from freqtrade.persistence import Trade


# ==========================
# PARÁMETROS BASE (constantes)
# ==========================
FEE_RATE = 0.001
SLIPPAGE_BUFFER = 0.0006

# stoploss absoluto base
STOPLOSS_ABS = -0.070

TIMEFRAME = '5m'
STARTUP_CANDLES = 130

BB40_WINDOW = 40
BB40_STDS = 2.2
BB20_WINDOW = 20
BB20_STDS = 2.2

# anti-cuchillo
PCT1_MIN = -2.5
PCT3_MIN = -5.5
COOLDOWN_BARS = 3

# filtro de compras altas
NO_BUY_BB_MULT = 1.000
NO_BUY_EMA20_MULT = 1.000

# zonas BB
DEEP_BB = 0.16
BB_ZONE_OK = 0.33
LOWER_WICK_BODY_RATIO = 1.30

# reglas compra (mantengo thresholds)
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
SELL_RSI_WICK = 66

# crash-guard
CRASH_FAST_DROP_EMA8 = 0.988
CRASH_FAST_DROP_PCT1 = -1.0
CRASH_ATR_BREAK_MULT = 1.6
CRASH_ADX_MIN = 26
CRASH_RSI_MAX = 50

# anti-chase (valores base; algunos se afinan vía parámetros)
BB_EXPANDING_HIGH = 0.50
REQUIRE_RED_PULLBACK = True


def bollinger_bands(stock_price, window_size, num_of_std):
    rolling_mean = stock_price.rolling(window=window_size).mean()
    rolling_std = stock_price.rolling(window=window_size).std()
    lower_band = rolling_mean - (rolling_std * num_of_std)
    return np.nan_to_num(rolling_mean), np.nan_to_num(lower_band)


class CombinedBinHAndCluc_ProHold(IStrategy):
    """
    Versión ProHold:
    - Evita microsalidas (comisión-killer)
    - Deja correr tendencias (ADX/DI + EMA8 slope)
    - Vende en picos/rechazos solo con profit neto decente
    - Stop dinámico controlado (evita que "trailing" te saque en -6% tras haber ido en positivo)
    """

    # ==========================
    # CONFIG BASE
    # ==========================
    stoploss = STOPLOSS_ABS
    timeframe = TIMEFRAME
    startup_candle_count = STARTUP_CANDLES

    minimal_roi = {
        "0": 0.050,
        "60": 0.035,
        "180": 0.020,
        "360": 0.012
    }

    use_exit_signal = False
    exit_profit_only = True
    ignore_roi_if_entry_signal = False
    trailing_stop = False

    MIN_HOLD_BARS = 6  # 30 min en 5m

    # ==========================
    # PARÁMETROS (profesional, sin romper)
    # ==========================
    # Umbral neto mínimo (comisiones + slippage + margen)
    min_profit_net = DecimalParameter(
        0.0040, 0.0200,
        default=(2 * FEE_RATE) + SLIPPAGE_BUFFER + 0.006,
        decimals=4,
        space="sell",
        optimize=False
    )

    # TP duro
    hard_tp = DecimalParameter(0.020, 0.120, default=0.060, decimals=3, space="sell", optimize=False)

    # Umbrales de salida por contexto
    peak_min_profit = DecimalParameter(0.008, 0.060, default=0.020, decimals=3, space="sell", optimize=False)

    # Activación trailing en función de current_profit (esto es lo “parametrizable”)
    profit_trail_start = DecimalParameter(0.010, 0.080, default=0.035, decimals=3, space="sell", optimize=False)

    # Trend definition (strong_trend parametrizado)
    adx_strong_trend = IntParameter(18, 45, default=28, space="sell", optimize=False)
    roc5_strong_min = DecimalParameter(-2.0, 2.0, default=0.0, decimals=2, space="sell", optimize=False)

    # Salida en strong trend solo si hay profit suficiente + señales de fade
    strong_trend_fade_profit = DecimalParameter(0.020, 0.120, default=0.040, decimals=3, space="sell", optimize=False)

    # Trailing dinámico controlado (parámetros clave)
    trail_atr_mult_low = DecimalParameter(1.0, 4.0, default=2.0, decimals=2, space="sell", optimize=False)
    trail_atr_mult_high = DecimalParameter(1.5, 6.0, default=3.0, decimals=2, space="sell", optimize=False)

    trail_dist_min = DecimalParameter(0.008, 0.050, default=0.018, decimals=3, space="sell", optimize=False)
    trail_dist_max = DecimalParameter(0.020, 0.080, default=0.040, decimals=3, space="sell", optimize=False)

    trail_vertical_min = DecimalParameter(0.010, 0.080, default=0.030, decimals=3, space="sell", optimize=False)
    roc5_vertical = DecimalParameter(1.0, 10.0, default=3.8, decimals=2, space="sell", optimize=False)

    fallback_trail_dist = DecimalParameter(0.008, 0.060, default=0.020, decimals=3, space="sell", optimize=False)

    # Anti-chase (para que opere “de verdad” en SOL/XRP/DOGE/ADA sin volverse loco)
    max_pct_up_1 = DecimalParameter(0.2, 2.0, default=0.9, decimals=2, space="buy", optimize=False)
    max_pct_up_3 = DecimalParameter(0.5, 6.0, default=2.5, decimals=2, space="buy", optimize=False)
    max_green_streak = IntParameter(1, 6, default=3, space="buy", optimize=False)

    buy_below_ema20_mult = DecimalParameter(0.990, 1.005, default=0.999, decimals=3, space="buy", optimize=False)
    buy_below_bb_mid_mult = DecimalParameter(0.990, 1.005, default=0.999, decimals=3, space="buy", optimize=False)

    pump_vol_mult = DecimalParameter(1.2, 4.0, default=2.6, decimals=2, space="buy", optimize=False)
    near_hh_distance = DecimalParameter(0.002, 0.050, default=0.010, decimals=3, space="buy", optimize=False)

    # No-buy-high RSI threshold (si subes, bloquea menos)
    no_buy_rsi_min = IntParameter(45, 75, default=60, space="buy", optimize=False)

    # ==========================
    # INDICADORES
    # ==========================
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
        dataframe['green_streak'] = dataframe['green'].rolling(window=self.max_green_streak.value, min_periods=1).sum()
        dataframe['vol_mean_fast'] = dataframe['volume'].rolling(window=10).mean()
        dataframe['pump_vol'] = dataframe['volume'] > (dataframe['vol_mean_fast'] * self.pump_vol_mult.value)
        dataframe['near_hh'] = dataframe['close'] >= (dataframe['hh_20'] * (1.0 - float(self.near_hh_distance.value)))

        # tendencia/hold helpers
        dataframe['trend_ok'] = (dataframe['adx'] > 22) & (dataframe['plus_di'] > dataframe['minus_di']) & dataframe['ema8_slope_up']
        dataframe['trend_strong'] = (
            (dataframe['adx'] >= self.adx_strong_trend.value) &
            (dataframe['plus_di'] > dataframe['minus_di']) &
            dataframe['ema8_slope_up']
        )

        return dataframe

    # ==========================
    # COMPRAS
    # ==========================
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
            (dataframe['rsi'] > self.no_buy_rsi_min.value)
        )

        deep_bb = (dataframe['bb_percent'] <= DEEP_BB)
        bb_zone_ok = (dataframe['bb_percent'] <= BB_ZONE_OK)

        lower_wick = dataframe['lower_wick']
        body = (dataframe['close'] - dataframe['open']).abs()
        hammerish = lower_wick > LOWER_WICK_BODY_RATIO * body

        anti_chase = (
            (dataframe['pct_1'] < float(self.max_pct_up_1.value)) &
            (dataframe['pct_3'] < float(self.max_pct_up_3.value)) &
            (dataframe['green_streak'] < self.max_green_streak.value) &
            (~((dataframe['bb_percent'] >= BB_EXPANDING_HIGH) & (dataframe['bb_expanding']))) &
            (~(dataframe['pump_vol'] & (dataframe['pct_1'] > 0.6))) &
            (dataframe['close'] <= dataframe['ema_fast'] * float(self.buy_below_ema20_mult.value)) &
            (dataframe['close'] <= dataframe['bb_middleband'] * float(self.buy_below_bb_mid_mult.value)) &
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

        dataframe.loc[
            (((A | B | C | D | E | F) & anti_cuchillo & ~no_buy_high & anti_chase) | D),
            'buy'
        ] = 1

        return dataframe

    # ==========================
    # REQUIRED por Freqtrade (aunque use_exit_signal=False)
    # ==========================
    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Estrategia gestiona salidas con custom_exit(), así que no generamos sell signals.
        dataframe['sell'] = 0
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Compatibilidad con versiones que exigen populate_exit_trend.
        if 'exit_long' not in dataframe.columns:
            dataframe['exit_long'] = 0
        else:
            dataframe['exit_long'] = 0
        return dataframe

    # ==========================
    # UTIL
    # ==========================
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

    # ==========================
    # EXIT (inteligente)
    # ==========================
    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs
    ) -> Optional[str]:

        # crash guard: sal si ya hay profit neto o estás plano
        if self._crash_incoming(pair):
            if (current_profit is None) or (current_profit >= 0.0):
                return "crash_guard"

        if current_profit is None:
            return None

        bars = self._bars_elapsed(trade, current_time)

        # NO salgas por debajo del neto mínimo
        if current_profit < float(self.min_profit_net.value):
            return None

        # mínimo de tiempo en trade
        if bars < self.MIN_HOLD_BARS:
            return None

        # TP duro
        if current_profit >= float(self.hard_tp.value):
            return "hard_tp"

        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last = df.iloc[-1]
            prev = df.iloc[-2]

            trend_ok = bool(last.get('trend_ok', False))

            # strong_trend parametrizado (ADX + DI + slope + ROC)
            adx = float(last['adx'])
            roc5 = float(last['roc5'])
            strong_trend = (
                (adx >= float(self.adx_strong_trend.value)) and
                (float(last['plus_di']) > float(last['minus_di'])) and
                bool(last['ema8_slope_up']) and
                (roc5 >= float(self.roc5_strong_min.value))
            )

            near_upper = (last['close'] >= last['bb_upperband'] * 0.999) or (last['high'] >= last['bb_upperband'])
            loc_peak = bool(last['loc_peak'])
            bear_candle = (last['close'] < last['open'])
            macd_fade = (last['macdhist'] < prev['macdhist'])
            ema_break = (last['close'] < last['ema8'])

            upper_wick = float(last['high'] - max(last['open'], last['close']))
            body = float(abs(last['close'] - last['open']))

            # 1) Si hay strong trend: deja correr; vende sólo si fade + profit suficiente
            if strong_trend:
                if (current_profit >= float(self.strong_trend_fade_profit.value)) and ema_break and macd_fade:
                    return "trend_strong_fade_exit"
                return None

            # 2) Pico óptimo con profit decente
            if (
                current_profit >= float(self.peak_min_profit.value) and
                near_upper and loc_peak and
                (float(last['rsi']) >= SELL_RSI_PEAK) and
                (bear_candle or macd_fade or ema_break)
            ):
                return "peak_exit"

            # 3) Rechazo por mecha grande en zona alta
            if (
                near_upper and
                (upper_wick >= float(last['atr']) * REJECT_UPPER_ATR_MULT) and
                (upper_wick > REJECT_WICK_BODY_RATIO * body) and
                (float(last['rsi']) >= SELL_RSI_WICK)
            ):
                if trend_ok and current_profit < 0.020:
                    return None
                return "upper_wick_reject_exit"

            # 4) No tendencia: salida por pérdida de momentum tras subir
            if current_profit >= 0.018 and (float(last['rsi']) < float(last['rsi_prev'])) and macd_fade and ema_break:
                return "momentum_fade_exit"

        except Exception:
            pass

        return None

    # ==========================
    # STOPLOSS dinámico (controlado)
    # ==========================
    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs
    ) -> float:

        # Antes del umbral (parametrizado por profit): stop fijo amplio
        if current_profit is None or current_profit < float(self.profit_trail_start.value):
            return self.stoploss

        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last = df.iloc[-1]
            atr = float(last['atr'])
            adx = float(last['adx'])
            roc5 = float(last['roc5'])
        except Exception:
            return stoploss_from_open(current_profit, float(self.fallback_trail_dist.value))

        strong_trend = (adx >= float(self.adx_strong_trend.value) and roc5 >= float(self.roc5_strong_min.value))
        vertical_rally = (roc5 >= float(self.roc5_vertical.value))

        k = float(self.trail_atr_mult_high.value) if current_profit > 0.08 else float(self.trail_atr_mult_low.value)
        dist = (k * atr) / max(current_rate, 1e-9)

        dist = min(float(self.trail_dist_max.value), max(float(self.trail_dist_min.value), dist))

        if vertical_rally:
            dist = max(dist, float(self.trail_vertical_min.value))
        elif not strong_trend:
            # Clave: evita que el trailing “permita” caídas enormes en mercados chop
            dist = min(dist, 0.022)

        return stoploss_from_open(current_profit, dist)
