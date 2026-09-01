#!/usr/bin/env bash
# ops/daily_report.sh — Reporte técnico diario → Telegram
# Crontab (servidor): 0 7 * * * → 9:00 AM hora España (UTC+2 verano)
set -euo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$BASE"

TOKEN=$(python3 -c "import json; c=json.load(open('$BASE/ops/config.secrets.json')); print(c['telegram']['token'])")
CHAT=$(python3 -c  "import json; c=json.load(open('$BASE/ops/config.secrets.json')); print(c['telegram']['chat_id'])")

MSG=$(python3 - <<'PYEOF'
import json, csv, sqlite3, subprocess, os
from datetime import datetime, timedelta

base = '/home/ubuntu/freqtrade'
today = datetime.utcnow().date()
week_ago = today - timedelta(days=7)
L = []

# ── Cabecera ─────────────────────────────────────────────────────────────────
week_start = (today - timedelta(days=7)).strftime('%d %b')
week_end   = today.strftime('%d %b %Y')
L.append(f"📊 Reporte Diario — {today.strftime('%d %b %Y')}")
L.append(f"_{week_start} → {week_end}_")
L.append('')

# ── Estado del servicio ───────────────────────────────────────────────────────
try:
    status = subprocess.check_output(['systemctl','is-active','freqtrade'],text=True).strip()
except: status = 'unknown'
svc_icon = '✅' if status == 'active' else '🚨'

try:
    since = subprocess.check_output(
        ['systemctl','show','freqtrade','--property=ActiveEnterTimestamp','--value'],
        text=True).strip().replace(' UTC','')
    since = ' '.join(since.split()[:2])
except: since = '?'

try:
    nprocs = int(subprocess.check_output(['pgrep','-c','-f','freqtrade trade'],text=True).strip())
except: nprocs = 0
proc_msg = '✅ 1 proceso' if nprocs <= 1 else f'⚠️ DUPLICADO — {nprocs} instancias'

try:
    df_out = subprocess.check_output(['df','-h',base],text=True).splitlines()
    parts  = df_out[1].split()
    disk_pct, disk_free = parts[4], parts[3]
    disk_icon = '⚠️' if int(disk_pct.rstrip('%')) > 85 else '✅'
except: disk_pct, disk_free, disk_icon = '?','?','⚠️'

try:
    mem = subprocess.check_output(['free','-h'],text=True).splitlines()
    mp  = [l for l in mem if l.startswith('Mem:')][0].split()
    mem_used, mem_total = mp[2], mp[1]
except: mem_used, mem_total = '?','?'

L.append('🤖 Estado del servidor')
L.append(f'• Bot: {svc_icon} {status} (desde {since})')
L.append(f'• Procesos: {proc_msg}')
L.append(f'• Disco: {disk_icon} {disk_pct} usado ({disk_free} libres)')
L.append(f'• Memoria: {mem_used} / {mem_total}')
L.append('')

# ── Operaciones ───────────────────────────────────────────────────────────────
try:
    conn = sqlite3.connect(f'{base}/trades.sqlite')
    w7   = (datetime.utcnow()-timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
    closed = conn.execute('''
        SELECT COUNT(*), SUM(CASE WHEN close_profit_abs>0 THEN 1 ELSE 0 END),
               ROUND(SUM(close_profit_abs),2)
        FROM trades WHERE is_open=0 AND close_date>?''',(w7,)).fetchone()
    open_t = conn.execute('SELECT COUNT(*) FROM trades WHERE is_open=1').fetchone()[0]
    total,wins,profit = (closed[0] or 0),int(closed[1] or 0),(closed[2] or 0.0)
    wr = f'{wins/total*100:.1f}%' if total else '—'
    best  = conn.execute('''SELECT pair,ROUND(close_profit_abs,2) FROM trades
        WHERE is_open=0 AND close_date>? ORDER BY close_profit_abs DESC LIMIT 1''',(w7,)).fetchone()
    worst = conn.execute('''SELECT pair,ROUND(close_profit_abs,2) FROM trades
        WHERE is_open=0 AND close_date>? ORDER BY close_profit_abs ASC  LIMIT 1''',(w7,)).fetchone()
    profit_icon = '📈' if profit > 0 else ('📉' if profit < 0 else '➖')
    L.append(f'{profit_icon} Operaciones últimos 7 días')
    L.append(f'• Trades cerrados: {total}')
    L.append(f'• Win rate: {wr} ({wins}W)')
    L.append(f'• Profit: {profit:+.2f} USD')
    L.append(f'• Trades abiertos ahora: {open_t}')
    if best:  L.append(f'• Mejor trade:  {best[0]}  +{best[1]} USD')
    if worst: L.append(f'• Peor trade:   {worst[0]}  {worst[1]} USD')
except Exception as e:
    L.append(f'⚠️ Operaciones: error — {e}')
L.append('')

# ── Fear & Greed ──────────────────────────────────────────────────────────────
def fg_label(v):
    return ('Miedo Extremo' if v<25 else 'Miedo' if v<45 else 'Neutral' if v<55
            else 'Codicia' if v<75 else 'Codicia Extrema')
def fg_emoji(v):
    return '😱' if v<25 else '😨' if v<45 else '😐' if v<55 else '😏' if v<75 else '🤑'

fg_week = []
try:
    with open(f'{base}/user_data/data/sentiment/fear_greed.csv') as f:
        for row in csv.DictReader(f):
            d = datetime.strptime(row['date'],'%Y-%m-%d').date()
            if d < week_ago: break
            fg_week.append((row['date'], int(row['fear_greed'])))
    fg_stale = fg_week and (today - datetime.strptime(fg_week[0][0],'%Y-%m-%d').date()).days > 2
except: fg_stale = True

fg_icon = '⚠️' if fg_stale else '✅'
L.append(f'🧠 Sentimiento — Fear & Greed  {fg_icon}')
if fg_week:
    avg = sum(v for _,v in fg_week) / len(fg_week)
    v0  = fg_week[0][1]
    trend = '  '.join(f'{fg_emoji(v)}{v}' for _,v in fg_week[:7])
    L.append(f'• Hoy: {v0}/100 — {fg_label(v0)}  |  media 7d: {avg:.0f}')
    L.append(f'• {trend}')
else:
    L.append('• Sin datos de F&G')
L.append('')

# ── Noticias IA ───────────────────────────────────────────────────────────────
def clean(s, n=90):
    s = s.replace('_','').replace('*','').replace('`','').replace('[','').replace(']','')
    return (s[:n]+'...') if len(s)>n else s

try:
    cfg = json.load(open(f'{base}/config.base.json'))
    wl  = set(p.split('/')[0] for p in cfg['exchange']['pair_whitelist'])
except: wl = set()

try:
    history = json.load(open(f'{base}/user_data/data/sentiment/news_themes.json'))
    latest  = next((e for e in reversed(history) if e.get('date')), None)
    if latest:
        nd      = latest['date']
        n_stale = (today - datetime.strptime(nd,'%Y-%m-%d').date()).days > 2
        n_icon  = '⚠️' if n_stale else '✅'
        sigs    = latest.get('coin_signals',[])
        by_score= sorted(sigs, key=lambda x: float(x.get('ai_score',0)), reverse=True)
        bulls   = [(s['coin'],float(s.get('ai_score',0)),s.get('reason',''))
                   for s in by_score if float(s.get('ai_score',0))>=0.3][:4]
        bears   = [(s['coin'],float(s.get('ai_score',0)),s.get('reason',''))
                   for s in by_score if float(s.get('ai_score',0))<=-0.3][-3:]

        L.append(f'📰 Noticias IA — mercado  {n_icon} {nd}  ({latest.get("articles_analyzed","?")} arts)')
        if bulls:
            for coin,score,reason in bulls:
                L.append(f'  📈 {coin} ({score:+.2f}): {clean(reason)}')
        if bears:
            for coin,score,reason in reversed(bears):
                L.append(f'  📉 {coin} ({score:+.2f}): {clean(reason)}')
        if not bulls and not bears:
            L.append('  Sin señales fuertes (todos entre -0.3 y +0.3)')
        L.append('')

        wl_sigs = sorted([(s['coin'],float(s.get('ai_score',0)),s.get('reason',''))
                           for s in sigs if s['coin'] in wl],
                          key=lambda x: x[1], reverse=True)
        L.append('🎯 Noticias IA — tus pares')
        if wl_sigs:
            for coin,score,reason in wl_sigs:
                arrow = '📈' if score>=0.2 else ('📉' if score<=-0.2 else '➖')
                L.append(f'  {arrow} {coin} ({score:+.2f}): {clean(reason)}')
        else:
            L.append('  Sin señales para los pares activos hoy')
        L.append('')
except Exception as e:
    L.append(f'⚠️ Noticias IA: error — {e}')
    L.append('')

# ── Infraestructura ───────────────────────────────────────────────────────────
L.append('🔧 Infraestructura')
try:
    cmd = "journalctl -u freqtrade --since '24 hours ago' 2>/dev/null | grep -ci 'error\\|exception\\|critical' || true"
    rerr = int(subprocess.check_output(cmd,shell=True,text=True).strip() or '0')
    err_icon = '⚠️' if rerr > 20 else '✅'
    L.append(f'• Errores en log (24h): {err_icon} {rerr}')
except: L.append('• Errores en log (24h): ?')

try:
    last_cron = subprocess.check_output(
        f"grep '\\[cron_daily\\].*fin' {base}/logs/cron_daily.log | tail -1 | grep -oP '\\d{{4}}-\\d{{2}}-\\d{{2}} \\d{{2}}:\\d{{2}}:\\d{{2}}' || echo '?'",
        shell=True,text=True).strip()
    cron_icon = '✅' if last_cron != '?' else '⚠️'
    L.append(f'• Ultimo cron diario: {cron_icon} {last_cron} UTC')
except: L.append('• Ultimo cron diario: ?')

print('\n'.join(L))
PYEOF
)

RESP=$(curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    -d chat_id="${CHAT}" \
    --data-urlencode "text=${MSG}")

OK=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin).get('ok','?'))" 2>/dev/null || echo '?')
if [ "$OK" != "True" ] && [ "$OK" != "true" ]; then
    echo "[daily_report] ERROR Telegram: $RESP" >&2
else
    echo "[daily_report] $(date -u '+%Y-%m-%d %H:%M:%S') UTC — enviado OK"
fi
