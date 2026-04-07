#!/usr/bin/env bash
set -euo pipefail

# ---- REENTRENAMIENTO AUTOMÁTICO DESACTIVADO ----
# Desactivado 2026-04-07: los params del hyperopt automático empeoran la estrategia
# (OnlyProfitHyperOptLoss sin validación temporal suficiente → overfit).
# Los params óptimos están fijados en user_data/strategies/CombinedBinHAndCluc.json
# y se despliegan vía git push → CI/CD → rsync.
# Para reactivar: eliminar las 3 líneas siguientes.
echo "[retrain] DESACTIVADO — ver comentario en cabecera del script"
exit 0

BASE="/home/ubuntu/freqtrade"
OPS="$BASE/ops"
STRAT="CombinedBinHAndCluc"
TF="15m"

# ---- logging ----
LOG="$OPS/retrain.$(date -u +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1
echo "[retrain] $(date -u +'%F %T') inicio"

CONF_BASE="$BASE/config.base.json"
CONF_SECRETS="$OPS/config.secrets.json"

TRAIN_START="20220101"
TRAIN_END=$(date -u -d "3 days ago" +%Y%m%d)
TIMERANGE="${TRAIN_START}-${TRAIN_END}"

EPOCHS=1200
PARAMS_SRC="$BASE/user_data/strategies/${STRAT}.json"
PARAMS_BAK="$OPS/params.bak.json"
BEST_TMP="$OPS/params_tmp.json"

cd "$BASE"

# ---- helpers ----
command -v jq >/dev/null || { echo "[retrain] ERROR: falta jq"; exit 2; }

if [[ -f "$CONF_SECRETS" ]]; then
  CONF_ARGS="-c $CONF_BASE -c $CONF_SECRETS"
  TG_TOKEN=$(jq -r '.telegram.token // empty' "$CONF_SECRETS")
  TG_CHAT=$(jq  -r '.telegram.chat_id // empty' "$CONF_SECRETS")
else
  CONF_ARGS="-c $BASE/ops/config.withparams.json"
  TG_TOKEN=""
  TG_CHAT=""
fi

tg() {
  # Envía mensaje Telegram si hay credenciales
  local msg="$1"
  if [[ -n "$TG_TOKEN" && -n "$TG_CHAT" ]]; then
    curl -s -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
      -d chat_id="$TG_CHAT" \
      -d parse_mode="HTML" \
      -d text="$msg" > /dev/null || true
  fi
}

# ---- backup de params actuales ----
if [[ -f "$PARAMS_SRC" ]]; then
  cp "$PARAMS_SRC" "$PARAMS_BAK"
  OLD_SL=$(jq -r '.params.stoploss.stoploss // .stoploss // "?"' "$PARAMS_BAK")
  echo "[retrain] backup de params actuales → $PARAMS_BAK (stoploss=$OLD_SL)"
else
  OLD_SL="?"
fi

tg "🤖 <b>Reentrenamiento iniciado</b>
Fecha: $(date -u +'%F %T') UTC
Timerange: $TIMERANGE
Epochs: $EPOCHS"

# ---- descarga datos ----
echo "[retrain] descargando datos ${TF} desde ${TRAIN_START}..."
# shellcheck disable=SC2086
freqtrade download-data $CONF_ARGS -t "$TF" --timerange "${TRAIN_START}-$(date -u +%Y%m%d)" --prepend

# ---- hyperopt ----
echo "[retrain] lanzando hyperopt (${EPOCHS} epochs)..."
# shellcheck disable=SC2086
freqtrade hyperopt \
  -s "$STRAT" \
  $CONF_ARGS \
  --spaces buy sell stoploss \
  --hyperopt-loss OnlyProfitHyperOptLoss \
  --timerange "$TIMERANGE" \
  -e "$EPOCHS" \
  -j -1 \
  --random-state 42 \
  --min-trades 10 \
  --early-stop 300 \
  --no-color

cp "$PARAMS_SRC" "$BEST_TMP"
NEW_SL=$(jq -r '.params.stoploss.stoploss // .stoploss // "?"' "$BEST_TMP")

