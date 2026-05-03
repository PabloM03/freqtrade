#!/usr/bin/env bash
# ops/run_hyperopt.sh — Hyperopt manual con validación OOS
# =========================================================
# Uso: bash ops/run_hyperopt.sh
#
# NO auto-despliega — muestra resultados para revisión manual.
# Despliegue: copiar el JSON generado a user_data/strategies/CombinedBinHAndCluc.json
# y hacer git push para que CI/CD lo aplique.
#
# Diferencias clave vs train_and_deploy.sh (desactivado):
#   - Descarga datos desde 2022 (incluye bear market OOS)
#   - Incluye datos 2026 (corrección de abril)
#   - --min-trades 20 (fuerza más frecuencia de trades)
#   - --spaces buy sell (stoploss NUNCA se toca)
#   - No auto-despliega — revisión manual antes de aplicar

set -euo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
FT="/home/ubuntu/miniconda3/envs/freqtrade/bin/freqtrade"
[ -x "$FT" ] || FT="$(conda run -n freqtrade which freqtrade 2>/dev/null || echo freqtrade)"

LOG="$BASE/logs/hyperopt_manual_$(date -u +%Y%m%d-%H%M%S).log"
mkdir -p "$BASE/logs"
exec > >(tee -a "$LOG") 2>&1

echo "================================================================"
echo " HYPEROPT MANUAL — $(date -u +'%F %T') UTC"
echo " Log: $LOG"
echo "================================================================"
cd "$BASE"

CONF="-c config.base.json -c config.backtest.json -c ops/config.secrets.json"

# 1. Actualizar datos desde 2022
echo ""
echo "[1/4] Descargando datos 15m desde 20220101..."
"$FT" download-data $CONF \
    --timeframes 15m \
    --timerange "20220101-$(date -u +%Y%m%d)" \
    --prepend \
    2>&1 | grep -E 'Downloading|Done|pairs' | tail -5

# 2. Hyperopt 2022-2026
echo ""
echo "[2/4] Hyperopt — 1000 epochs, OnlyProfitHyperOptLoss, min-trades=20..."
echo "      Espacios: buy + sell (stoploss intocable)"
"$FT" hyperopt $CONF \
    -s MyStrategy \
    --spaces buy sell \
    --hyperopt-loss OnlyProfitHyperOptLoss \
    --timerange 20220101-20260430 \
    -e 1000 \
    -j -1 \
    --random-state 42 \
    --min-trades 20 \
    --no-color

# 3. Validación OOS 2022 (bear market)
echo ""
echo "[3/4] Validación OOS 2022 (bear market)..."
"$FT" backtesting $CONF \
    -s MyStrategy --timerange 20220101-20221231 --cache none 2>&1 \
    | grep -E 'Trades|Win|Profit|Drawdown|STRATEGY SUMMARY' | tail -8

# 4. Validación in-sample 2024-2025 (comparar con baseline: 98T 88.8% WR +$1129)
echo ""
echo "[4/4] Validación 2024-2025 (baseline: 98T, 88.8% WR, +\$1129)..."
"$FT" backtesting $CONF \
    -s MyStrategy --timerange 20240101-20251231 --cache none 2>&1 \
    | grep -E 'Trades|Win|Profit|Drawdown|STRATEGY SUMMARY' | tail -8

echo ""
echo "================================================================"
echo " COMPLETADO — $(date -u +'%F %T') UTC"
echo " Resultados en: user_data/strategies/CombinedBinHAndCluc.json"
echo " Para desplegar: git add/commit/push desde local → CI/CD aplica"
echo "================================================================"
