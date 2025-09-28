# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime
from math import exp, sqrt
from typing import Dict

import numpy as np
from pandas import DataFrame

from freqtrade.constants import Config
from freqtrade.optimize.hyperopt import IHyperOptLoss


# ---------------------------
# Ajustes de la función de pérdida (puedes tunearlos)
# ---------------------------

# Beneficio total objetivo (suma de profit_ratio)
# 3.0 = 300% Σ% (ojo: es suma de ratios de cada trade, NO CAGR).
EXPECTED_MAX_PROFIT = 3.0

# Objetivo de operaciones: puedes definirlo por día o absoluto
TARGET_TRADES_PER_DAY = 8.0     # objetivo razonable de actividad
MIN_TRADES_REQUIRED   = 120     # penalización fuerte si no llegas a esto

# Duración media máxima aceptable (min)
MAX_ACCEPTED_TRADE_DURATION = 300

# Pesos relativos de cada término (ajústalos a tu gusto)
W_PROFIT   = 1.00   # empuja a más beneficio total
W_TRADES   = 0.80   # empuja a suficiente nº de trades (actividad)
W_DD       = 0.80   # penaliza el drawdown máximo
W_DURATION = 0.40   # penaliza duración media alta
W_SHARPE   = 0.20   # recompensa Sharpe por operación (reduce pérdida)


class MyBalancedLoss(IHyperOptLoss):
    """
    Loss compuesta (menor = mejor):

      L =  W_PROFIT   * profit_loss
         + W_TRADES   * trades_loss
         + W_DD       * drawdown_loss
         + W_DURATION * duration_loss
         + W_SHARPE   * sharpe_penalty

    Donde:
      - profit_loss     -> penaliza si Σ profit_ratio está por debajo de EXPECTED_MAX_PROFIT.
      - trades_loss     -> penaliza si trade_count es bajo respecto a TARGET_TRADES_PER_DAY * días (y si < MIN_TRADES_REQUIRED).
      - drawdown_loss   -> penaliza el drawdown máximo (normalizado por el pico de equity).
      - duration_loss   -> penaliza duración media alta.
      - sharpe_penalty  -> penaliza si el Sharpe por operación < 2 (≈ “bueno”).
    """

    @staticmethod
    def _calc_days(min_date: datetime, max_date: datetime) -> float:
        span = (max_date - min_date).total_seconds()
        return max(1.0, span / 86400.0)

    @staticmethod
    def _safe_mean(series: DataFrame) -> float:
        if series is None or len(series) == 0:
            return 0.0
        return float(np.nanmean(series))

    @staticmethod
    def _equity_and_dd(results: DataFrame) -> tuple[np.ndarray, float]:
        """
        Construye una curva de equity y devuelve (equity_curve, max_dd_ratio)
        - Usa profit_abs si existe; si no, usa profit_ratio como proxy.
        - max_dd_ratio = max_drawdown / max_equity_peak (en [0,1]).
        """
        if "profit_abs" in results.columns:
            rets = results["profit_abs"].fillna(0.0).to_numpy()
        elif "profit_ratio" in results.columns:
            rets = results["profit_ratio"].fillna(0.0).to_numpy()
        else:
            # sin datos -> sin drawdown
            return np.array([0.0]), 0.0

        equity = np.cumsum(rets)
        if equity.size == 0:
            return np.array([0.0]), 0.0

        running_max = np.maximum.accumulate(equity)
        drawdown = running_max - equity
        max_dd_abs = float(np.nanmax(drawdown)) if drawdown.size else 0.0
        peak = float(np.nanmax(running_max)) if running_max.size else 0.0
        dd_ratio = (max_dd_abs / peak) if peak > 0 else 0.0
        dd_ratio = max(0.0, min(1.0, dd_ratio))  # clamp a [0,1]
        return equity, dd_ratio

    @staticmethod
    def _sharpe_per_trade(results: DataFrame) -> float:
        """
        Sharpe por operación (sin anualizar): mean / std de profit_ratio por trade.
        (Si std≈0, devuelve 0 para no explotar).
        """
        if "profit_ratio" not in results.columns or results.empty:
            return 0.0
        r = results["profit_ratio"].astype(float).dropna()
        if r.size < 2:
            return 0.0
        mu = float(r.mean())
        sd = float(r.std(ddof=0))
        return (mu / sd) if sd > 1e-12 else 0.0

    @staticmethod
    def hyperopt_loss_function(
        results: DataFrame,
        trade_count: int,
        min_date: datetime,
        max_date: datetime,
        config: Config,
        processed: Dict[str, DataFrame],
        *args,
        **kwargs,
    ) -> float:
        # Caso extremo: sin trades -> mala solución
        if results is None or results.empty or trade_count <= 0:
            return 1e9

        # -------- Beneficio total (suma de profit_ratio) --------
        total_profit_ratio = float(results["profit_ratio"].sum()) if "profit_ratio" in results.columns else 0.0
        # Queremos que se acerque (o supere) EXPECTED_MAX_PROFIT.
        profit_loss = max(0.0, 1.0 - (total_profit_ratio / max(1e-9, EXPECTED_MAX_PROFIT)))

        # -------- Actividad: nº de operaciones comparado con días --------
        days = MyBalancedLoss._calc_days(min_date, max_date)
        target_trades = TARGET_TRADES_PER_DAY * days
        # Penalización suave si te alejas del objetivo (gaussiana) + penalización fuerte si muy pocos trades
        trades_deviation = (trade_count - target_trades)
        # Escala: cuanto mayor la ventana, más permisivo (evita penalizar demasiado).
        scale = max(50.0, target_trades ** 1.15)
        trades_loss = 1.0 - exp(-(trades_deviation ** 2) / scale)

        if trade_count < MIN_TRADES_REQUIRED:
            trades_loss += (MIN_TRADES_REQUIRED - trade_count) * 0.002  # empuja a mínimo de muestras

        # -------- Drawdown máximo (normalizado) --------
        _, dd_ratio = MyBalancedLoss._equity_and_dd(results)
        drawdown_loss = dd_ratio  # ya está en [0,1]

        # -------- Duración media --------
        avg_minutes = MyBalancedLoss._safe_mean(results.get("trade_duration", None))
        duration_loss = min(avg_minutes / float(MAX_ACCEPTED_TRADE_DURATION), 1.0)

        # -------- Sharpe por trade --------
        sharpe = MyBalancedLoss._sharpe_per_trade(results)
        # Queremos Sharpe >= 2. Si < 2, penaliza linealmente; si >=2, no penaliza.
        sharpe_penalty = max(0.0, 2.0 - sharpe) / 2.0  # en [0,1] aprox.

        # -------- Loss total (menor = mejor) --------
        loss = (
            W_PROFIT   * profit_loss   +
            W_TRADES   * trades_loss   +
            W_DD       * drawdown_loss +
            W_DURATION * duration_loss +
            W_SHARPE   * sharpe_penalty
        )

        # Seguridad numérica
        if not np.isfinite(loss):
            return 1e9

        return float(loss)
