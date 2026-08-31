#!/usr/bin/env bash
# ops/weekly_report.sh — Reporte técnico semanal → Telegram
# Crontab (servidor): 0 7 * * 1 → lunes 9:00 AM hora España (UTC+2 verano / UTC+1 invierno ajustar)
set -euo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$BASE"

TOKEN=$(python3 -c "import json; c=json.load(open('$BASE/ops/config.secrets.json')); print(c['telegram']['token'])")
CHAT=$(python3 -c  "import json; c=json.load(open('$BASE/ops/config.secrets.json')); print(c['telegram']['chat_id'])")

# ── 1. Estado del servicio ─────────────────────────────────────────────────
SERVICE_STATUS=$(systemctl is-active freqtrade 2>/dev/null || echo "unknown")
if [ "$SERVICE_STATUS" = "active" ]; then SVC_ICON="✅"; else SVC_ICON="🚨"; fi

SINCE=$(systemctl show freqtrade --property=ActiveEnterTimestamp --value 2>/dev/null \
        | sed 's/ UTC//' | awk '{print $1, $2}' || echo "desconocido")

# ── 2. Procesos duplicados ─────────────────────────────────────────────────
FT_PROCS=$(pgrep -c -f "freqtrade trade" 2>/dev/null || echo "0")
if [ "$FT_PROCS" -gt 1 ] 2>/dev/null; then
    PROC_MSG="⚠️ DUPLICADO — ${FT_PROCS} instancias corriendo"
else
    PROC_MSG="✅ 1 proceso"
fi

