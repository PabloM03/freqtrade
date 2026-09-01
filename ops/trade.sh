#!/usr/bin/env bash
set -euo pipefail

BASE="/home/ubuntu/freqtrade"
OPS="$BASE/ops"

# Config: usar split (config.base.json + ops/config.secrets.json) si existen.
# Fallback: ops/config.withparams.json (legacy, todo-en-uno).
CONF_BASE="$BASE/config.base.json"
CONF_SECRETS="$OPS/config.secrets.json"
CONF_LEGACY="$OPS/config.withparams.json"

# Reducir caché de wallet de 3600s (1h) a 300s (5min) en wallets.py
# Se re-aplica en cada arranque para sobrevivir upgrades de freqtrade
WALLETS_PY=$(python3 -c "import freqtrade.wallets as w, inspect; print(inspect.getfile(w))" 2>/dev/null || true)
if [[ -n "$WALLETS_PY" && -f "$WALLETS_PY" ]]; then
  sed -i 's/timedelta(seconds=3600)/timedelta(seconds=300)/g' "$WALLETS_PY"
fi

if [[ -f "$CONF_BASE" && -f "$CONF_SECRETS" ]]; then
  logger -t trade "[trade] config: config.base.json + ops/config.secrets.json"
  exec freqtrade trade -c "$CONF_BASE" -c "$CONF_SECRETS"
elif [[ -f "$CONF_LEGACY" ]]; then
  logger -t trade "[trade] config: ops/config.withparams.json (legacy)"
  exec freqtrade trade -c "$CONF_LEGACY"
else
  echo "[trade] ERROR: no config found. Crea ops/config.secrets.json (ver config.secrets.json.example)" >&2
  exit 1
fi
