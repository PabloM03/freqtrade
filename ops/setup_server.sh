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

# 4. Hacer ejecutable cron_daily.sh
chmod +x "$OPS/cron_daily.sh"

# 5. Registrar cron (evita duplicados)
TMPFILE=$(mktemp)
crontab -l 2>/dev/null | grep -v "cron_daily.sh" > "$TMPFILE" || true
echo "$CRON_CMD" >> "$TMPFILE"
crontab "$TMPFILE"
rm "$TMPFILE"
echo "[setup] Cron registrado: $CRON_CMD"

# 6. Test inmediato del pipeline
echo ""
echo "[setup] Ejecutando pipeline de prueba (dry-run)..."
python3 "$OPS/analyze_news.py" --dry-run

echo ""
echo "======================================================"
echo "  Setup completo. El pipeline correrá cada día a 00:10 UTC."
echo "  Para ver logs: tail -f $BASE/logs/cron_daily.log"
echo "======================================================"
