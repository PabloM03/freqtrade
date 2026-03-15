#!/usr/bin/env bash
# Revierte los params del bot al backup anterior al último reentrenamiento
set -euo pipefail

BASE="/home/ubuntu/freqtrade"
OPS="$BASE/ops"
STRAT="CombinedBinHAndCluc"
PARAMS_SRC="$BASE/user_data/strategies/${STRAT}.json"
PARAMS_BAK="$OPS/params.bak.json"
CONF_SECRETS="$OPS/config.secrets.json"

if [[ ! -f "$PARAMS_BAK" ]]; then
  echo "ERROR: no existe backup en $PARAMS_BAK"
  exit 1
fi

echo "Revirtiendo params..."
cp "$PARAMS_BAK" "$PARAMS_SRC"
sudo systemctl restart freqtrade
echo "Params revertidos. Bot reiniciado."

# Notificación Telegram
if [[ -f "$CONF_SECRETS" ]]; then
  TG_TOKEN=$(jq -r '.telegram.token // empty' "$CONF_SECRETS")
  TG_CHAT=$(jq  -r '.telegram.chat_id // empty' "$CONF_SECRETS")
  SL=$(jq -r '.params.stoploss.stoploss // .stoploss // "?"' "$PARAMS_BAK")
  if [[ -n "$TG_TOKEN" && -n "$TG_CHAT" ]]; then
    curl -s -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
      -d chat_id="$TG_CHAT" \
      -d parse_mode="HTML" \
      -d text="⏪ <b>Params revertidos al backup anterior</b>
Stoploss restaurado: $SL
Bot reiniciado." > /dev/null || true
  fi
fi
