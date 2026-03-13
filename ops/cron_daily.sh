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

echo "[cron_daily] $(date -u +'%F %T') UTC — inicio"

# 1. Fear & Greed + CoinGecko trending + Binance spikes + RSS news
echo "[cron_daily] step 1: fetch_sentiment (Fear&Greed + trending + noticias)"
python3 "$OPS/fetch_sentiment.py" && echo "[cron_daily] fetch_sentiment OK" || echo "[cron_daily] WARN: fetch_sentiment falló (no fatal)"

# 2. Análisis temático — funciona con TAVILY_API_KEY o ANTHROPIC_API_KEY (o keywords fallback)
echo "[cron_daily] step 2: analyze_news (Tavily+keywords o Claude AI)"
python3 "$OPS/analyze_news.py" && echo "[cron_daily] analyze_news OK" || echo "[cron_daily] WARN: analyze_news falló (usará señal neutral)"

echo "[cron_daily] $(date -u +'%F %T') UTC — fin"

# Rotación simple de logs (mantener últimas 2 semanas)
find "$LOG_DIR" -name "*.log" -mtime +14 -delete 2>/dev/null || true