# ---- validación OOS 2022 ----
echo "[retrain] validando en 2022 OOS (bear market)..."
# shellcheck disable=SC2086
OOS_OUTPUT=$(freqtrade backtesting \
  -s "$STRAT" \
  $CONF_ARGS \
  --timerange 20220101-20221231 \
  --cache none 2>&1 || true)

echo "$OOS_OUTPUT"
OOS_WIN=$(echo "$OOS_OUTPUT" | grep -oP 'Win\s+\K[\d.]+(?=\s*%)' | tail -1 || echo "0")
OOS_TRADES=$(echo "$OOS_OUTPUT" | grep -oP 'Total trades\s+\|\s+\K\d+' | tail -1 || echo "?")
OOS_PROFIT=$(echo "$OOS_OUTPUT" | grep -oP 'Total profit %\s+\|\s+\K[\d.]+' | tail -1 || echo "?")
echo "[retrain] OOS 2022 → trades=$OOS_TRADES WR=${OOS_WIN}% profit=${OOS_PROFIT}%"

if (( $(echo "$OOS_WIN < 40" | bc -l) )); then
  MSG="❌ <b>Reentrenamiento ABORTADO</b>
WR en 2022 OOS: ${OOS_WIN}% (mínimo 40%)
Stoploss nuevo: $NEW_SL | anterior: $OLD_SL
Params NO desplegados. Para revisar manualmente: $BEST_TMP
Params anteriores intactos en: $PARAMS_BAK"
  tg "$MSG"
  echo "[retrain] ABORTANDO — WR OOS demasiado bajo"
  exit 4
fi

# ---- normalizar JSON ----
if jq -e 'has("params")' "$BEST_TMP" >/dev/null; then
  jq '.params' "$BEST_TMP" > "$BEST_TMP.norm"
else
  jq '.' "$BEST_TMP" > "$BEST_TMP.norm"
fi

if [[ ! -s "$BEST_TMP.norm" ]] || [[ "$(jq 'length' "$BEST_TMP.norm")" -lt 5 ]]; then
  tg "❌ <b>Reentrenamiento ABORTADO</b>
JSON de params vacío o inválido. Revisar manualmente."
  echo "[retrain] params exportados vacíos. abortando."
  exit 3
fi

# Sin cambios → no reiniciar
if [[ -f "$PARAMS_SRC" ]] && cmp -s "$BEST_TMP.norm" "$PARAMS_SRC"; then
  tg "ℹ️ <b>Reentrenamiento completado — sin cambios</b>
Los params óptimos son idénticos a los actuales. Bot no reiniciado."
  echo "[retrain] sin cambios en parámetros."
  exit 0
fi

# ---- despliegue atómico ----
echo "[retrain] desplegando nuevos parámetros..."
install -m 0644 "$BEST_TMP.norm" "$PARAMS_SRC.new"
mv -f "$PARAMS_SRC.new" "$PARAMS_SRC"
sudo systemctl restart freqtrade

WARN_MSG=""
if (( $(echo "$OOS_WIN < 55" | bc -l) )); then
  WARN_MSG="
⚠️ WR OOS moderado (${OOS_WIN}%) — revisar con precaución"
fi

tg "✅ <b>Reentrenamiento completado y desplegado</b>
Fecha: $(date -u +'%F %T') UTC

<b>Parámetros:</b>
  Stoploss anterior: $OLD_SL
  Stoploss nuevo:    $NEW_SL

<b>Validación 2022 OOS (bear market):</b>
  Trades: $OOS_TRADES | WR: ${OOS_WIN}% | Profit: ${OOS_PROFIT}%
$WARN_MSG
<b>Para revertir si algo va mal:</b>
  ssh server → bash ops/revert_params.sh"

echo "[retrain] ok. nuevos parámetros desplegados."

# housekeeping
find "$BASE/user_data/hyperopt_results" -type f -mtime +30 -delete || true
find "$BASE/user_data/logs"             -type f -mtime +14 -delete || true
find "$OPS" -name "retrain.*.log"       -type f -mtime +60 -delete || true
