#!/usr/bin/env bash
set -euo pipefail

BASE="/home/ubuntu/freqtrade"
CONF="$BASE/config.json"
OPS="$BASE/ops"
STRAT="CombinedBinHAndCluc"
TF="5m"

# ventanas rolling: entrena últimos 150 días y despliega si OK
TRAIN_START=$(date -u -d "150 days ago" +%Y%m%d)
TRAIN_END=$(date -u -d "15 days ago" +%Y%m%d)     # deja 15 días para OOS si luego quieres validar
TIMERANGE="${TRAIN_START}-${TRAIN_END}"

EPOCHS=1200

cd "$BASE"

echo "[retrain] descargando datos..."
freqtrade download-data -t "$TF" --days 200

echo "[retrain] lanzando hyperopt (TPE)..."
# Exporta el mejor set directamente a un fichero controlado
BEST_TMP="$OPS/params_tmp.json"
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

# Normaliza el JSON (según versión, puede venir como {"params":{...}} o directamente {...})
if jq -e 'has("params")' "$BEST_TMP" >/dev/null; then
  jq '.params' "$BEST_TMP" > "$BEST_TMP.norm"
else
  jq '.' "$BEST_TMP" > "$BEST_TMP.norm"
fi

# sanity check mínimo: que no esté vacío y tenga algunas claves
if [[ ! -s "$BEST_TMP.norm" ]] || [[ "$(jq 'length' "$BEST_TMP.norm")" -lt 5 ]]; then
  echo "[retrain] parámetros exportados vacíos o sospechosos. abortando despliegue."
  exit 2
fi

# despliegue atómico
echo "[retrain] desplegando nuevos parámetros..."
install -m 0644 "$BEST_TMP.norm" "$OPS/params.json.new"
mv -f "$OPS/params.json.new" "$OPS/params.json"

# reinicia el bot para aplicar (trade.sh leerá el nuevo params.json)
echo "[retrain] reiniciando servicio freqtrade..."
sudo systemctl restart freqtrade

echo "[retrain] ok. mejores parámetros aplicados."
