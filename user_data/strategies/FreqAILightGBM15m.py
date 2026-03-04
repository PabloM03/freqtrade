"""
FreqAILightGBM15m v2 — ML con LightGBM Regressor + filtros de calidad

Mejoras sobre v1:
- Target más largo: 96 velas (24h) en lugar de 32 (8h) → más señal, menos ruido
- Entry threshold más alto: 2.5% por defecto → solo entradas de alta convicción
- Filtro de tendencia triple (ema50_ok) → bloquea entradas en downtrend
- HARD_TP = 0.50 → deja correr movimientos grandes (BONK, WIF, etc.)
- Solo pares con historial largo: BTC, ETH, SOL (más datos = mejor entrenamiento)

Walk-forward real:
- train_period_days=90, backtest_period_days=30 → cero look-ahead bias

Para backtesting (usar config.freqai_v2.json):
  freqtrade backtesting -c config.json -c config.backtest.freqai.json -c config.freqai.json
    -s FreqAILightGBM15m --timerange 20240101-20241231 --cache none
"""

import logging
import talib.abstract as ta
import numpy as np
from pandas import DataFrame
from freqtrade.strategy import IStrategy, DecimalParameter

logger = logging.getLogger(__name__)


class FreqAILightGBM15m(IStrategy):

    INTERFACE_VERSION = 3
    timeframe = "15m"
    startup_candle_count = 300

    stoploss = -0.06
    trailing_stop = False
    minimal_roi = {"0": 0.999}

    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = True
    process_only_new_candles = True

    # TP duro para dejar correr grandes movimientos
    HARD_TP = 0.50

    # Umbral de predicción — más alto = menos trades pero más calidad
    entry_threshold = DecimalParameter(1.5, 4.0, default=2.5, decimals=1, space="buy", optimize=True)
    exit_threshold  = DecimalParameter(-4.0, -1.0, default=-1.5, decimals=1, space="sell", optimize=True)

    # Filtro de tendencia (ema50_ok)
    buy_ema50_close_pct = DecimalParameter(0.920, 0.998, default=0.970, decimals=3, space="buy", optimize=True)
    buy_ema50_slope     = DecimalParameter(0.960, 0.998, default=0.985, decimals=3, space="buy", optimize=True)

    def feature_engineering_expand_all(
        self, dataframe: DataFrame, period: int, metadata: dict, **kwargs
    ) -> DataFrame:
        """
        Features por cada período en indicator_periods_candles [10, 20, 40].
        Naming literal "period" — FreqAI renombra internamente.
        """
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
        """Features por cada timeframe incluido."""
        dataframe["%-pct_1"]     = dataframe["close"].pct_change(1)
        dataframe["%-pct_4"]     = dataframe["close"].pct_change(4)
        dataframe["%-pct_16"]    = dataframe["close"].pct_change(16)
        dataframe["%-pct_32"]    = dataframe["close"].pct_change(32)
        dataframe["%-vol_ratio"] = dataframe["volume"] / (dataframe["volume"].rolling(20).mean() + 1e-8)
        dataframe["%-vol_ratio_4"] = dataframe["volume"] / (dataframe["volume"].rolling(4).mean() + 1e-8)
        dataframe["%-raw_price"]  = dataframe["close"]
        dataframe["%-raw_volume"] = dataframe["volume"]

        return dataframe

    def feature_engineering_standard(
        self, dataframe: DataFrame, metadata: dict, **kwargs
    ) -> DataFrame:
        """Features globales + TARGET."""
        ema200 = ta.EMA(dataframe, timeperiod=200)
        ema80  = ta.EMA(dataframe, timeperiod=80)
        ema50  = ta.EMA(dataframe, timeperiod=50)
        dataframe["%-close_ema200"] = dataframe["close"] / (ema200 + 1e-8)
        dataframe["%-close_ema80"]  = dataframe["close"] / (ema80 + 1e-8)
        dataframe["%-close_ema50"]  = dataframe["close"] / (ema50 + 1e-8)
        dataframe["%-ema50_ema200"] = ema50 / (ema200 + 1e-8)
        dataframe["%-ema200_slope"] = ema200 / (ema200.shift(96) + 1e-8)
        dataframe["%-ema50_slope"]  = ema50  / (ema50.shift(32) + 1e-8)

        atr = ta.ATR(dataframe, timeperiod=14)
        dataframe["%-atr_ratio"] = atr / (dataframe["close"] + 1e-8)

        stoch = ta.STOCHRSI(dataframe, timeperiod=14, fastk_period=3, fastd_period=3)
        dataframe["%-stoch_k"] = stoch["fastk"]
        dataframe["%-stoch_d"] = stoch["fastd"]

        # TARGET: % de cambio en las próximas 96 velas (24h a 15m) — más señal que 8h
        dataframe["&-s_target"] = (
            dataframe["close"].shift(-96) / dataframe["close"] - 1
        ) * 100

        # Para filtro ema50_ok (no es un feature ML — se usa solo en populate_entry_trend)
        dataframe["ema50_ht"] = ema80   # EMA80@15m = 20h — "ema_fast" equivalente
        dataframe["ema200_ht"] = ema200  # EMA200@15m = 50h — "ema_slow"

        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = self.freqai.start(dataframe, metadata, self)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Filtro de tendencia: EMA200 no bajando en 48h + precio cerca de EMA200
        ema50_ok = (
            (dataframe["ema200_ht"] >= dataframe["ema200_ht"].shift(192) * self.buy_ema50_slope.value) &
            (dataframe["close"] >= dataframe["ema200_ht"] * self.buy_ema50_close_pct.value)
        )

        conditions = [
            dataframe["&-s_target"] > self.entry_threshold.value,
            dataframe["do_predict"] == 1,
            ema50_ok,
            dataframe["volume"] > 0,
        ]
        dataframe.loc[np.all(conditions, axis=0), "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = [
            dataframe["&-s_target"] < self.exit_threshold.value,
            dataframe["do_predict"] == 1,
            dataframe["volume"] > 0,
        ]
        dataframe.loc[np.all(conditions, axis=0), "exit_long"] = 1
        return dataframe

    def custom_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):  # noqa: ARG002
        """Hard TP para dejar correr grandes movimientos."""
        if current_profit is not None and current_profit >= self.HARD_TP:
            return "hard_tp"
        return None
