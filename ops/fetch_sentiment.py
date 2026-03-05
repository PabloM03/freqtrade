#!/usr/bin/env python3
"""
ops/fetch_sentiment.py — Pipeline completo de sentimiento y noticias
=====================================================================
Actualiza todos los datos de sentimiento usados por la estrategia.

Fuentes implementadas:
  1. Fear & Greed Index (Alternative.me) — GRATIS, sin registro
  2. CryptoPanic news + sentiment por coin — GRATIS con token (ver abajo)
  3. Google Trends (interés de búsqueda por coin) — GRATIS, sin registro
  4. Whale Alert (transacciones grandes BTC/ETH) — GRATIS con token

CONFIGURACIÓN REQUERIDA:
  Crea el archivo ops/.env con tus tokens:
    CRYPTOPANIC_TOKEN=tu_token_aqui     # gratis en cryptopanic.com/developers
    WHALE_ALERT_KEY=tu_key_aqui         # gratis en whale-alert.io/pricing (Free plan)

CÓMO EJECUTAR:
  python3 ops/fetch_sentiment.py            # actualización completa
  python3 ops/fetch_sentiment.py --quick    # solo F&G (sin rate limits)

CRON (actualización diaria a las 00:05 UTC):
  5 0 * * * cd /path/to/freqtrade && python3 ops/fetch_sentiment.py >> logs/sentiment.log 2>&1
"""

import os
import sys
import json
import time
import csv
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ─── Configuración ────────────────────────────────────────────────────────────
ROOT      = Path(__file__).parent.parent
DATA_DIR  = ROOT / "user_data" / "data" / "sentiment"
DATA_DIR.mkdir(parents=True, exist_ok=True)

ENV_FILE  = Path(__file__).parent / ".env"

def load_env():
    """Carga tokens desde ops/.env si existe."""
    tokens = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                tokens[k.strip()] = v.strip()
    return tokens

ENV = load_env()
CRYPTOPANIC_TOKEN = ENV.get("CRYPTOPANIC_TOKEN", "")
WHALE_ALERT_KEY   = ENV.get("WHALE_ALERT_KEY", "")

# Mapeado coin → keyword Google Trends
COIN_TRENDS_MAP = {
    "BTC":   "bitcoin",
    "SOL":   "solana",
    "LINK":  "chainlink crypto",
    "PEPE":  "pepe coin crypto",
    "SHIB":  "shiba inu coin",
    "BONK":  "bonk coin",
    "WIF":   "dog wif hat",
    "TURBO": "turbo memecoin",
}

# Mapeado coin → símbolo CryptoPanic
COIN_CP_MAP = {
    "BTC": "BTC", "SOL": "SOL", "LINK": "LINK",
    "PEPE": "PEPE", "SHIB": "SHIB", "BONK": "BONK",
    "WIF": "WIF", "TURBO": "TURBO",
}


# ─── 1. Fear & Greed Index ─────────────────────────────────────────────────────
def update_fear_greed():
    """Descarga/actualiza todo el historial del F&G Index."""
    import urllib.request
    print("[F&G] Descargando Fear & Greed histórico...")
    url = "https://api.alternative.me/fng/?limit=0&date_format=us"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"[F&G] ERROR: {e}")
        return

    out = DATA_DIR / "fear_greed.csv"
    rows = data["data"]
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "fear_greed"])
        for row in rows:
            from datetime import datetime
            dt = datetime.strptime(row["timestamp"], "%m-%d-%Y")
            w.writerow([dt.strftime("%Y-%m-%d"), int(row["value"])])
    print(f"[F&G] ✅  {len(rows)} días guardados → {out}")


