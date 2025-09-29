#!/usr/bin/env bash
set -euo pipefail
logger -t trade "[trade] usando /home/ubuntu/freqtrade/ops/config.withparams.json"
# Importante: NO tocar parámetros por CLI. La estrategia leerá el JSON plano.
exec freqtrade trade -c /home/ubuntu/freqtrade/ops/config.withparams.json
