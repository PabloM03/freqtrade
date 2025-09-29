from datetime import datetime
from math import exp
from pandas import DataFrame
from freqtrade.constants import Config
from freqtrade.optimize.hyperopt import IHyperOptLoss

# Ajusta si quieres
TARGET_TRADES = 600                 # nº operaciones objetivo para tu ventana
EXPECTED_MAX_PROFIT = 3.0           # suma de profit_ratio esperada (ratio)
MAX_ACCEPTED_TRADE_DURATION = 300   # minutos

class MyBalancedLoss(IHyperOptLoss):
    """
    Menor = mejor. Equilibra:
    - beneficio total alto
    - nº de operaciones razonable (cerca de TARGET_TRADES)
    - duración media controlada
    """
    @staticmethod
    def hyperopt_loss_function(
        results: DataFrame,
        trade_count: int,
        min_date: datetime,
        max_date: datetime,
        config: Config,
        processed: dict[str, DataFrame],
        *args, **kwargs,
    ) -> float:
        total_profit = float(results["profit_ratio"].sum()) if not results.empty else 0.0
        trade_duration = float(results["trade_duration"].mean()) if not results.empty else MAX_ACCEPTED_TRADE_DURATION

        trade_loss = 1 - 0.25 * exp(-((trade_count - TARGET_TRADES) ** 2) / 10**5.8)
        profit_loss = max(0.0, 1.0 - total_profit / EXPECTED_MAX_PROFIT)
        duration_loss = 0.4 * min(trade_duration / MAX_ACCEPTED_TRADE_DURATION, 1.0)

        return trade_loss + profit_loss + duration_loss