# ─── 2. CryptoPanic news sentiment ────────────────────────────────────────────
def fetch_cryptopanic_coin(coin: str, pages: int = 5) -> list:
    """
    Descarga las últimas noticias de CryptoPanic para una moneda.
    Devuelve lista de {date, coin, score} donde score: +1 bullish, -1 bearish, 0 neutral
    """
    import urllib.request
    if not CRYPTOPANIC_TOKEN:
        return []

    results = []
    for page in range(1, pages + 1):
        url = (
            f"https://cryptopanic.com/api/free/v1/posts/"
            f"?auth_token={CRYPTOPANIC_TOKEN}"
            f"&currencies={coin}&public=true&page={page}"
        )
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                data = json.loads(r.read())
        except Exception as e:
            print(f"[CryptoPanic/{coin}] page {page} ERROR: {e}")
            break

        for post in data.get("results", []):
            pub = post.get("published_at", "")[:10]  # YYYY-MM-DD
            votes = post.get("votes", {})
            pos = votes.get("positive", 0) + votes.get("liked", 0)
            neg = votes.get("negative", 0) + votes.get("disliked", 0)
            if pos + neg == 0:
                score = 0
            else:
                score = round((pos - neg) / (pos + neg), 3)
            results.append({"date": pub, "coin": coin, "score": score})

        if not data.get("next"):
            break
        time.sleep(1.2)  # respetar rate limit

    return results


def update_cryptopanic(pages_per_coin: int = 10):
    """Actualiza el historial de sentimiento de noticias CryptoPanic."""
    if not CRYPTOPANIC_TOKEN:
        print("[CryptoPanic] ⚠️  Sin token — omitido (configura CRYPTOPANIC_TOKEN en ops/.env)")
        print("              → Regístrate gratis en: https://cryptopanic.com/developers/api/")
        return

    print(f"[CryptoPanic] Descargando noticias ({pages_per_coin} páginas por coin)...")
    out = DATA_DIR / "cryptopanic_sentiment.csv"

    # Cargar existente para no perder histórico
    existing = {}
    if out.exists():
        with open(out) as f:
            for row in csv.DictReader(f):
                key = (row["date"], row["coin"])
                existing[key] = float(row["score"])

    new_count = 0
    for coin in COIN_CP_MAP:
        posts = fetch_cryptopanic_coin(COIN_CP_MAP[coin], pages=pages_per_coin)
        for p in posts:
            key = (p["date"], p["coin"])
            if key not in existing:
                existing[key] = p["score"]
                new_count += 1
        time.sleep(2)

    # Guardar todo ordenado
    rows = [{"date": k[0], "coin": k[1], "score": v} for k, v in sorted(existing.items())]
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "coin", "score"])
        w.writeheader()
        w.writerows(rows)
    print(f"[CryptoPanic] ✅  {new_count} nuevos registros, total {len(rows)} → {out}")


# ─── 3. Google Trends ─────────────────────────────────────────────────────────
def update_google_trends(force: bool = False):
    """Actualiza Google Trends semanal para todos los pares."""
    out = DATA_DIR / "google_trends.json"

    # Solo actualizar si el archivo tiene más de 6 días
    if out.exists() and not force:
        mtime = datetime.fromtimestamp(out.stat().st_mtime)
        if (datetime.now() - mtime).days < 6:
            print("[Trends] ℹ️  Actualizado hace <6 días — omitido")
            return

    try:
        from pytrends.request import TrendReq
    except ImportError:
        print("[Trends] ⚠️  pytrends no instalado: conda install -c conda-forge pytrends")
        return

    print("[Trends] Descargando Google Trends...")
    pytrends = TrendReq(hl="en-US", tz=0, timeout=(10, 35))
    results = out.read_text() if out.exists() else "{}"
    data = json.loads(results)

    for coin, keyword in COIN_TRENDS_MAP.items():
        time.sleep(7)
        try:
            pytrends.build_payload([keyword], timeframe="2022-01-01 2026-03-04", geo="")
            df = pytrends.interest_over_time()
            if not df.empty and keyword in df.columns:
                data[coin] = {str(ts): int(v) for ts, v in df[keyword].items()}
                print(f"[Trends] {coin}: {len(df)} semanas OK")
        except Exception as e:
            print(f"[Trends] {coin} ERROR: {e}")

    out.write_text(json.dumps(data, indent=2))
    print(f"[Trends] ✅  Guardado → {out}")


