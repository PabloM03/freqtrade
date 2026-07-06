#!/usr/bin/env bash
# ops/run_hyperopt.sh — Hyperopt automático con validación OOS y auto-deploy
# ===========================================================================
# Uso: bash ops/run_hyperopt.sh [meses]
#
#   meses  — ventana de optimización en meses hacia atrás (default: 24)
#             Ej: bash ops/run_hyperopt.sh 12   → optimiza últimos 12 meses
#
# Flujo completo:
#   1. Descarga datos 15m (desde 2022 para tener OOS)
#   2. Hyperopt en los últimos N meses (mercado actual, sin sesgo bear 2022)
#   3. Valida en 2022 OOS — si WR < 40%: restaura backup y aborta
#   4. Si OK: reinicia el servicio con los nuevos params
#   5. Muestra backtesting en ventana reciente (informativo)

set -euo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
FT="/home/ubuntu/miniconda3/envs/freqtrade/bin/freqtrade"
[ -x "$FT" ] || FT="$(conda run -n freqtrade which freqtrade 2>/dev/null || echo freqtrade)"

LOG="$BASE/logs/hyperopt_$(date -u +%Y%m%d-%H%M%S).log"
mkdir -p "$BASE/logs"
exec > >(tee -a "$LOG") 2>&1

# Lock — evita que dos instancias corran simultáneamente
LOCK="/tmp/freqtrade_hyperopt.lock"
if [ -f "$LOCK" ]; then
    echo "ERROR: Hyperopt ya en curso (lock: $LOCK). Saliendo."
    exit 1
fi
trap 'rm -f "$LOCK"' EXIT INT TERM
touch "$LOCK"

# Ventana dinámica: últimos N meses hasta hoy
MONTHS="${1:-24}"
TODAY="$(date -u +%Y%m%d)"
OPT_START="$(date -u -d "$MONTHS months ago" +%Y%m%d 2>/dev/null \
          || date -u -v-${MONTHS}m +%Y%m%d)"   # macOS fallback

echo "================================================================"
echo " HYPEROPT AUTO — $(date -u +'%F %T') UTC"
echo " Ventana: ${OPT_START} → ${TODAY} (últimos ${MONTHS} meses)"
echo " Loss: CalmarHyperOptLoss — optimiza profit/drawdown en mercado actual"
echo " Log: $LOG"
echo "================================================================"
cd "$BASE"

# Auto-detectar config.secrets.json (raíz en local, ops/ en servidor)
if [ -f "ops/config.secrets.json" ]; then
    SECRETS="ops/config.secrets.json"
elif [ -f "config.secrets.json" ]; then
    SECRETS="config.secrets.json"
else
    echo "ERROR: no se encuentra config.secrets.json ni ops/config.secrets.json"
    exit 1
fi
CONF="-c config.base.json -c config.backtest.json -c $SECRETS"

PARAMS_FILE="$BASE/user_data/strategies/CombinedBinHAndCluc.json"

# 1. Actualizar datos (desde 2022 para tener datos de validación OOS)
# timeout 900s (15 min) — download-data a veces no cierra el pipe al terminar (bug freqtrade)
echo ""
echo "[1/4] Descargando datos 15m desde 20220101 (timeout 15min)..."
timeout 900 "$FT" download-data $CONF \
    --timeframes 15m \
    --timerange "20220101-${TODAY}" \
    --prepend \
    2>&1 | grep -E 'Downloading|Done|pairs|Error' | tail -10 || true
echo "  Descarga completada (o timeout alcanzado — datos existentes son suficientes)"

# Backup de los params antes del hyperopt
BACKUP=""
if [ -f "$PARAMS_FILE" ]; then
    BACKUP="${PARAMS_FILE%.json}.backup_$(date -u +%Y%m%d-%H%M%S)"
    cp "$PARAMS_FILE" "$BACKUP"
    echo "  Backup: $BACKUP"
fi

