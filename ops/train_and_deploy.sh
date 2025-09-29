#!/usr/bin/env bash
set -euo pipefail
# ---- logging a fichero además de journald ----
LOG="$OPS/retrain.$(date -u +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1
echo "[retrain] $(date -u +'%F %T') inicio"
# ---------------------------------------------

BASE="/home/ubuntu/freqtrade"
CONF="$BASE/config.json"
OPS="$BASE/ops"
STRAT="CombinedBinHAndCluc"
TF="5m"

# Ventana rolling: entrena ~150 días y deja 15 días fuera si luego quieres validar
TRAIN_START=$(date -u -d "150 days ago" +%Y%m%d)
TRAIN_END=$(date -u -d "15 days ago" +%Y%m%d)
TIMERANGE="${TRAIN_START}-${TRAIN_END}"

EPOCHS=1200
BEST_TMP="$OPS/params_tmp.json"

cd "$BASE"

# Requisitos previos simples
command -v jq >/dev/null || { echo "[retrain] ERROR: falta 'jq' (sudo apt-get install -y jq)"; exit 2; }
test -f "$BASE/user_data/hyperoptloss/my_balanced_loss.py" || {
  echo "[retrain] AVISO: no veo user_data/hyperoptloss/my_balanced_loss.py (usando MyBalancedLoss)."
}


echo "[retrain] descargando datos..."
freqtrade download-data -t "$TF" --days 200

echo "[retrain] lanzando hyperopt (TPE)..."

freqtrade hyperopt \
  -s "$STRAT" \
  -c "$CONF" \
  --spaces buy sell stoploss trailing protection \
  --hyperopt-loss MyBalancedLoss \
  --timerange "$TIMERANGE" \
  -e "$EPOCHS" \
  --random-state 42 \
  --export-params "$BEST_TMP" \
  --no-color

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


