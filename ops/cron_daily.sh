#!/usr/bin/env bash
# ops/cron_daily.sh — Pipeline diario de sentimiento + noticias AI
# ================================================================
# Instalar en cron del servidor:
#   crontab -e
#   10 0 * * * /home/ubuntu/freqtrade/ops/cron_daily.sh >> /home/ubuntu/freqtrade/ops/logs/cron_daily.log 2>&1
#
# Requiere:
#   - ANTHROPIC_API_KEY en ops/.env (para analyze_news.py)
#   - Python 3 con urllib en PATH (sin dependencias extra)

set -euo pipefail

BASE="/home/ubuntu/freqtrade"
OPS="$BASE/ops"
LOG_DIR="$OPS/logs"
mkdir -p "$LOG_DIR"

# Añadir conda al PATH (no está disponible en cron por defecto)
for _conda_dir in /home/ubuntu/miniconda3/bin /home/ubuntu/anaconda3/bin /opt/conda/bin; do
  [ -x "$_conda_dir/conda" ] && export PATH="$_conda_dir:$PATH" && break
done

# Usar Python del conda env freqtrade (tiene anthropic, tavily-python, requests)
# Fallback a python3 del sistema si no existe el env
CONDA_PYTHON="/home/ubuntu/miniconda3/envs/freqtrade/bin/python3"
PYTHON="${CONDA_PYTHON:-python3}"
[ -x "$CONDA_PYTHON" ] && PYTHON="$CONDA_PYTHON"

echo "[cron_daily] $(date -u +'%F %T') UTC — inicio"

# 1. Fear & Greed + CoinGecko trending + Binance spikes + RSS news
echo "[cron_daily] step 1: fetch_sentiment (Fear&Greed + trending + noticias)"
"$PYTHON" "$OPS/fetch_sentiment.py" && echo "[cron_daily] fetch_sentiment OK" || echo "[cron_daily] WARN: fetch_sentiment falló (no fatal)"

# 2. Análisis temático — funciona con TAVILY_API_KEY o ANTHROPIC_API_KEY (o keywords fallback)
echo "[cron_daily] step 2: analyze_news (Tavily+keywords o Claude AI)"
"$PYTHON" "$OPS/analyze_news.py" && echo "[cron_daily] analyze_news OK" || echo "[cron_daily] WARN: analyze_news falló (usará señal neutral)"

# 3. Gestión automática de pares — sobreescribe la whitelist diariamente con los mejores pares.
# La blacklist es SOLO MANUAL — este script nunca la toca.
echo "[cron_daily] step 3: validate_pairs"
"$PYTHON" "$OPS/validate_pairs.py" && echo "[cron_daily] validate_pairs OK" || echo "[cron_daily] WARN: validate_pairs falló"

echo "[cron_daily] $(date -u +'%F %T') UTC — fin"

# Rotación simple de logs (mantener últimas 2 semanas)
find "$LOG_DIR" -name "*.log" -mtime +14 -delete 2>/dev/null || true
