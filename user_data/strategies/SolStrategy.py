import freqtrade.vendor.qtpylib.indicators as qtpylib
import numpy as np
import talib.abstract as ta

from freqtrade.strategy.interface import IStrategy
from freqtrade.strategy import informative, merge_informative_pair
from freqtrade.strategy import stoploss_from_open
from pandas import DataFrame
from datetime import datetime
from typing import Optional
from freqtrade.persistence import Trade


# ==========================
# ✅ SOL v1 - Optimizada para SOL/USDT (5m timing + 1h regime)
# Objetivo: NO predecir, sino operar con ventaja estadística:
# - Entrar en pullbacks dentro de tendencia o rebotes con estructura
# - Evitar perseguir spikes
# - Dejar correr con trailing adaptativo
# ==========================

# ---- Costes / mínima ganancia neta ----
FEE_RATE = 0.001
SLIPPAGE_BUFFER = 0.0007
MIN_PROFIT_NET = 7 * FEE_RATE + SLIPPAGE_BUFFER

# ---- Targets / exits ----
HARD_TP = 0.060                 # SOL suele dar tramos; 6% es razonable en 5m cuando se alinea 1h
PEAK_MIN_PROFIT = 0.018         # pico “premium”
HH_EMA_MIN_PROFIT = 0.022       # HH + ruptura EMA8

# ---- Stoploss base ----
STOPLOSS_ABS = -0.055           # algo de aire, pero no suicida

# ---- Filtros anti-cuchillo / anti-chase ----
PCT1_MIN = -2.2
PCT3_MIN = -5.2
COOLDOWN_BARS = 3

MAX_PCT_UP_1 = 0.55
MAX_PCT_UP_3 = 1.40
MAX_GREEN_STREAK = 3
PUMP_VOL_MULT = 2.0
NEAR_HH_DISTANCE = 0.030
REQUIRE_RED_PULLBACK = True

# ---- “Value zone” ----
BB20_WINDOW = 20
BB20_STDS = 2.2

DEEP_BB = 0.18
BB_ZONE_OK = 0.33
LOWER_WICK_BODY_RATIO = 1.20

# ---- Trend filters (5m + 1h) ----
ADX_MIN_5M = 14                # no operar mercados muertos
ADX_STRONG_TREND_1H = 22        # si 1h fuerte, preferimos pullbacks
EMA_TREND_SLOPE = True

# ---- Pullback rules (SOL friendly) ----
E_RSI_MIN = 54
PULLBACK_MAX_DISTANCE_EMA20 = 0.020     # si está demasiado por encima de EMA20 en 5m, no compras
BUY_BELOW_BB_MID_MULT = 0.999
BUY_BELOW_EMA20_MULT = 0.999

# ---- Trailing dinámico ----
TRAIL_ATR_MULT_LOW = 2.6
TRAIL_ATR_MULT_HIGH = 3.7
TRAIL_DIST_MIN = 0.020
TRAIL_DIST_MAX = 0.075
FALLBACK_TRAIL_DIST = 0.028
ROC5_VERTICAL = 3.2
TRAIL_VERTICAL_MIN = 0.032

# ---- Crash guard ----
CRASH_FAST_DROP_EMA20 = 0.990
CRASH_FAST_DROP_PCT1 = -0.9
CRASH_ATR_BREAK_MULT = 1.65
CRASH_ADX_MIN = 24
CRASH_RSI_MAX = 48


def bb_percent(df: DataFrame) -> DataFrame:
    tp = qtpylib.typical_price(df)
    bb = qtpylib.bollinger_bands(tp, window=BB20_WINDOW, stds=BB20_STDS)
    df["bb_lowerband"] = bb["lower"]
    df["bb_middleband"] = bb["mid"]
    df["bb_upperband"] = bb["upper"]
    denom = (df["bb_upperband"] - df["bb_lowerband"]).replace(0, np.nan)
    df["bb_width"] = (df["bb_upperband"] - df["bb_lowerband"]) / df["bb_middleband"]
    df["bb_percent"] = (df["close"] - df["bb_lowerband"]) / denom
    df["bb_expanding"] = df["bb_width"] > df["bb_width"].shift(1)
    return df