# ── 3. Operaciones últimos 7 días (SQLite) ─────────────────────────────────
TRADES_INFO=$(python3 - <<'PYEOF'
import sqlite3, datetime, os

db = os.path.expanduser('/home/ubuntu/freqtrade/trades.sqlite')
try:
    conn = sqlite3.connect(db)
    week_ago = (datetime.datetime.utcnow() - datetime.timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')

    closed = conn.execute('''
        SELECT COUNT(*),
               SUM(CASE WHEN close_profit_abs > 0 THEN 1 ELSE 0 END),
               ROUND(SUM(close_profit_abs), 2)
        FROM trades
        WHERE is_open=0 AND close_date > ?
    ''', (week_ago,)).fetchone()

    open_t = conn.execute('SELECT COUNT(*) FROM trades WHERE is_open=1').fetchone()[0]

    total = closed[0] or 0
    wins  = int(closed[1] or 0)
    profit = closed[2] or 0.0
    wr = f"{wins/total*100:.1f}%" if total else "—"

    # Mejor y peor trade de la semana
    best = conn.execute('''
        SELECT pair, ROUND(close_profit_abs,2) FROM trades
        WHERE is_open=0 AND close_date > ? ORDER BY close_profit_abs DESC LIMIT 1
    ''', (week_ago,)).fetchone()
    worst = conn.execute('''
        SELECT pair, ROUND(close_profit_abs,2) FROM trades
        WHERE is_open=0 AND close_date > ? ORDER BY close_profit_abs ASC LIMIT 1
    ''', (week_ago,)).fetchone()

    print(f"{total}|{wins}|{wr}|{profit}|{open_t}|{best[0] if best else '—'}|{best[1] if best else 0}|{worst[0] if worst else '—'}|{worst[1] if worst else 0}")
except Exception as e:
    print(f"0|0|—|0|0|—|0|—|0|ERR:{e}")
PYEOF
)

TOTAL=$(echo "$TRADES_INFO" | cut -d'|' -f1)
WINS=$( echo "$TRADES_INFO" | cut -d'|' -f2)
WR=$(   echo "$TRADES_INFO" | cut -d'|' -f3)
PROFIT=$(echo "$TRADES_INFO" | cut -d'|' -f4)
OPEN=$(  echo "$TRADES_INFO" | cut -d'|' -f5)
BEST_PAIR=$(echo "$TRADES_INFO" | cut -d'|' -f6)
BEST_PNL=$( echo "$TRADES_INFO" | cut -d'|' -f7)
WORST_PAIR=$(echo "$TRADES_INFO" | cut -d'|' -f8)
WORST_PNL=$( echo "$TRADES_INFO" | cut -d'|' -f9)

if   (( $(echo "$PROFIT > 0" | bc -l) )); then PROFIT_ICON="📈"
elif (( $(echo "$PROFIT < 0" | bc -l) )); then PROFIT_ICON="📉"
else PROFIT_ICON="➖"; fi

# ── 4. Errores en logs (últimas 168h) ─────────────────────────────────────
LOG_FILE="$BASE/logs/freqtrade.log"
if [ -f "$LOG_FILE" ]; then
    ERRORS=$(grep -c -i "error\|exception\|critical" "$LOG_FILE" 2>/dev/null || echo "0")
    # Errores en las últimas 24h (para detectar picos recientes)
    RECENT_ERRORS=$(awk -v d="$(date -u -d '24 hours ago' '+%Y-%m-%d')" '$0 >= d' "$LOG_FILE" 2>/dev/null \
                    | grep -c -i "error\|exception\|critical" || echo "0")
else
    ERRORS=0; RECENT_ERRORS=0
fi
if [ "$RECENT_ERRORS" -gt 20 ] 2>/dev/null; then ERR_ICON="⚠️"; else ERR_ICON="✅"; fi

# ── 5. Estado del cron diario ──────────────────────────────────────────────
LAST_CRON_LINE=$(grep "\[cron_daily\].*fin" "$BASE/logs/cron_daily.log" 2>/dev/null | tail -1 || echo "")
if [ -n "$LAST_CRON_LINE" ]; then
    LAST_CRON=$(echo "$LAST_CRON_LINE" | grep -oP '\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}' || echo "?")
    CRON_ICON="✅"
else
    LAST_CRON="sin registros"
    CRON_ICON="⚠️"
fi

CRON_ERRORS=$(grep -c -i "error\|fail\|ERR" "$BASE/logs/cron_daily.log" 2>/dev/null | tail -168 || echo "0")

# ── 6. Recursos del servidor ───────────────────────────────────────────────
DISK_PCT=$(df -h "$BASE" | tail -1 | awk '{print $5}')
DISK_FREE=$(df -h "$BASE" | tail -1 | awk '{print $4}')
MEM_USED=$(free -h | awk '/^Mem:/{print $3}')
MEM_TOTAL=$(free -h | awk '/^Mem:/{print $2}')

DISK_NUM=${DISK_PCT/\%/}
if [ "$DISK_NUM" -gt 85 ] 2>/dev/null; then DISK_ICON="⚠️"; else DISK_ICON="✅"; fi

# ── 7. Sentimiento de mercado ──────────────────────────────────────────────
SENTIMENT_INFO=$(python3 - <<'PYEOF'
import json, csv, os, sys
from datetime import datetime, timedelta

base = '/home/ubuntu/freqtrade'
today = datetime.utcnow().date()

# Fear & Greed
fg_path = f'{base}/user_data/data/sentiment/fear_greed.csv'
fg_val = '?'
fg_date = None
fg_stale = True
try:
    with open(fg_path) as f:
        reader = csv.DictReader(f)
        row = next(reader)
        fg_date = datetime.strptime(row['date'], '%Y-%m-%d').date()
        fg_val = row['fear_greed']
        fg_stale = (today - fg_date).days > 2
except Exception as e:
    fg_val = f'ERR:{e}'

if int(fg_val) if fg_val.lstrip('-').isdigit() else 0:
    v = int(fg_val)
    if v < 25: fg_label = 'Extreme Fear'
    elif v < 45: fg_label = 'Fear'
    elif v < 55: fg_label = 'Neutral'
    elif v < 75: fg_label = 'Greed'
    else: fg_label = 'Extreme Greed'
else:
    fg_label = '?'

# AI news scores
news_path = f'{base}/user_data/data/sentiment/news_themes.json'
top_bull = []
top_bear = []
news_date = None
news_stale = True
try:
    history = json.loads(open(news_path).read())
    entry = next((e for e in reversed(history) if e.get('date')), None)
    if entry:
        news_date = entry.get('date')
        news_stale = (today - datetime.strptime(news_date, '%Y-%m-%d').date()).days > 2
        signals = entry.get('coin_signals', [])
        signals_sorted = sorted(signals, key=lambda x: float(x.get('ai_score', 0)), reverse=True)
        top_bull = [(s['coin'], float(s.get('ai_score', 0))) for s in signals_sorted if float(s.get('ai_score', 0)) >= 0.2][:3]
        top_bear = [(s['coin'], float(s.get('ai_score', 0))) for s in signals_sorted if float(s.get('ai_score', 0)) <= -0.2][-3:]
except Exception as e:
    news_date = f'ERR:{e}'

fg_icon = '⚠️' if fg_stale else '✅'
news_icon = '⚠️' if news_stale else '✅'

bull_str = ', '.join(f'{c}({s:+.2f})' for c, s in top_bull) if top_bull else 'ninguno'
bear_str = ', '.join(f'{c}({s:+.2f})' for c, s in top_bear) if top_bear else 'ninguno'

print(f'{fg_icon}|{fg_val}|{fg_label}|{fg_date}|{news_icon}|{news_date}|{bull_str}|{bear_str}')
PYEOF
)

FG_ICON=$(   echo "$SENTIMENT_INFO" | cut -d'|' -f1)
FG_VAL=$(    echo "$SENTIMENT_INFO" | cut -d'|' -f2)
FG_LABEL=$(  echo "$SENTIMENT_INFO" | cut -d'|' -f3)
FG_DATE=$(   echo "$SENTIMENT_INFO" | cut -d'|' -f4)
NEWS_ICON=$( echo "$SENTIMENT_INFO" | cut -d'|' -f5)
NEWS_DATE=$( echo "$SENTIMENT_INFO" | cut -d'|' -f6)
BULL_COINS=$(echo "$SENTIMENT_INFO" | cut -d'|' -f7)
BEAR_COINS=$(echo "$SENTIMENT_INFO" | cut -d'|' -f8)

# ── 8. Construir mensaje ───────────────────────────────────────────────────
WEEK_START=$(date -u -d '7 days ago' '+%d %b')
WEEK_END=$(date -u '+%d %b %Y')

MSG="📊 *Reporte Semanal — lunes $(date -u '+%d %b %Y')*
_${WEEK_START} → ${WEEK_END}_

🤖 *Estado del servidor*
• Bot: ${SVC_ICON} ${SERVICE_STATUS} (desde ${SINCE})
• Procesos: ${PROC_MSG}
• Disco: ${DISK_ICON} ${DISK_PCT} usado (${DISK_FREE} libres)
• Memoria: ${MEM_USED} / ${MEM_TOTAL}

${PROFIT_ICON} *Operaciones de la semana*
• Trades cerrados: ${TOTAL}
• Win rate: ${WR} (${WINS}W)
• Profit: ${PROFIT} USDC
• Trades abiertos ahora: ${OPEN}
• Mejor trade: ${BEST_PAIR} (+${BEST_PNL} USDC)
• Peor trade: ${WORST_PAIR} (${WORST_PNL} USDC)

🧠 *Sentimiento de mercado*
• Fear & Greed: ${FG_ICON} ${FG_VAL}/100 — ${FG_LABEL} (${FG_DATE})
• 📈 Bullish AI: ${BULL_COINS}
• 📉 Bearish AI: ${BEAR_COINS}
• Datos noticias: ${NEWS_ICON} ${NEWS_DATE}

🔧 *Infraestructura*
• Errores en log (24h): ${ERR_ICON} ${RECENT_ERRORS}
• Último cron diario: ${CRON_ICON} ${LAST_CRON}"

curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    -d chat_id="${CHAT}" \
    -d parse_mode='Markdown' \
    -d text="${MSG}" > /dev/null

echo "[weekly_report] $(date -u '+%Y-%m-%d %H:%M:%S') UTC — enviado OK"
