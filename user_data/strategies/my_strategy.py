# pragma pylint: disable=missing-docstring, invalid-name, pointless-string-statement
# flake8: noqa: F401
# isort: skip_file
# --- Do not remove these imports ---
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone
from pandas import DataFrame
from typing import Optional, Union

from freqtrade.strategy import (
    IStrategy,
    Trade,
    Order,
    PairLocks,
    informative,
    BooleanParameter,
    CategoricalParameter,
    DecimalParameter,
    IntParameter,
    RealParameter,
    timeframe_to_minutes,
    timeframe_to_next_date,
    timeframe_to_prev_date,
    merge_informative_pair,
    stoploss_from_absolute,
    stoploss_from_open,
)

import talib.abstract as ta
from technical import qtpylib


class MyStrategy(IStrategy):
    INTERFACE_VERSION = 3

    # Long only (tu código tenía short pero lo tenías desactivado: mejor no generar señales short)
    can_short: bool = False

    timeframe = "5m"
    process_only_new_candles = True

    use_exit_signal = True
    exit_profit_only = True          # <- evita “salidas tontas” si no hay profit
    ignore_roi_if_entry_signal = False

    # ROI más coherente para buscar tramos (no scalping micro)
    minimal_roi = {
        "0": 0.06,     # si hay tramo, busca 6%
        "30": 0.04,    # a partir de 30m baja exigencia
        "90": 0.025,
        "180": 0.015,
        "360": 0.0,
    }

    # Stoploss menos suicida que -10% en 5m (pero sigue dando aire)
    stoploss = -0.08

    # Trailing para capturar “beneficios grandes”
    trailing_stop = True
    trailing_stop_positive = 0.012          # asegura +1.2% una vez activado
    trailing_stop_positive_offset = 0.03    # no se activa hasta +3%
    trailing_only_offset_is_reached = True

    startup_candle_count: int = 200

    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }
    order_time_in_force = {"entry": "GTC", "exit": "GTC"}

    # ==========================
    # Parámetros optimizables (hyperopt)
    # ==========================
    buy_rsi = IntParameter(10, 45, default=28, space="buy", optimize=True, load=True)
    sell_rsi = IntParameter(55, 95, default=72, space="sell", optimize=True, load=True)

    buy_adx = IntParameter(10, 35, default=18, space="buy", optimize=True, load=True)
    buy_bb_percent = DecimalParameter(0.05, 0.40, default=0.20, decimals=2, space="buy", optimize=True, load=True)
    buy_bb_width = DecimalParameter(0.01, 0.12, default=0.03, decimals=3, space="buy", optimize=True, load=True)

    sell_bb_percent = DecimalParameter(0.60, 0.98, default=0.88, decimals=2, space="sell", optimize=True, load=True)

    plot_config = {
        "main_plot": {"tema": {}, "sar": {"color": "white"}},
        "subplots": {
            "MACD": {"macd": {"color": "blue"}, "macdsignal": {"color": "orange"}},
            "RSI": {"rsi": {"color": "red"}},
        },
    }

    def informative_pairs(self):
        return []

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Momentum
        dataframe["adx"] = ta.ADX(dataframe)
        dataframe["rsi"] = ta.RSI(dataframe)

        stoch_fast = ta.STOCHF(dataframe)
        dataframe["fastd"] = stoch_fast["fastd"]
        dataframe["fastk"] = stoch_fast["fastk"]

        macd = ta.MACD(dataframe)
        dataframe["macd"] = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]
        dataframe["macdhist"] = macd["macdhist"]

        dataframe["mfi"] = ta.MFI(dataframe)

        # Bollinger
        bollinger = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2)
        dataframe["bb_lowerband"] = bollinger["lower"]
        dataframe["bb_middleband"] = bollinger["mid"]
        dataframe["bb_upperband"] = bollinger["upper"]
        dataframe["bb_percent"] = (dataframe["close"] - dataframe["bb_lowerband"]) / (
            dataframe["bb_upperband"] - dataframe["bb_lowerband"]
        )
        dataframe["bb_width"] = (dataframe["bb_upperband"] - dataframe["bb_lowerband"]) / dataframe["bb_middleband"]

        # Trend
        dataframe["sar"] = ta.SAR(dataframe)
        dataframe["tema"] = ta.TEMA(dataframe, timeperiod=9)

        # Extra helpers
        dataframe["tema_rising"] = dataframe["tema"] > dataframe["tema"].shift(1)
        dataframe["tema_falling"] = dataframe["tema"] < dataframe["tema"].shift(1)
        dataframe["macdhist_rising"] = dataframe["macdhist"] > dataframe["macdhist"].shift(1)
        dataframe["macdhist_falling"] = dataframe["macdhist"] < dataframe["macdhist"].shift(1)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe["volume"] > 0)
                # 1) Evitar lateralidad muerta: necesitas volatilidad mínima
                & (dataframe["bb_width"] > self.buy_bb_width.value)
                # 2) Evitar mercados sin dirección: ADX mínimo
                & (dataframe["adx"] > self.buy_adx.value)
                # 3) Zona “barata” dentro de BB (más margen hasta arriba)
                & (dataframe["bb_percent"] < self.buy_bb_percent.value)
                # 4) Giro a favor: TEMA subiendo y precio no por encima de BB mid
                & (dataframe["tema"] <= dataframe["bb_middleband"])
                & (dataframe["tema_rising"])
                # 5) Impulso real: MACD hist subiendo
                & (dataframe["macdhist_rising"])
                # 6) RSI confirma salida de sobreventa (menos ruido que solo “cruce”)
                & (dataframe["rsi"] > self.buy_rsi.value)
                & (dataframe["rsi"].shift(1) <= self.buy_rsi.value)
                # 7) Evita comprar ya recalentado por flujo (MFI muy alto)
                & (dataframe["mfi"] < 70)
            ),
            "enter_long",
        ] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe["volume"] > 0)
                # Salida por zona alta + pérdida de impulso
                & (
                    (
                        (dataframe["bb_percent"] > self.sell_bb_percent.value)
                        & (dataframe["tema_falling"])
                        & (dataframe["macdhist_falling"])
                    )
                    |
                    (
                        (dataframe["rsi"] > self.sell_rsi.value)
                        & (dataframe["tema_falling"])
                    )
                )
            ),
            "exit_long",
        ] = 1

        return dataframe