# 2. Hyperopt en mercado reciente
echo ""
echo "[2/4] Hyperopt — 1500 epochs, CalmarHyperOptLoss, ventana ${OPT_START}-${TODAY}..."
echo "      Espacios: buy + sell (stoploss intocable)"
"$FT" hyperopt $CONF \
    -s MyStrategy \
    --spaces buy sell \
    --hyperopt-loss CalmarHyperOptLoss \
    --timerange "${OPT_START}-${TODAY}" \
    -e 1500 \
    -j 2 \
    --random-state 42 \
    --min-trades 20 \
    --no-color

# Verificar que el hyperopt generó params nuevos
if [ ! -f "$PARAMS_FILE" ]; then
    echo ""
    echo "ERROR: hyperopt no generó $PARAMS_FILE. Bot sin cambios."
    [ -n "$BACKUP" ] && cp "$BACKUP" "$PARAMS_FILE" && echo "Backup restaurado."
    exit 1
fi

# 3. Validación en ventana reciente — métricas informativas
echo ""
echo "[3/4] Validación reciente ${OPT_START}-${TODAY}..."
"$FT" backtesting $CONF \
    -s MyStrategy --timerange "${OPT_START}-${TODAY}" --cache none 2>&1 \
    | grep -E 'Trades|Win|Profit|Drawdown|STRATEGY SUMMARY' | tail -8

# 4. Stress test 2022 bear — criterio de aceptación: WR ≥ 40%
#    La estrategia es de reversión en bull, NO de bear. 40% es el mínimo para no ser
#    catastrófico si el mercado se gira. CalmarHyperOptLoss ya garantiza calidad en bull.
echo ""
echo "[4/4] Stress test 2022 (criterio: WR ≥ 40% o 0 trades)..."
OOS_OUT=$("$FT" backtesting $CONF \
    -s MyStrategy --timerange 20220101-20221231 --cache none 2>&1)
echo "$OOS_OUT" | grep -E 'Trades|Win|Profit|Drawdown|STRATEGY SUMMARY' | tail -8

# Parsear trades y wins del STRATEGY SUMMARY
SUMMARY_LINE=$(echo "$OOS_OUT" | grep -E '^\s*\|\s*MyStrategy' | tail -1)
OOS_TRADES=$(echo "$SUMMARY_LINE" | awk -F'|' '{gsub(/ /,"",$3); print $3+0}')
OOS_WINS=$(echo "$SUMMARY_LINE"  | awk -F'|' '{gsub(/ /,"",$6); print $6+0}')

DEPLOY=true
if [[ "$OOS_TRADES" =~ ^[0-9]+$ && "$OOS_TRADES" -gt 0 ]]; then
    WR_PCT=$(( OOS_WINS * 100 / OOS_TRADES ))
    if [[ $WR_PCT -lt 40 ]]; then
        echo ""
        echo "  ⚠️  WR 2022 = ${WR_PCT}% < 40% — overfit al bull. Restaurando params anteriores."
        DEPLOY=false
    else
        echo ""
        echo "  ✓ WR 2022 = ${WR_PCT}% ≥ 40% — params aceptados"
    fi
else
    echo ""
    echo "  ✓ 0 trades en 2022 — estrategia correctamente conservadora en bear"
fi

echo ""
echo "================================================================"
if $DEPLOY; then
    echo " ✓ CRITERIOS OK — Aplicando params y reiniciando bot..."
    sudo systemctl restart freqtrade 2>/dev/null \
        && echo " Bot reiniciado con nuevos params ✓" \
        || echo " WARN: reinicio manual: sudo systemctl restart freqtrade"
else
    [ -n "$BACKUP" ] && cp "$BACKUP" "$PARAMS_FILE" && echo " Params revertidos al backup."
    echo " Bot sin cambios (params anteriores preservados)."
fi
echo " Completado: $(date -u +'%F %T') UTC"
echo " Log: $LOG"
echo "================================================================"
