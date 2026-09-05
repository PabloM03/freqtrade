#!/usr/bin/env bash
set -euo pipefail
BASE="/home/ubuntu/freqtrade"
OPS="$BASE/ops"
exec freqtrade trade \
  -c "$BASE/config.base.json" \
  -c "$OPS/config.prop.json" \
  -c "$OPS/config.secrets.json"
