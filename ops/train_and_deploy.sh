#!/usr/bin/env bash
set -euo pipefail
# ---- logging a fichero además de journald ----
LOG="$OPS/retrain.$(date -u +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1
echo "[retrain] $(date -u +'%F %T') inicio"
# ---------------------------------------------

BASE="/home/ubuntu/freqtrade"
OPS="$BASE/ops"
STRAT="CombinedBinHAndCluc"
TF="15m"   # timeframe de la estrategia activa

# Config: base + secrets + params en cascada
CONF_BASE="$BASE/config.base.json"
CONF_SECRETS="$OPS/config.secrets.json"   # credenciales del servidor (no en repo)

# Ventana rolling para hyperopt:
# - Incluye 2022 bear (OOS de validación) + datos recientes
# - Entrena con todos los datos disponibles para capturar patrones de todos los regímenes
TRAIN_START="20220101"
TRAIN_END=$(date -u -d "3 days ago" +%Y%m%d)
TIMERANGE="${TRAIN_START}-${TRAIN_END}"

EPOCHS=1200
# Freqtrade auto-exporta los mejores params a user_data/strategies/{STRAT}.json
PARAMS_SRC="$BASE/user_data/strategies/${STRAT}.json"
BEST_TMP="$OPS/params_tmp.json"

cd "$BASE"

# Requisitos previos
command -v jq >/dev/null || { echo "[retrain] ERROR: falta 'jq' (sudo apt-get install -y jq)"; exit 2; }

# Seleccionar config según lo que esté disponible
if [[ -f "$CONF_SECRETS" ]]; then
  CONF_ARGS="-c $CONF_BASE -c $CONF_SECRETS"
else
  # Fallback: config todo-en-uno legacy (servidor viejo)
  CONF_ARGS="-c $BASE/ops/config.withparams.json"
fi

echo "[retrain] descargando datos ${TF} desde ${TRAIN_START}..."
# shellcheck disable=SC2086
freqtrade download-data $CONF_ARGS -t "$TF" --timerange "${TRAIN_START}-$(date -u +%Y%m%d)" --prepend

echo "[retrain] lanzando hyperopt (${EPOCHS} epochs, timerange ${TIMERANGE})..."
# shellcheck disable=SC2086
freqtrade hyperopt \
  -s "$STRAT" \
  $CONF_ARGS \
  --spaces buy sell stoploss \
  --hyperopt-loss CalmarHyperOptLoss \
  --timerange "$TIMERANGE" \
  -e "$EPOCHS" \
  -j -1 \
  --random-state 42 \
  --min-trades 10 \
  --early-stop 300 \
  --no-color
# Freqtrade exporta automáticamente los mejores params a user_data/strategies/{STRAT}.json
cp "$PARAMS_SRC" "$BEST_TMP"

# ---- Validación OOS 2022 bear market ----
# Antes de desplegar, asegúrate de que los nuevos parámetros no destrozan el OOS
echo "[retrain] validando en 2022 OOS (bear market)..."
# shellcheck disable=SC2086
OOS_OUTPUT=$(freqtrade backtesting \
  -s "$STRAT" \
  $CONF_ARGS \
  --timerange 20220101-20221231 \
  --cache none 2>&1 || true)

echo "$OOS_OUTPUT"
# Extraer tasa de ganancias del output
OOS_WIN=$(echo "$OOS_OUTPUT" | grep -oP 'Win\s+\K[\d.]+(?=\s*%)' | tail -1 || echo "0")
echo "[retrain] Win rate 2022 OOS: ${OOS_WIN}%"
if (( $(echo "$OOS_WIN < 40" | bc -l) )); then
  echo "[retrain] ERROR: Win rate 2022 OOS muy bajo (${OOS_WIN}% < 40%). ABORTANDO despliegue."
  echo "[retrain] Parámetros candidatos en $BEST_TMP — revisar manualmente."
  exit 4
elif (( $(echo "$OOS_WIN < 55" | bc -l) )); then
  echo "[retrain] WARN: Win rate 2022 OOS moderado (${OOS_WIN}%). Desplegando con cautela."
else
  echo "[retrain] OK: Win rate 2022 OOS aceptable (${OOS_WIN}%)."
fi

# Normaliza el JSON (algunas versiones exportan {"params":{...}})
if jq -e 'has("params")' "$BEST_TMP" >/dev/null; then
  jq '.params' "$BEST_TMP" > "$BEST_TMP.norm"
else
  jq '.' "$BEST_TMP" > "$BEST_TMP.norm"
fi

# Sanity check básico
if [[ ! -s "$BEST_TMP.norm" ]] || [[ "$(jq 'length' "$BEST_TMP.norm")" -lt 5 ]]; then
  echo "[retrain] parámetros exportados vacíos o sospechosos. abortando despliegue."
  exit 3
fi

# Si ya existe params.json y no cambió, no reinicies
if [[ -f "$OPS/params.json" ]] && cmp -s "$BEST_TMP.norm" "$OPS/params.json"; then
  echo "[retrain] sin cambios en parámetros -> no reinicio."
  exit 0
fi

# Despliegue atómico
echo "[retrain] desplegando nuevos parámetros..."
install -m 0644 "$BEST_TMP.norm" "$OPS/params.json.new"
mv -f "$OPS/params.json.new" "$OPS/params.json"

# Reinicia el bot para aplicar
echo "[retrain] reiniciando servicio freqtrade..."
sudo systemctl restart freqtrade

echo "[retrain] ok. mejores parámetros aplicados."

# housekeeping: borra resultados/historicos viejos
find "$BASE/user_data/hyperopt_results" -type f -mtime +30 -delete || true
find "$BASE/user_data/logs"            -type f -mtime +14 -delete || true
