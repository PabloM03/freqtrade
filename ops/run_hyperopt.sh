#!/usr/bin/env bash
# ops/run_hyperopt.sh — Hyperopt manual con validación OOS
# =========================================================
# Uso: bash ops/run_hyperopt.sh [meses]
#
#   meses  — ventana de optimización en meses hacia atrás (default: 18)
#             Ej: bash ops/run_hyperopt.sh 12   → optimiza últimos 12 meses
#
# Filosofía:
#   - Optimizar en mercado RECIENTE (últimos ~18 meses) — los parámetros
#     deben ser óptimos para el mercado actual, no para el bear 2022
#   - 2022 solo se usa como VALIDACIÓN OOS (stress test que no catastrofea)
#
# NO auto-despliega — muestra resultados para revisión manual.
# Despliegue: copiar el JSON generado a user_data/strategies/CombinedBinHAndCluc.json
# y hacer git push para que CI/CD lo aplique.

set -euo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
FT="/home/ubuntu/miniconda3/envs/freqtrade/bin/freqtrade"
[ -x "$FT" ] || FT="$(conda run -n freqtrade which freqtrade 2>/dev/null || echo freqtrade)"

LOG="$BASE/logs/hyperopt_$(date -u +%Y%m%d-%H%M%S).log"
mkdir -p "$BASE/logs"
exec > >(tee -a "$LOG") 2>&1

# Lock — evita que dos instancias corran simultáneamente (hyperopt usa todos los CPUs)
LOCK="/tmp/freqtrade_hyperopt.lock"
if [ -f "$LOCK" ]; then
    echo "ERROR: Hyperopt ya en curso (lock: $LOCK). Saliendo."
    exit 1
fi
trap 'rm -f "$LOCK"' EXIT INT TERM
touch "$LOCK"

# Ventana dinámica: últimos N meses hasta hoy
# Default 24 meses — suficientes trades (150-200) para que Calmar sea significativo
MONTHS="${1:-24}"
TODAY="$(date -u +%Y%m%d)"
OPT_START="$(date -u -d "$MONTHS months ago" +%Y%m%d 2>/dev/null \
          || date -u -v-${MONTHS}m +%Y%m%d)"   # macOS fallback

echo "================================================================"
echo " HYPEROPT MANUAL — $(date -u +'%F %T') UTC"
echo " Ventana optimización: ${OPT_START} → ${TODAY} (últimos ${MONTHS} meses)"
echo " Loss: CalmarHyperOptLoss (profit / max_drawdown) — sin 2022 = no sesgado al bear"
echo " Log: $LOG"
echo "================================================================"
cd "$BASE"

CONF="-c config.base.json -c config.backtest.json -c ops/config.secrets.json"

# 1. Actualizar datos (desde 2022 para tener datos de validación OOS)
echo ""
echo "[1/4] Descargando datos 15m desde 20220101..."
"$FT" download-data $CONF \
    --timeframes 15m \
    --timerange "20220101-${TODAY}" \
    --prepend \
    2>&1 | grep -E 'Downloading|Done|pairs' | tail -5

# Backup de los params actuales (para comparar antes/después)
PARAMS_FILE="$BASE/user_data/strategies/CombinedBinHAndCluc.json"
if [ -f "$PARAMS_FILE" ]; then
    BACKUP="${PARAMS_FILE%.json}.backup_$(date -u +%Y%m%d)"
    cp "$PARAMS_FILE" "$BACKUP"
    echo "  Backup params: $BACKUP"
fi

# 2. Hyperopt en mercado reciente — CalmarHyperOptLoss maximiza profit/drawdown
#    Sin 2022 en la ventana, Calmar no penaliza el bear → parámetros óptimos para bull actual
#    1500 epochs para una búsqueda exhaustiva
echo ""
echo "[2/4] Hyperopt — 1500 epochs, CalmarHyperOptLoss, ventana ${OPT_START}-${TODAY}..."
echo "      Espacios: buy + sell (stoploss intocable)"
"$FT" hyperopt $CONF \
    -s MyStrategy \
    --spaces buy sell \
    --hyperopt-loss CalmarHyperOptLoss \
    --timerange "${OPT_START}-${TODAY}" \
    -e 1500 \
    -j -1 \
    --random-state 42 \
    --min-trades 20 \
    --no-color

# 3. Validación OOS 2022 (bear market — stress test)
#    Criterio de rechazo: WR < 40% en 2022 → overfit al bull, descartar
echo ""
echo "[3/4] Validación OOS 2022 (bear stress test — rechazar si WR < 40%)..."
"$FT" backtesting $CONF \
    -s MyStrategy --timerange 20220101-20221231 --cache none 2>&1 \
    | grep -E 'Trades|Win|Profit|Drawdown|STRATEGY SUMMARY' | tail -8

# 4. Validación en la ventana de optimización (ver Calmar, DD, WR)
echo ""
echo "[4/4] Validación ventana reciente ${OPT_START}-${TODAY}..."
"$FT" backtesting $CONF \
    -s MyStrategy --timerange "${OPT_START}-${TODAY}" --cache none 2>&1 \
    | grep -E 'Trades|Win|Profit|Drawdown|STRATEGY SUMMARY' | tail -8

echo ""
echo "================================================================"
echo " COMPLETADO — $(date -u +'%F %T') UTC"
echo " Ventana usada: ${OPT_START} → ${TODAY} (${MONTHS} meses)"
echo " Resultados en: user_data/strategies/CombinedBinHAndCluc.json"
echo " Para desplegar: git add/commit/push desde local → CI/CD aplica"
echo " NOTA: Si WR 2022 < 40% → no desplegar (overfit al bull)"
echo "================================================================"
