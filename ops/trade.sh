#!/usr/bin/env bash
set -euo pipefail

BASE="/home/ubuntu/freqtrade"
OPS="$BASE/ops"

# Config: usar split (config.base.json + ops/config.secrets.json) si existen.
# Fallback: ops/config.withparams.json (legacy, todo-en-uno).
CONF_BASE="$BASE/config.base.json"
CONF_PAIRS="$BASE/config.pairs.json"
CONF_SECRETS="$OPS/config.secrets.json"
CONF_LEGACY="$OPS/config.withparams.json"

if [[ -f "$CONF_BASE" && -f "$CONF_SECRETS" ]]; then
  # config.pairs.json: whitelist dinámica gestionada por validate_pairs.py (no en git)
  # Si existe, sobreescribe la pair_whitelist de config.base.json
  if [[ -f "$CONF_PAIRS" ]]; then
    logger -t trade "[trade] config: config.base.json + config.pairs.json + ops/config.secrets.json"
    exec freqtrade trade -c "$CONF_BASE" -c "$CONF_PAIRS" -c "$CONF_SECRETS"
  fi
  logger -t trade "[trade] config: config.base.json + ops/config.secrets.json"
  exec freqtrade trade -c "$CONF_BASE" -c "$CONF_SECRETS"
elif [[ -f "$CONF_LEGACY" ]]; then
  logger -t trade "[trade] config: ops/config.withparams.json (legacy)"
  exec freqtrade trade -c "$CONF_LEGACY"
else
  echo "[trade] ERROR: no config found. Crea ops/config.secrets.json (ver config.secrets.json.example)" >&2
  exit 1
fi
