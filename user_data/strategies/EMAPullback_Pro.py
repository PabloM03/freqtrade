import freqtrade.vendor.qtpylib.indicators as qtpylib
import numpy as np
import talib.abstract as ta

from freqtrade.strategy.interface import IStrategy
from freqtrade.strategy import stoploss_from_open
from pandas import DataFrame
from datetime import datetime
from typing import Optional
from freqtrade.persistence import Trade


class EMAPullback_Pro(IStrategy):
    """
    Estrategia simple y robusta basada en medias móviles:
    - Filtro de tendencia: EMA200
    - Estructura: EMA20 / EMA50
    - Entrada: pullback hacia EMA20 dentro de tendencia alcista
    - Anti-cuchillo: límites de caídas + cooldown tras velón rojo
    - Salidas: take profit duro + pérdida de tendencia con beneficio mínimo
    - Trailing: simple, se activa solo cuando ya hay beneficio decente
    """

    # ===== Config base =====
    timeframe = "5m"
    startup_candle_count = 240  # para EMA200 con margen

    # Importante: mantenemos compatibilidad.
    use_sell_signal = False
    sell_profit_only = True
    ignore_roi_if_buy_signal = False
    trailing_stop = False
    minimal_roi = {"0": 0.0}

    # ===== Parámetros (pocos y con sentido) =====
    # Costes / mínimos
    FEE_RATE = 0.001
    SLIPPAGE_BUFFER = 0.0005
    MIN_PROFIT_NET = 2 * FEE_RATE + SLIPPAGE_BUFFER  # ~0.25% aprox

    # Riesgo
    stoploss = -0.06  # -6%

    # Take profit “duro”
    HARD_TP = 0.035   # 3.5%

    # Anti-cuchillo (en %)
    PCT1_MIN = -1.8   # si la última vela cae más de -1.8%, no comprar
    PCT3_MIN = -4.0   # si en 3 velas cae más de -4%, no comprar
    COOLDOWN_BARS = 3 # tras velón rojo, esperar N velas

    # Tendencia / entradas (medias)
    EMA_FAST = 20
    EMA_SLOW = 50
    EMA_TREND = 200

    # Entrada por pullback
    PULLBACK_EMA20_MULT = 1.002   # close <= ema20 * 1.002 (cerca)
    BUY_BELOW_EMA20 = True        # exige estar en pullback real
    AVOID_CHASING_PCT1 = 0.7      # no comprar si última vela sube > 0.7%
    AVOID_NEAR_HH = 0.010         # evitar compra a <1% del máximo 50 velas

    # RSI “ligero” (no protagonista)
    RSI_MIN = 35
    RSI_MAX = 60

    # Mínimo hold para no vender “al instante”
    MIN_HOLD_BARS = 3

    # Trailing simple
    TRAIL_START = 0.020   # cuando profit >= 2%, activar trailing
    TRAIL_DIST  = 0.018   # trailing ~1.8% desde el open (con stoploss_from_open)
    TRAIL_DIST_TIGHT = 0.012  # si pierde fuerza, apretar

    # ===== Indicadores =====
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema20"]  = ta.EMA(dataframe, timeperiod=self.EMA_FAST)
        dataframe["ema50"]  = ta.EMA(dataframe, timeperiod=self.EMA_SLOW)
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=self.EMA_TREND)

        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)

        # caídas/subidas rápidas (%)
        dataframe["pct_1"] = dataframe["close"].pct_change(1) * 100.0
        dataframe["pct_3"] = dataframe["close"].pct_change(3) * 100.0

        # velón rojo (cuchillo) + cooldown
        body = (dataframe["close"] - dataframe["open"]).abs()
        dataframe["big_red"] = (dataframe["close"] < dataframe["open"]) & (body > 1.2 * dataframe["atr"])
        dataframe["cooldown"] = dataframe["big_red"].rolling(self.COOLDOWN_BARS).max().fillna(0).astype(bool)

        # evitar comprar pegado a máximos recientes
        dataframe["hh_50"] = dataframe["high"].rolling(50).max()
        dataframe["near_hh"] = dataframe["close"] >= (dataframe["hh_50"] * (1.0 - self.AVOID_NEAR_HH))

        # estructura de tendencia
        dataframe["trend_up"] = (
            (dataframe["close"] > dataframe["ema200"]) &
            (dataframe["ema20"] > dataframe["ema50"]) &
            (dataframe["ema50"] > dataframe["ema200"])
        )

        # “pullback” hacia ema20 (no persecución)
        dataframe["pullback_ok"] = dataframe["close"] <= (dataframe["ema20"] * self.PULLBACK_EMA20_MULT)
        dataframe["ema20_slope_up"] = dataframe["ema20"] > dataframe["ema20"].shift(1)

        return dataframe

    # ===== Entradas =====
    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        anti_cuchillo = (
            (dataframe["pct_1"] > self.PCT1_MIN) &
            (dataframe["pct_3"] > self.PCT3_MIN) &
            (~dataframe["cooldown"]) &
            (dataframe["volume"] > 0)
        )

        no_chase = (
            (dataframe["pct_1"] < self.AVOID_CHASING_PCT1) &
            (~dataframe["near_hh"])
        )

        rsi_ok = (dataframe["rsi"] >= self.RSI_MIN) & (dataframe["rsi"] <= self.RSI_MAX)

        # Entrada principal: tendencia + pullback + pequeña confirmación
        # Confirmación mínima: o vela verde, o cierre subiendo vs previo
        confirm = (dataframe["close"] >= dataframe["open"]) | (dataframe["close"] > dataframe["close"].shift(1))

        entry = (
            dataframe["trend_up"] &
            dataframe["ema20_slope_up"] &
            rsi_ok &
            anti_cuchillo &
            no_chase &
            dataframe["pullback_ok"] &
            confirm
        )

        # Si quieres exigir estar por debajo de EMA20 (pullback real)
        if self.BUY_BELOW_EMA20:
            entry = entry & (dataframe["close"] <= dataframe["ema20"])

        dataframe.loc[entry, "buy"] = 1
        return dataframe

    # ===== Señal de salida (solo para compatibilidad; la salida real va en custom_exit) =====
    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["sell"] = 0
        return dataframe

    # ===== Util =====
    def _bars_elapsed(self, trade: Trade, current_time: datetime) -> int:
        tf_minutes = int(self.timeframe.rstrip("m"))
        seconds = (current_time - trade.open_date_utc).total_seconds()
        return int(max(0, seconds) // (tf_minutes * 60))

    # ===== Exits =====
    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs
    ) -> Optional[str]:

        # Evitar “compra y vende al instante”
        bars = self._bars_elapsed(trade, current_time)
        if bars < self.MIN_HOLD_BARS:
            return None

        # TP duro
        if current_profit is not None and current_profit >= self.HARD_TP:
            return "hard_tp"

        # Requiere beneficio neto mínimo para vender por señal (si no, no scalpeamos migajas)
        if current_profit is None or current_profit < self.MIN_PROFIT_NET:
            return None

        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last = df.iloc[-1]

            # Pérdida de estructura / tendencia:
            # 1) close pierde EMA20
            lose_ema20 = last["close"] < last["ema20"]
            # 2) cruce bajista EMA20 < EMA50 (más serio)
            bear_cross = last["ema20"] < last["ema50"]

            # Si estás en beneficio, y empieza a romper estructura, sal
            if bear_cross:
                return "ema20_below_ema50_exit"
            if lose_ema20 and (last["rsi"] < 55):
                return "lose_ema20_exit"

        except Exception:
            pass

        return None

    # ===== Stoploss dinámico (trailing simple) =====
    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs
    ) -> float:

        # Antes de activar trailing, usa stoploss base
        if current_profit is None or current_profit < self.TRAIL_START:
            return self.stoploss

        # Trailing simple: protege beneficio ya ganado
        # Si pierde EMA20 o RSI cae, aprieta un poco
        dist = self.TRAIL_DIST
        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last = df.iloc[-1]
            if (last["close"] < last["ema20"]) or (last["rsi"] < 50):
                dist = self.TRAIL_DIST_TIGHT
        except Exception:
            pass

        return stoploss_from_open(current_profit, dist)
