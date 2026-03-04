"""
TrendFollowing15m v2 — Trend-following a 15m con períodos escalados

El error de la v1 era usar EMA50/EMA200 que a 15m solo representan 12h/50h — demasiado
cortos, causando miles de señales falsas. V2 usa períodos escalados para representar
tendencias reales en días:

- EMA96  (96×15m  = 24h = 1 día) — "short" trend
- EMA384 (384×15m = 96h = 4 días) — "long" trend
- ADX(56) (56×15m = 14h) — fuerza de tendencia con suficiente lookback

Para entrar: la tendencia de 1 día está por encima de la de 4 días (uptrend real),
el precio está por encima de la EMA diaria, y el momentum (MACD + ADX) confirma.

El trailing stop es más amplio (10% offset, 5% activo) para aguantar pullbacks normales
sin salir prematuramente.
"""

import talib.abstract as ta
import numpy as np
from pandas import DataFrame
from freqtrade.strategy import IStrategy, IntParameter


class TrendFollowing15m(IStrategy):

    INTERFACE_VERSION = 3
    timeframe = "15m"
    startup_candle_count = 500  # EMA384 necesita 384+ velas

    stoploss = -0.10  # 10% SL — más espacio para tendencias reales
    trailing_stop = True
    trailing_stop_positive = 0.05       # activa trailing cuando ganancia > 5%
    trailing_stop_positive_offset = 0.10  # trailing comienza al +10%
    trailing_only_offset_is_reached = True

    minimal_roi = {"0": 0.999}

    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = True
    process_only_new_candles = True

    # ── Hyperopt parameters ─────────────────────────────────────────────────
    buy_adx_min  = IntParameter(20, 40, default=28,   space="buy", optimize=True)
    buy_rsi_min  = IntParameter(40, 55, default=48,   space="buy", optimize=True)
    buy_rsi_max  = IntParameter(60, 75, default=68,   space="buy", optimize=True)
    sell_rsi_max = IntParameter(72, 85, default=78,   space="sell", optimize=True)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:

        # ── Tendencia (períodos escalados para representar días) ──────────
        # EMA96  = 96 × 15m = 24h ≈ 1 día
        # EMA384 = 384 × 15m = 96h ≈ 4 días
        dataframe["ema_1d"]  = ta.EMA(dataframe, timeperiod=96)
        dataframe["ema_4d"]  = ta.EMA(dataframe, timeperiod=384)

        # ADX con lookback largo (56 × 15m = 14h)
        dataframe["adx"]     = ta.ADX(dataframe, timeperiod=56)

        # ── Momentum ──────────────────────────────────────────────────────
        macd = ta.MACD(dataframe, fastperiod=24, slowperiod=52, signalperiod=18)
        dataframe["macd"]        = macd["macd"]
        dataframe["macdsignal"]  = macd["macdsignal"]
        dataframe["macdhist"]    = macd["macdhist"]

        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)

        # ── Volumen (media de 50 velas para mayor estabilidad) ────────────
        dataframe["vol_ma50"] = dataframe["volume"].rolling(50).mean()

        # ── ATR para referencia de volatilidad ────────────────────────────
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:

        conditions = [
            # Tendencia: EMA de 1 día sobre EMA de 4 días → uptrend real
            dataframe["ema_1d"]  > dataframe["ema_4d"],
            # Precio por encima de la EMA de 1 día (no rezagado)
            dataframe["close"]   > dataframe["ema_1d"],
            # ADX confirma que hay tendencia (no lateral)
            dataframe["adx"]     > self.buy_adx_min.value,
            # MACD muestra momentum alcista
            dataframe["macd"]    > dataframe["macdsignal"],
            dataframe["macd"]    > 0,
            # RSI en zona neutra-alcista (no sobrecomprado ni sobrevendido extremo)
            dataframe["rsi"]     > self.buy_rsi_min.value,
            dataframe["rsi"]     < self.buy_rsi_max.value,
            # Volumen por encima de la media (confirmación)
            dataframe["volume"]  > dataframe["vol_ma50"] * 1.3,
            dataframe["volume"]  > 0,
        ]

        dataframe.loc[
            np.all(conditions, axis=0),
            "enter_long",
        ] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:

        conditions = [
            (
                # Pérdida de tendencia estructural (EMA 1d cruza por debajo de 4d)
                (dataframe["ema_1d"] < dataframe["ema_4d"])
                # O momentum se invierte con fuerza
                | (
                    (dataframe["macd"] < dataframe["macdsignal"])
                    & (dataframe["macdhist"] < dataframe["macdhist"].shift(2))  # decelerando
                )
                # O RSI en sobrecompra extrema
                | (dataframe["rsi"] > self.sell_rsi_max.value)
            ),
            dataframe["volume"] > 0,
        ]

        dataframe.loc[
            np.all(conditions, axis=0),
            "exit_long",
        ] = 1

        return dataframe
