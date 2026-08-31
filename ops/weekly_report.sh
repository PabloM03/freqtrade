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
SENTIMENT_BLOCK=$(python3 - <<'PYEOF'
import json, csv
from datetime import datetime, timedelta

base = '/home/ubuntu/freqtrade'
today = datetime.utcnow().date()
week_ago = today - timedelta(days=7)

# Fear & Greed — últimos 7 días
fg_path = f'{base}/user_data/data/sentiment/fear_greed.csv'
fg_week = []
fg_stale = True
try:
    with open(fg_path) as f:
        for row in csv.DictReader(f):
            d = datetime.strptime(row['date'], '%Y-%m-%d').date()
            if d < week_ago:
                break
            fg_week.append((row['date'], int(row['fear_greed'])))
    if fg_week:
        fg_stale = (today - datetime.strptime(fg_week[0][0], '%Y-%m-%d').date()).days > 2
except Exception as e:
    fg_week = []

def fg_label(v):
    if v < 25:   return 'Miedo Extremo'
    elif v < 45: return 'Miedo'
    elif v < 55: return 'Neutral'
    elif v < 75: return 'Codicia'
    else:        return 'Codicia Extrema'

def fg_emoji(v):
    if v < 25:   return '😱'
    elif v < 45: return '😨'
    elif v < 55: return '😐'
    elif v < 75: return '😏'
    else:        return '🤑'

fg_icon = '⚠️' if fg_stale else '✅'
if fg_week:
    avg_fg = sum(v for _, v in fg_week) / len(fg_week)
    today_fg = fg_week[0][1]
    fg_trend = ' '.join(f'{fg_emoji(v)}{v}' for _, v in fg_week[:5])
    fg_summary = f'{fg_icon} Hoy: *{today_fg}* ({fg_label(today_fg)}) — media semana: {avg_fg:.0f}\n  {fg_trend}'
else:
    fg_summary = '⚠️ Sin datos F&G'

# Whitelist activa
try:
    cfg = json.load(open(f'{base}/config.base.json'))
    whitelist_coins = set(p.split('/')[0] for p in cfg['exchange']['pair_whitelist'])
except Exception:
    whitelist_coins = set()

# AI news — últimos 7 días
news_path = f'{base}/user_data/data/sentiment/news_themes.json'
news_stale = True
news_lines = []
whitelist_lines = []
try:
    history = json.load(open(news_path))
    # Entrada más reciente
    latest = next((e for e in reversed(history) if e.get('date')), None)
    if latest:
        news_date = latest['date']
        news_stale = (today - datetime.strptime(news_date, '%Y-%m-%d').date()).days > 2
        signals = latest.get('coin_signals', [])

        # Coins del whitelist con score
        wl_signals = [(s['coin'], float(s.get('ai_score', 0)), s.get('reason', ''))
                      for s in signals if s['coin'] in whitelist_coins]
        wl_signals.sort(key=lambda x: x[1], reverse=True)
        for coin, score, reason in wl_signals:
            emoji = '📈' if score >= 0.2 else ('📉' if score <= -0.2 else '➖')
            short_reason = reason[:80] + '…' if len(reason) > 80 else reason
            whitelist_lines.append(f'  {emoji} *{coin}* ({score:+.2f}): _{short_reason}_')

        # Top 3 bullish y top 3 bearish de todo el mercado
        all_sorted = sorted(signals, key=lambda x: float(x.get('ai_score', 0)), reverse=True)
        top_bull = [(s['coin'], float(s.get('ai_score', 0)), s.get('reason', '')) for s in all_sorted if float(s.get('ai_score', 0)) >= 0.3][:3]
        top_bear = [(s['coin'], float(s.get('ai_score', 0)), s.get('reason', '')) for s in all_sorted if float(s.get('ai_score', 0)) <= -0.3][-3:]

        for coin, score, reason in top_bull:
            short_reason = reason[:80] + '…' if len(reason) > 80 else reason
            news_lines.append(f'  📈 *{coin}* ({score:+.2f}): _{short_reason}_')
        for coin, score, reason in top_bear[::-1]:
            short_reason = reason[:80] + '…' if len(reason) > 80 else reason
            news_lines.append(f'  📉 *{coin}* ({score:+.2f}): _{short_reason}_')

        if not news_lines:
            news_lines.append('  ➖ Sin señales fuertes hoy (todos entre -0.3 y +0.3)')
except Exception as e:
    news_lines = [f'  ⚠️ Error: {e}']
    news_date = '?'

news_icon = '⚠️' if news_stale else '✅'

print('FG_SUMMARY:' + fg_summary)
print('NEWS_ICON:' + news_icon)
print('NEWS_DATE:' + (news_date if 'news_date' in dir() else '?'))
print('NEWS_LINES:' + '\n'.join(news_lines) if news_lines else 'NEWS_LINES:ninguno')
print('WL_LINES:' + '\n'.join(whitelist_lines) if whitelist_lines else 'WL_LINES:sin datos en whitelist')
PYEOF
)

FG_SUMMARY=$(echo "$SENTIMENT_BLOCK" | grep '^FG_SUMMARY:' | sed 's/^FG_SUMMARY://')
NEWS_ICON=$( echo "$SENTIMENT_BLOCK" | grep '^NEWS_ICON:'  | sed 's/^NEWS_ICON://')
NEWS_DATE=$( echo "$SENTIMENT_BLOCK" | grep '^NEWS_DATE:'  | sed 's/^NEWS_DATE://')
NEWS_LINES=$(echo "$SENTIMENT_BLOCK" | sed -n '/^NEWS_LINES:/,/^WL_LINES:/{ /^NEWS_LINES:/{ s/^NEWS_LINES://; p }; /^WL_LINES:/d; p }')
WL_LINES=$(  echo "$SENTIMENT_BLOCK" | sed -n 's/^WL_LINES://p')

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

🧠 *Sentimiento — Fear & Greed*
${FG_SUMMARY}

📰 *Noticias IA — mercado* (${NEWS_ICON} ${NEWS_DATE})
${NEWS_LINES}

🎯 *Noticias IA — tus pares*
${WL_LINES}

🔧 *Infraestructura*
• Errores en log (24h): ${ERR_ICON} ${RECENT_ERRORS}
• Último cron diario: ${CRON_ICON} ${LAST_CRON}"

curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    -d chat_id="${CHAT}" \
    -d parse_mode='Markdown' \
    -d text="${MSG}" > /dev/null

echo "[weekly_report] $(date -u '+%Y-%m-%d %H:%M:%S') UTC — enviado OK"
