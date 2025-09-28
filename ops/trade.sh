#!/usr/bin/env bash
set -euo pipefail

BASE="/home/ubuntu/freqtrade"
CONF="$BASE/config.json"
PARAMS_FILE="$BASE/ops/params.json"

cd "$BASE"

if [[ -s "$PARAMS_FILE" ]]; then
  # compacta a una sola línea por si hay saltos
  PARAMS_JSON="$(tr -d '\n' < "$PARAMS_FILE")"
  echo "[trade] usando strategy-parameters desde $PARAMS_FILE"
  exec freqtrade trade -c "$CONF" --strategy-parameters "$PARAMS_JSON"
else
  echo "[trade] sin params.json -> arrancando sin --strategy-parameters"
  exec freqtrade trade -c "$CONF"
fi
