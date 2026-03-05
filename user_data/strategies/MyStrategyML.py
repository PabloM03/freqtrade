"""
MyStrategyML — MyStrategy v4 + FreqAI Binary Classifier
=========================================================
Hereda TODA la lógica de MyStrategy (A-I conditions, F&G, ema50_ok, exits).
Añade un clasificador LightGBM que predice: ¿subirá ≥3% en 6h?

ARQUITECTURA ML:
  - Label: close.shift(-96) / close >= 1.03  →  binario 0/1
  - Features: RSI, MACD, BB, EMA, ATR, StochRSI + correlación BTC
  - Señales FUERTES (D, H, I): ignoran ML → siempre entran en pánico/capitulación
  - Señales DÉBILES (A,B,C,E,F,G): requieren ML prob > 0.55 O precio en zona ultra-oversold

FIX DEL FALLO ANTERIOR (MyStrategyHybrid):
  - Usaba regresor → predicía siempre ~0% (aprende la media)
  - Ahora: clasificador binario → aprende patrones de subida real
  - train_period_days=60 (no 90) → meme coins participan antes
  - Pares sin historial ML: sus señales fuertes siguen activas
"""

import numpy as np
import pandas as pd
from pandas import DataFrame
from freqtrade.strategy import DecimalParameter

from CombinedBinHAndCluc import MyStrategy


class MyStrategyML(MyStrategy):
    """
    MyStrategy + FreqAI LightGBM Classifier como booster (no filtro duro).
    """

    # FreqAI required
    use_custom_stoploss = False  # heredado de MyStrategy

    # Umbral de confianza ML para señales débiles (optimizable)
    buy_ml_min_conf  = DecimalParameter(0.50, 0.70, default=0.55, decimals=2, space='buy', optimize=True)

    def feature_engineering_expand_all(self, dataframe: DataFrame, period: int,
                                        metadata: dict, **kwargs) -> DataFrame:
        """Features adicionales al set base que FreqAI genera automáticamente."""
        dataframe[f"%-rsi-period_{period}"] = dataframe["rsi"]
        dataframe[f"%-macd-hist-period_{period}"] = dataframe["macdhist"]
        dataframe[f"%-bb-percent-period_{period}"] = dataframe["bb_percent"]
        dataframe[f"%-atr-period_{period}"] = dataframe["atr"] / dataframe["close"]
        dataframe[f"%-stoch-k-period_{period}"] = dataframe["stoch_k"]
        dataframe[f"%-adx-period_{period}"] = dataframe["adx"]
        dataframe[f"%-vol-spike-period_{period}"] = dataframe["vol_spike"].astype(float)
        dataframe[f"%-fear-greed-period_{period}"] = dataframe["fear_greed"]
        return dataframe

    def feature_engineering_standard(self, dataframe: DataFrame,
                                      metadata: dict, **kwargs) -> DataFrame:
        """Features estándar (sin período variable)."""
        dataframe["%-day-of-week"] = dataframe["date"].dt.dayofweek
        dataframe["%-hour-of-day"]  = dataframe["date"].dt.hour
        dataframe["%-ema50-slope"]  = (
            dataframe["ema_slow"] / dataframe["ema_slow"].shift(96) - 1
        )
        dataframe["%-close-over-ema200"] = dataframe["close"] / dataframe["ema_slow"]
        return dataframe

    def set_freqai_targets(self, dataframe: DataFrame, metadata: dict, **kwargs) -> DataFrame:
        """
        Etiqueta binaria: ¿subirá ≥3% en las próximas 6h (96 candles × 15m)?
        1 = sube ≥3%, 0 = no sube
        """
        future_close = dataframe["close"].shift(-96)
        dataframe["&s_up_label"] = (future_close / dataframe["close"] >= 1.03).astype(int)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Llama a la lógica base (A-I conditions + F&G + ema50_ok),
        luego aplica filtro ML a las señales débiles.
        """
        # Ejecutar toda la lógica de MyStrategy (A-I + F&G + filtros)
        dataframe = super().populate_entry_trend(dataframe, metadata)

        # Si FreqAI no ha generado predicciones aún (pares sin historial suficiente)
        # → conservar las señales tal como están (no bloquear)
        if "&s_up_label_mean" not in dataframe.columns:
            return dataframe

        # Probabilidad de subida según el clasificador (0.0 - 1.0)
        ml_prob  = dataframe["&s_up_label_mean"].fillna(0.5)
        ml_valid = (dataframe.get("do_predict", pd.Series(0, index=dataframe.index)) == 1)

        # Confianza ML: prob > umbral Y predicción válida
        ml_confident = (ml_prob > self.buy_ml_min_conf.value) & ml_valid

        # Zona ultra-oversold: si el precio está muy deprimido, no necesitamos ML
        ultra_oversold = (dataframe["bb_percent"] <= 0.12) | (dataframe["rsi"] < 22)

        # Señales FUERTES — ignoran ML (pánico macro, capitulación extrema)
        strong_tags = {"D_capitulation", "H_panic_fear", "I_rsi_crash"}

        # Para cada fila con señal, aplicar filtro ML solo si no es señal fuerte
        has_signal    = dataframe["enter_long"] == 1
        is_strong     = dataframe["enter_tag"].isin(strong_tags)
        needs_ml      = has_signal & ~is_strong & ~ultra_oversold

        # Bloquear señales débiles que el ML no confirma
        block = needs_ml & ~ml_confident
        dataframe.loc[block, "enter_long"] = 0
        dataframe.loc[block, "enter_tag"]  = ""

        return dataframe
