"""
FreqAIEnhanced15m.py — Estrategia LightGBMClassifier (condición K)

El modelo predice si el precio subirá >= 1.5% en las próximas 48 velas (12h).
Condición K: FreqAI predice subida + RSI < 55 + zona de valor técnica.

Backtest:
    freqtrade backtesting \
      -c config.json -c config.backtest.json \
      -c config.backtest.freqai.json -c config.freqai.json \
      -s FreqAIEnhanced15m --timerange 20240101-20241231 --cache none

Nota: necesita datos 2023 para el primer entrenamiento (train_period_days=90).
"""
import freqtrade.vendor.qtpylib.indicators as qtpylib
import talib.abstract as ta
from freqtrade.strategy import IStrategy, DecimalParameter
from pandas import DataFrame


class FreqAIEnhanced15m(IStrategy):
    """
    Clasificador LightGBM que aprende cuándo el mercado va a subir >= 1.5% en 12h.
    Se usa como condición K: señal additive (no filtro) sobre la estrategia base.
    """

    INTERFACE_VERSION = 3
    timeframe = "15m"
    startup_candle_count = 500
    can_short = False

    # Stoploss amplio — calidad de entrada filtrada por ML, no por SL estrecho
    stoploss = -0.347
    trailing_stop = True
    trailing_stop_positive = 0.03
    trailing_stop_positive_offset = 0.05
    trailing_only_offset_is_reached = True

    # HARD_TP 50% — igual que MyStrategy para comparativa justa
    minimal_roi = {"0": 0.50}

    process_only_new_candles = True
    use_exit_signal = False

    # Zona de valor (threshold BB percent)
    buy_bb_zone_ok = DecimalParameter(0.20, 0.80, default=0.68, space='buy')

    # -------------------------------------------------------------------------
    # FreqAI — Feature Engineering
    # -------------------------------------------------------------------------

    def feature_engineering_expand_all(
        self, dataframe: DataFrame, period: int, metadata: dict, **kwargs
    ) -> DataFrame:
        """
        Features que se expanden para cada período en indicator_periods_candles.
        Con [8, 20, 40] → 3 versiones de cada feature (períodos corto/medio/largo).
        """
        dataframe[f"%-rsi-{period}"] = ta.RSI(dataframe, timeperiod=period)
        dataframe[f"%-adx-{period}"] = ta.ADX(dataframe, timeperiod=period)
        dataframe[f"%-roc-{period}"] = ta.ROC(dataframe, timeperiod=period)
        dataframe[f"%-mfi-{period}"] = ta.MFI(dataframe, timeperiod=period)
        dataframe[f"%-cci-{period}"] = ta.CCI(dataframe, timeperiod=period)

        macd = ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)
        dataframe[f"%-macdhist-{period}"] = macd["macdhist"]

        bb = qtpylib.bollinger_bands(
            qtpylib.typical_price(dataframe), window=period, stds=2
        )
        denom = bb["upper"] - bb["lower"] + 1e-9
        dataframe[f"%-bb_pct-{period}"] = (dataframe["close"] - bb["lower"]) / denom
        dataframe[f"%-bb_width-{period}"] = (bb["upper"] - bb["lower"]) / (bb["mid"] + 1e-9)

        return dataframe

    def feature_engineering_expand_basic(
        self, dataframe: DataFrame, metadata: dict, **kwargs
    ) -> DataFrame:
        """
        Features básicas de precio y volumen (una sola versión, sin expansión por período).
        """
        dataframe["%-pct_1"] = dataframe["close"].pct_change(1) * 100
        dataframe["%-pct_4"] = dataframe["close"].pct_change(4) * 100
        dataframe["%-pct_16"] = dataframe["close"].pct_change(16) * 100
        vol_ma = dataframe["volume"].rolling(20).mean()
        dataframe["%-vol_ratio"] = dataframe["volume"] / (vol_ma + 1e-9)
        dataframe["%-vol_pct"] = dataframe["volume"].pct_change(1)
        return dataframe

    def feature_engineering_standard(
        self, dataframe: DataFrame, metadata: dict, **kwargs
    ) -> DataFrame:
        """
        Solo define el target. Las features estructurales ya están en expand_all/expand_basic.

        Nota: LightGBMClassifier es incompatible con pandas 3.0 en esta versión de
        freqtrade (el check `dtype == object` falla para strings en pandas 3.x, que
        los almacena como dtype='str'). Usamos LightGBMRegressor con target numérico.
        """
        # ---- Target: % de retorno en las próximas 48 velas (12h) ----
        # Regressor predice retorno futuro; entrada cuando predicción > 0.5%
        dataframe["&-s_target"] = (
            dataframe["close"].shift(-48) / dataframe["close"] - 1
        ) * 100

        return dataframe

    # -------------------------------------------------------------------------
    # Indicadores técnicos para los filtros de la condición K
    # -------------------------------------------------------------------------

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        1. Llama a FreqAI para obtener la predicción del clasificador.
        2. Calcula indicadores técnicos usados como filtros de la condición K.
        """
        # --- FreqAI: entrena/carga el modelo y añade columnas de predicción ---
        dataframe = self.freqai.start(dataframe, metadata, self)

        # --- Indicadores técnicos para filtros ---
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["ema80"] = ta.EMA(dataframe, timeperiod=80)
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)

        # BB80 (ventana ×4 para equivalencia 20h en 15m)
        bb80 = qtpylib.bollinger_bands(
            qtpylib.typical_price(dataframe), window=80, stds=2
        )
        dataframe["bb_middleband"] = bb80["mid"]
        dataframe["bb_upperband"] = bb80["upper"]
        dataframe["bb_lowerband"] = bb80["lower"]
        dataframe["bb_percent"] = (
            (dataframe["close"] - bb80["lower"]) / (bb80["upper"] - bb80["lower"] + 1e-9)
        )

        dataframe["vol_ma"] = dataframe["volume"].rolling(20).mean()

        # Pendiente EMA200 — no entrar si el mercado está en caída libre
        dataframe["ema200_slope_48"] = (
            dataframe["ema200"] / (dataframe["ema200"].shift(192) + 1e-9)  # 192 × 15m = 48h
        )

        return dataframe

    # -------------------------------------------------------------------------
    # Entry / Exit
    # -------------------------------------------------------------------------

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Condición K: el regresor predice retorno > 0.5% en 12h + precio en zona de valor.

        Columnas que añade FreqAI (LightGBMRegressor):
          - &-s_target    → retorno predicho (% en 12h)
          - do_predict    → 1 si el modelo tiene confianza, 0 si outlier
        """
        pred_col = "&-s_target"

        if pred_col not in dataframe.columns:
            # FreqAI no configurado o primer startup sin modelo aún
            dataframe["enter_long"] = 0
            return dataframe

        # Filtro de confianza del modelo (do_predict = 1: in-distribution)
        model_confident = (dataframe["do_predict"] == 1)

        # Regresor predice retorno positivo > 0.5% en 12h
        # Threshold bajo (no filtro, señal additive) — umbral mínimo para no entrar en pérdida esperada
        freqai_bullish = (dataframe[pred_col] > 0.5)

        # Filtros técnicos (precio en zona de valor, no overbought, no en caída libre)
        in_value_zone = (dataframe["bb_percent"] <= self.buy_bb_zone_ok.value)
        rsi_ok = (dataframe["rsi"] < 55) & (dataframe["rsi"] > 20)
        trend_ok = (dataframe["ema200_slope_48"] >= 0.986)  # EMA200 no cayendo >1.4% en 48h
        vol_ok = (dataframe["volume"] > dataframe["vol_ma"] * 0.5)
        price_not_extended = (dataframe["close"] < dataframe["bb_upperband"])

        K = (
            model_confident &
            freqai_bullish &
            in_value_zone &
            rsi_ok &
            trend_ok &
            vol_ok &
            price_not_extended
        )

        dataframe.loc[K, "enter_long"] = 1
        dataframe.loc[K, "enter_tag"] = "K_freqai"

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Las salidas las gestiona el trailing stop y minimal_roi."""
        dataframe["exit_long"] = 0
        return dataframe