class MyStrategy(IStrategy):
    """
    SOL v1 (5m + 1h):
    - 1h: determina régimen (tendencia / bajista / rango)
    - 5m: timing con pullback + confirmación
    - Exits: premium peaks + trailing ATR
    """

    timeframe = "5m"
    startup_candle_count = 220
    stoploss = STOPLOSS_ABS

    # dejamos custom_exit/custom_stoploss mandar, así que ROI “infinito”
    minimal_roi = {"0": 10.0}
    use_sell_signal = True
    sell_profit_only = True
    ignore_roi_if_buy_signal = True
    trailing_stop = False

    MIN_HOLD_BARS = 3

    def informative_pairs(self):
        # SOLO tiene sentido si tu whitelist incluye SOL/USDT
        # Aun así, para Freqtrade hace falta indicar el par informativo:
        return [(pair, "1h") for pair in self.dp.current_whitelist()] if self.dp else []

    @informative("1h")
    def populate_indicators_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema50_1h"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema200_1h"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["adx_1h"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["rsi_1h"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["roc_1h"] = ta.ROC(dataframe, timeperiod=9)
        dataframe["ema50_slope_1h"] = dataframe["ema50_1h"] > dataframe["ema50_1h"].shift(1)
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # ---- Base 5m ----
        dataframe["ema8"] = ta.EMA(dataframe, timeperiod=8)
        dataframe["ema20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)

        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["rsi_prev"] = dataframe["rsi"].shift(1)

        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["plus_di"] = ta.PLUS_DI(dataframe, timeperiod=14)
        dataframe["minus_di"] = ta.MINUS_DI(dataframe, timeperiod=14)

        macd = ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)
        dataframe["macd"] = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]
        dataframe["macdhist"] = macd["macdhist"]

        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["roc5"] = ta.ROC(dataframe, timeperiod=5)

        dataframe["pct_1"] = dataframe["close"].pct_change(1) * 100.0
        dataframe["pct_3"] = dataframe["close"].pct_change(3) * 100.0

        dataframe["hh_20"] = dataframe["high"].rolling(20).max()
        dataframe["ll_10"] = dataframe["low"].rolling(10).min()

        # wicks
        dataframe["upper_wick"] = (dataframe["high"] - np.maximum(dataframe["open"], dataframe["close"])).abs()
        dataframe["lower_wick"] = (np.minimum(dataframe["open"], dataframe["close"]) - dataframe["low"]).abs()
        body = (dataframe["close"] - dataframe["open"]).abs()
        dataframe["hammerish"] = dataframe["lower_wick"] > (LOWER_WICK_BODY_RATIO * body)

        # BB
        dataframe = bb_percent(dataframe)

        # volumen
        dataframe["vol_mean_fast"] = dataframe["volume"].rolling(10).mean()
        dataframe["vol_mean_slow"] = dataframe["volume"].rolling(30).mean()
        dataframe["pump_vol"] = dataframe["volume"] > (dataframe["vol_mean_fast"] * PUMP_VOL_MULT)

        # cooldown por vela roja grande (SOL hace dumps fuertes)
        big_red = (dataframe["close"] < dataframe["open"]) & (body > 1.2 * dataframe["atr"])
        dataframe["cooldown"] = big_red.rolling(COOLDOWN_BARS).max().astype(bool)

        # máximos/mínimos locales (microestructura)
        dataframe["loc_peak"] = (
            (dataframe["high"] >= dataframe["high"].rolling(6).max()) &
            (dataframe["high"] >= dataframe["high"].shift(1)) &
            (dataframe["high"] >= dataframe["high"].shift(2))
        )
        dataframe["loc_trough"] = (
            (dataframe["low"] <= dataframe["low"].rolling(6).min()) &
            (dataframe["low"] <= dataframe["low"].shift(1)) &
            (dataframe["low"] <= dataframe["low"].shift(2))
        )

        # anti-chase helpers
        dataframe["green"] = dataframe["close"] > dataframe["open"]
        dataframe["green_streak"] = dataframe["green"].rolling(MAX_GREEN_STREAK, min_periods=1).sum()
        dataframe["near_hh"] = dataframe["close"] >= (dataframe["hh_20"] * (1.0 - NEAR_HH_DISTANCE))

        # ---- Merge 1h informative ----
        if self.dp:
            inf = self.dp.get_pair_dataframe(pair=metadata["pair"], timeframe="1h")
            inf = self.populate_indicators_1h(inf, metadata)
            dataframe = merge_informative_pair(dataframe, inf, self.timeframe, "1h", ffill=True)

        return dataframe

    # ==========================
    # ENTRIES (SOL)
    # ==========================
    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # 1h regime: evita comprar en bajista fuerte
        # - Si precio < ema200_1h y ema50_1h cayendo y ADX fuerte => NO LONG
        bear_regime = (
            (dataframe["close_1h"] < dataframe["ema200_1h"]) &
            (~dataframe["ema50_slope_1h"]) &
            (dataframe["adx_1h"] >= ADX_STRONG_TREND_1H)
        )

        # 5m anti-knife
        anti_cuchillo = (
            (dataframe["pct_1"] > PCT1_MIN) &
            (dataframe["pct_3"] > PCT3_MIN) &
            (~dataframe["cooldown"]) &
            (dataframe["volume"] > 0) &
            (dataframe["adx"] >= ADX_MIN_5M)
        )

        # anti-chase (no perseguir spikes)
        anti_chase = (
            (dataframe["pct_1"] < MAX_PCT_UP_1) &
            (dataframe["pct_3"] < MAX_PCT_UP_3) &
            (dataframe["green_streak"] < MAX_GREEN_STREAK) &
            (~(dataframe["pump_vol"] & (dataframe["pct_1"] > 0.6))) &
            (dataframe["close"] <= dataframe["ema20"] * BUY_BELOW_EMA20_MULT) &
            (dataframe["close"] <= dataframe["bb_middleband"] * BUY_BELOW_BB_MID_MULT) &
            (~dataframe["near_hh"])
        )
        if REQUIRE_RED_PULLBACK:
            anti_chase = anti_chase & (
                (dataframe["close"] <= dataframe["open"]) |
                (dataframe["low"] < dataframe["close"].shift(1))
            )

        deep_value = (dataframe["bb_percent"] <= DEEP_BB)
        zone_low = (dataframe["bb_percent"] <= BB_ZONE_OK)

        # Entrada 1: Pullback “limpio” en tendencia 1h (mejor para SOL)
        pullback_trend = (
            (~bear_regime) &
            (dataframe["close_1h"] >= dataframe["ema50_1h"]) &
            (dataframe["ema50_slope_1h"]) &
            # timing 5m
            (dataframe["close"] <= dataframe["ema20"] * (1.0 + PULLBACK_MAX_DISTANCE_EMA20)) &
            (dataframe["close"] >= dataframe["ema8"]) &
            (dataframe["rsi"] >= E_RSI_MIN) &
            (dataframe["rsi"] > dataframe["rsi_prev"]) &
            (dataframe["macdhist"] >= dataframe["macdhist"].shift(1)) &
            (zone_low | (dataframe["hammerish"]))
        )

        # Entrada 2: Reversal profundo (solo si no es bear fuerte 1h)
        deep_reversal = (
            (~bear_regime) &
            (deep_value | dataframe["loc_trough"]) &
            (dataframe["rsi_prev"] < 48) &
            (dataframe["rsi"] > dataframe["rsi_prev"]) &
            (dataframe["close"] >= dataframe["open"]) &
            (dataframe["hammerish"] | (dataframe["volume"] > dataframe["vol_mean_slow"] * 1.2)) &
            (dataframe["macdhist"] >= dataframe["macdhist"].shift(1))
        )

        dataframe.loc[
            (anti_cuchillo & anti_chase & (pullback_trend | deep_reversal)),
            "buy",
        ] = 1

        return dataframe

    # ==========================
    # SELL signals (solo señales; el exit “real” va en custom_exit)
    # ==========================
    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        reject_upper = (
            (dataframe["upper_wick"] >= dataframe["atr"] * 1.05) &
            (dataframe["upper_wick"] > (dataframe["close"] - dataframe["open"]).abs() * 1.30) &
            ((dataframe["high"] >= dataframe["bb_upperband"] * 0.999) | (dataframe["close"] >= dataframe["bb_upperband"])) &
            (dataframe["rsi"] >= 68)
        )

        peak_exit = (
            (dataframe["loc_peak"]) &
            (dataframe["close"] >= dataframe["bb_upperband"] * 0.999) &
            (dataframe["rsi"] >= 74) &
            ((dataframe["macdhist"] < dataframe["macdhist"].shift(1)) | (dataframe["close"] < dataframe["ema8"]))
        )

        dataframe.loc[(reject_upper | peak_exit), "sell"] = 1
        return dataframe

    # ==========================
    # Helpers
    # ==========================
    def _bars_elapsed(self, trade: Trade, current_time: datetime) -> int:
        tf_minutes = int(self.timeframe.rstrip("m"))
        seconds = (current_time - trade.open_date_utc).total_seconds()
        return int(max(0, seconds) // (tf_minutes * 60))

    def _crash_incoming(self, pair: str) -> bool:
        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last = df.iloc[-1]
            prev = df.iloc[-2]
            fast_drop = (last["close"] <= last["ema20"] * CRASH_FAST_DROP_EMA20) and (last["pct_1"] <= CRASH_FAST_DROP_PCT1)
            atr_break = (last["low"] < last["ema20"] - CRASH_ATR_BREAK_MULT * last["atr"])
            bb_flush = (last["bb_percent"] < 0) and bool(last["bb_expanding"]) and (last["macdhist"] < prev["macdhist"])
            di_shift = (last["adx"] > CRASH_ADX_MIN) and (last["minus_di"] > last["plus_di"]) and (last["rsi"] < CRASH_RSI_MAX)
            return sum([fast_drop, atr_break, bb_flush or di_shift]) >= 2
        except Exception:
            return False

    # ==========================
    # Custom Exit (donde se “gana dinero” de verdad)
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

        # Crash guard: si hay señales de flush y hay profit neto, sales.
        if self._crash_incoming(pair):
            if (current_profit is not None) and (current_profit > MIN_PROFIT_NET):
                return "crash_guard"

        bars = self._bars_elapsed(trade, current_time)
        if bars < self.MIN_HOLD_BARS:
            return None

        # Hard TP: si hay tramo fuerte, lo coges
        if current_profit is not None and current_profit >= HARD_TP:
            return "hard_tp"

        # Exige beneficio neto mínimo para cualquier salida “normal”
        if current_profit is None or current_profit < MIN_PROFIT_NET:
            return None

        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last = df.iloc[-1]
            prev = df.iloc[-2]

            near_upper = (last["close"] >= last["bb_upperband"] * 0.999) or (last["high"] >= last["bb_upperband"])
            loc_peak = bool(last["loc_peak"]) if "loc_peak" in last else bool(last["high"] >= df["high"].rolling(6).max().iloc[-1])

            rsi_high = last["rsi"] >= 74
            bear_candle = last["close"] < last["open"]
            macd_fade = last["macdhist"] < prev["macdhist"]
            ema_break = last["close"] < last["ema8"]

            # Pico premium: banda alta + máximo local + giro
            if current_profit >= PEAK_MIN_PROFIT and near_upper and loc_peak and rsi_high and (bear_candle or macd_fade or ema_break):
                return "peak_exit"

            # HH + ruptura EMA8 + MACD debilitando
            if current_profit >= HH_EMA_MIN_PROFIT:
                hh_prev = prev["high"] >= df["high"].rolling(20).max().iloc[-2]
                if hh_prev and ema_break and macd_fade and (last["rsi"] >= 68):
                    return "hh_ema8_break"

            # Rechazo por mecha grande arriba (SOL hace esto mucho)
            upper_wick = float(last["high"] - max(last["open"], last["close"]))
            body = float(abs(last["close"] - last["open"]))
            if near_upper and (upper_wick >= last["atr"] * 1.05) and (upper_wick > 1.30 * body) and (last["rsi"] >= 68):
                return "upper_wick_reject"

            # Agotamiento: pierde momentum y rompe EMA8 tras tramo
            if current_profit >= (MIN_PROFIT_NET + 0.003) and bars >= 6:
                if (last["rsi"] < last["rsi_prev"]) and macd_fade and ema_break:
                    return "momentum_fade"

        except Exception:
            pass

        return None

    # ==========================
    # Custom Stoploss (Trailing ATR adaptativo)
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

        # Antes de +3% no trailing: deja respirar
        if current_profit is None or current_profit < 0.03:
            return self.stoploss

        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last = df.iloc[-1]
            atr = float(last["atr"])
            adx = float(last["adx"])
            roc5 = float(last["roc5"])
        except Exception:
            return stoploss_from_open(current_profit, FALLBACK_TRAIL_DIST)

        strong = (adx >= 26 and roc5 > 0)
        vertical = (roc5 >= ROC5_VERTICAL)

        k = TRAIL_ATR_MULT_HIGH if current_profit > 0.06 else TRAIL_ATR_MULT_LOW
        dist = (k * atr) / max(current_rate, 1e-9)
        dist = min(TRAIL_DIST_MAX, max(TRAIL_DIST_MIN, dist))

        if vertical:
            dist = max(dist, TRAIL_VERTICAL_MIN)
        elif not strong:
            dist = min(dist, 0.020)

        # Ajuste suave en el tramo medio para no dar profit back
        if 0.03 <= current_profit < 0.06:
            return stoploss_from_open(current_profit, max(0.018, dist))

        return stoploss_from_open(current_profit, dist)