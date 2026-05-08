#!/usr/bin/env bash
# ops/setup_server.sh — Setup único del servidor (correr UNA VEZ tras clonar/desplegar)
# ======================================================================================
# Instala dependencias Python, configura ops/.env y registra el cron diario.
#
# USO:
#   cd ~/freqtrade
#   bash ops/setup_server.sh [TAVILY_API_KEY] [ANTHROPIC_API_KEY]
#
# Ejemplo:
#   bash ops/setup_server.sh tvly-dev-xxxxx
#   bash ops/setup_server.sh tvly-dev-xxxxx sk-ant-xxxxx
#
# Si no se pasan argumentos, solo instala dependencias y registra el cron
# (asume que ops/.env ya está configurado manualmente).

set -euo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
OPS="$BASE/ops"
ENV_FILE="$OPS/.env"
CRON_CMD="10 0 * * * $OPS/cron_daily.sh >> $BASE/logs/cron_daily.log 2>&1"
# Hyperopt trimestral: 1 ene, 1 abr, 1 jul, 1 oct a las 02:00 UTC (ventana últimos 24 meses)
# NO auto-despliega — resultado queda en logs/hyperopt_*.log para revisión manual
CRON_HYPEROPT="0 2 1 1,4,7,10 * $OPS/run_hyperopt.sh >> $BASE/logs/hyperopt_cron.log 2>&1"

echo "======================================================"
echo "  Freqtrade Server Setup"
echo "  Base: $BASE"
echo "======================================================"

# 1. Crear directorios necesarios
mkdir -p "$BASE/logs"
echo "[setup] Directorios OK"

# 2. Instalar dependencias Python
echo "[setup] Instalando dependencias Python..."
pip install tavily-python --break-system-packages -q 2>/dev/null || \
  pip install tavily-python -q 2>/dev/null || \
  echo "  WARN: no se pudo instalar tavily-python (fallback a RSS)"

# anthropic es opcional — no falla si no se puede instalar
pip install anthropic --break-system-packages -q 2>/dev/null || \
  pip install anthropic -q 2>/dev/null || \
  echo "  INFO: anthropic no instalado (opcional — usará keywords)"

echo "[setup] Dependencias OK"

# 3. Configurar ops/.env
touch "$ENV_FILE"

TAVILY_KEY="${1:-}"
ANTHROPIC_KEY="${2:-}"

if [[ -n "$TAVILY_KEY" ]]; then
  if grep -q "TAVILY_API_KEY" "$ENV_FILE" 2>/dev/null; then
    sed -i "s|TAVILY_API_KEY=.*|TAVILY_API_KEY=$TAVILY_KEY|" "$ENV_FILE"
  else
    echo "TAVILY_API_KEY=$TAVILY_KEY" >> "$ENV_FILE"
  fi
  echo "[setup] TAVILY_API_KEY configurada"
fi

if [[ -n "$ANTHROPIC_KEY" ]]; then
  if grep -q "ANTHROPIC_API_KEY" "$ENV_FILE" 2>/dev/null; then
    sed -i "s|ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=$ANTHROPIC_KEY|" "$ENV_FILE"
  else
    echo "ANTHROPIC_API_KEY=$ANTHROPIC_KEY" >> "$ENV_FILE"
  fi
  echo "[setup] ANTHROPIC_API_KEY configurada"
fi

echo "[setup] ops/.env:"
cat "$ENV_FILE" | grep -v "^#" | grep "=" | sed 's/=.*/=***/'

# 4. Hacer ejecutables los scripts ops
chmod +x "$OPS/cron_daily.sh"
chmod +x "$OPS/run_hyperopt.sh"

# 5. Registrar crons (evita duplicados)
TMPFILE=$(mktemp)
crontab -l 2>/dev/null | grep -v "cron_daily.sh" | grep -v "run_hyperopt.sh" > "$TMPFILE" || true
echo "$CRON_CMD" >> "$TMPFILE"
echo "$CRON_HYPEROPT" >> "$TMPFILE"
crontab "$TMPFILE"
rm "$TMPFILE"
echo "[setup] Cron diario:     $CRON_CMD"
echo "[setup] Cron trimestral: $CRON_HYPEROPT"

# 6. Test inmediato del pipeline
echo ""
echo "[setup] Ejecutando pipeline de prueba (dry-run)..."
python3 "$OPS/analyze_news.py" --dry-run

echo ""
echo "======================================================"
echo "  Setup completo. Pipeline:"
echo "    - Diario 00:10 UTC: fetch_sentiment + analyze_news + validate_pairs (lunes)"
echo "    - Trimestral 02:00 UTC (1 ene/abr/jul/oct): hyperopt (24 meses, sin auto-deploy)"
echo "  Logs: $BASE/logs/"
echo "======================================================"