# ─── 4. Whale Alert ───────────────────────────────────────────────────────────
def update_whale_alert(hours_back: int = 24):
    """
    Descarga transacciones de ballenas recientes (>$1M en BTC/ETH).
    Requiere: cuenta gratis en whale-alert.io → WHALE_ALERT_KEY en ops/.env
    """
    if not WHALE_ALERT_KEY:
        print("[Whales] ⚠️  Sin API key — omitido")
        print("          → Regístrate gratis en: https://whale-alert.io/pricing")
        print("          → Free plan: 10 req/min, 100 transacciones/req")
        return

    import urllib.request
    out = DATA_DIR / "whale_transactions.csv"

    since = int((datetime.now(timezone.utc) - timedelta(hours=hours_back)).timestamp())
    url = (
        f"https://api.whale-alert.io/v1/transactions"
        f"?api_key={WHALE_ALERT_KEY}&min_value=1000000&start={since}&limit=100"
    )
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"[Whales] ERROR: {e}")
        return

    txs = data.get("transactions", [])
    print(f"[Whales] {len(txs)} transacciones en últimas {hours_back}h")

    # Calcular señal de ballenas por coin
    whale_signals = {}
    for tx in txs:
        symbol = tx.get("symbol", "").upper()
        tx_type = tx.get("transaction_type", "")
        amount_usd = tx.get("amount_usd", 0)

        # Exchange inflow = posible venta próxima (bearish)
        # Exchange outflow = retiro a cold wallet (bullish)
        if "exchange" in tx.get("to", {}).get("owner_type", ""):
            signal = -1  # bearish
        elif "exchange" in tx.get("from", {}).get("owner_type", ""):
            signal = +1  # bullish
        else:
            signal = 0

        if symbol not in whale_signals:
            whale_signals[symbol] = {"bullish_usd": 0, "bearish_usd": 0, "count": 0}
        if signal > 0:
            whale_signals[symbol]["bullish_usd"] += amount_usd
        elif signal < 0:
            whale_signals[symbol]["bearish_usd"] += amount_usd
        whale_signals[symbol]["count"] += 1

    # Guardar señal diaria
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows_existing = []
    if out.exists():
        with open(out) as f:
            rows_existing = list(csv.DictReader(f))
        rows_existing = [r for r in rows_existing if r["date"] != today]

    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "coin", "bull_usd", "bear_usd", "score"])
        w.writeheader()
        w.writerows(rows_existing)
        for coin, s in whale_signals.items():
            total = s["bullish_usd"] + s["bearish_usd"]
            score = round((s["bullish_usd"] - s["bearish_usd"]) / max(total, 1), 3)
            w.writerow({"date": today, "coin": coin,
                        "bull_usd": int(s["bullish_usd"]),
                        "bear_usd": int(s["bearish_usd"]),
                        "score": score})
    print(f"[Whales] ✅  Señales guardadas → {out}")


# ─── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Actualiza todos los datos de sentimiento")
    parser.add_argument("--quick",   action="store_true", help="Solo F&G (sin rate limits)")
    parser.add_argument("--trends",  action="store_true", help="Forzar actualización Google Trends")
    parser.add_argument("--whales",  action="store_true", help="Solo Whale Alert")
    parser.add_argument("--news",    action="store_true", help="Solo CryptoPanic")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  Sentiment Pipeline — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    if args.whales:
        update_whale_alert()
    elif args.news:
        update_cryptopanic(pages_per_coin=20)
    elif args.quick:
        update_fear_greed()
    else:
        update_fear_greed()
        update_cryptopanic()
        update_google_trends(force=args.trends)
        update_whale_alert()

    print("\n✅ Pipeline completo.\n")
