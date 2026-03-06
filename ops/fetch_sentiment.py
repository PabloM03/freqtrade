#!/usr/bin/env python3
"""
ops/fetch_sentiment.py — Pipeline de sentimiento crypto (fuentes 100% gratuitas, sin registro)
================================================================================================
Ejecutar diariamente (cron 00:05 UTC) para mantener todos los datos actualizados.

Fuentes:
  1. Fear & Greed Index (Alternative.me) — gratis, sin key
  2. CoinGecko whale volume detector — gratis, sin key, historial 365d
  3. CoinGecko trending coins — gratis, sin key (qué coins son hot hoy)
  4. Binance 24h volume spikes — gratis, sin key (detección de volumen anormal)
  5. RSS news sentiment (Cointelegraph / Decrypt / Reddit / Google News) — gratis, sin key

USO:
  python3 ops/fetch_sentiment.py              # todo
  python3 ops/fetch_sentiment.py --quick      # solo F&G
  python3 ops/fetch_sentiment.py --trending   # solo CoinGecko trending + Binance spikes
  python3 ops/fetch_sentiment.py --whales     # solo CoinGecko whale detector
  python3 ops/fetch_sentiment.py --news       # solo noticias RSS
"""

import json, csv, time, argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import urllib.request
import xml.etree.ElementTree as ET

ROOT     = Path(__file__).parent.parent
DATA_DIR = ROOT / "user_data" / "data" / "sentiment"
DATA_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0",
    "Accept": "application/json, text/html, */*",
}

COINS_COINGECKO = {
    "BTC":   "bitcoin",
    "SOL":   "solana",
    "LINK":  "chainlink",
    "PEPE":  "pepe",
    "SHIB":  "shiba-inu",
    "BONK":  "bonk",
    "WIF":   "dogwifcoin",
    "TURBO": "turbo",
    "FLOKI": "floki",
    "DOGE":  "dogecoin",
}

# Palabras clave para sentiment de noticias
BULLISH_WORDS = {
    "surge", "surged", "surges", "rally", "rallied", "bullish", "breakout", "ath",
    "all-time high", "adoption", "institutional", "etf approved", "launch", "upgrade",
    "accumulate", "buy", "partnership", "integration", "record", "milestone",
    "trump bitcoin", "pro-crypto", "strategic reserve", "hodl", "moon", "pump",
    "listing", "binance listing", "coinbase listing", "explode", "soar",
}
BEARISH_WORDS = {
    "crash", "crashed", "crashes", "plunge", "drop", "fell", "bearish", "hack", "hacked",
    "exploit", "ban", "banned", "regulation", "crackdown", "sell", "selloff", "fear",
    "uncertainty", "scam", "fraud", "sec", "lawsuit", "investigation", "dump", "dumped",
    "rug pull", "liquidation", "capitulation", "collapse", "warning", "risk",
}

COIN_KEYWORDS = {
    "BTC":   ["bitcoin", "btc", "#btc", "satoshi"],
    "SOL":   ["solana", "sol", "#sol"],
    "LINK":  ["chainlink", "link", "#link"],
    "PEPE":  ["pepe", "pepecoin", "$pepe"],
    "SHIB":  ["shiba", "shib", "#shib"],
    "BONK":  ["bonk", "#bonk", "$bonk"],
    "WIF":   ["dogwifhat", "wif", "#wif"],
    "TURBO": ["turbo", "$turbo"],
    "FLOKI": ["floki", "floki inu", "#floki"],
    "DOGE":  ["doge", "dogecoin", "#doge"],
}

RSS_FEEDS = [
    # Noticias crypto profesionales
    "https://cointelegraph.com/rss",
    "https://decrypt.co/feed",
    "https://cryptobriefing.com/feed/",
    # Reddit crypto (JSON API público, sin clave)
    "https://www.reddit.com/r/CryptoCurrency/.rss",
    "https://www.reddit.com/r/Bitcoin/.rss",
    "https://www.reddit.com/r/SatoshiStreetBets/.rss",
    # Google News RSS para crypto (sin registro, sin key)
    "https://news.google.com/rss/search?q=crypto+bitcoin&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=trump+bitcoin+crypto&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=altcoin+pump+rally&hl=en-US&gl=US&ceid=US:en",
]


# ── 1. Fear & Greed ────────────────────────────────────────────────────────────
def update_fear_greed():
    print("[F&G] Actualizando Fear & Greed Index...")
    url = "https://api.alternative.me/fng/?limit=0&date_format=us"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"[F&G] ERROR: {e}"); return

    out = DATA_DIR / "fear_greed.csv"
    rows = data["data"]
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "fear_greed"])
        for row in rows:
            dt = datetime.strptime(row["timestamp"], "%m-%d-%Y")
            w.writerow([dt.strftime("%Y-%m-%d"), int(row["value"])])
    print(f"[F&G] OK  {len(rows)} días → {out.name}")


# ── 2. CoinGecko Whale Volume Detector ─────────────────────────────────────────
def update_whale_volume(days: int = 365):
    """
    Descarga historial de volumen diario por coin (hasta 365d gratis).
    Detecta anomalías: vol > 2.5x media 30d = actividad de ballenas.
    whale_signal = +1 (acumulación bullish) / -1 (distribución bearish) / 0
    """
    print("[Whales] Actualizando detector de volumen de ballenas (CoinGecko)...")
    out = DATA_DIR / "whale_volume.csv"

    all_rows = {}
    if out.exists():
        with open(out) as f:
            for row in csv.DictReader(f):
                all_rows[(row["date"], row["coin"])] = row

    for coin_sym, cg_id in COINS_COINGECKO.items():
        url = (f"https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart"
               f"?vs_currency=usd&days={days}&interval=daily")
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
        except Exception as e:
            print(f"[Whales] {coin_sym}: {e}"); time.sleep(2); continue

        prices  = {int(p[0]): p[1] for p in data.get("prices", [])}
        volumes = {int(v[0]): v[1] for v in data.get("total_volumes", [])}

        daily = []
        for ts_ms, vol in sorted(volumes.items()):
            date = datetime.fromtimestamp(ts_ms/1000, tz=timezone.utc).strftime("%Y-%m-%d")
            price = prices.get(ts_ms, 0)
            daily.append({"date": date, "coin": coin_sym, "price": price, "volume": vol})

        for i, row in enumerate(daily):
            window_vols = [daily[j]["volume"] for j in range(max(0, i-30), i+1)]
            avg_vol = sum(window_vols) / len(window_vols) if window_vols else 1
            vol_ratio = row["volume"] / max(avg_vol, 1)

            if i > 0:
                price_change = (row["price"] - daily[i-1]["price"]) / max(daily[i-1]["price"], 1)
            else:
                price_change = 0

            if vol_ratio >= 2.5 and price_change > 0.01:
                whale_signal = 1
            elif vol_ratio >= 2.5 and price_change < -0.01:
                whale_signal = -1
            else:
                whale_signal = 0

            key = (row["date"], coin_sym)
            all_rows[key] = {
                "date": row["date"], "coin": coin_sym,
                "vol_ratio": round(vol_ratio, 2),
                "price_chg": round(price_change * 100, 2),
                "whale_signal": whale_signal,
            }

        print(f"[Whales] {coin_sym}: {len(daily)} días OK")
        time.sleep(1.5)

    rows = sorted(all_rows.values(), key=lambda x: (x["date"], x["coin"]))
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "coin", "vol_ratio", "price_chg", "whale_signal"])
        w.writeheader(); w.writerows(rows)
    print(f"[Whales] OK  {len(rows)} registros → {out.name}")


# ── 3. CoinGecko Trending Coins ───────────────────────────────────────────────
def update_coingecko_trending():
    """
    Obtiene los 7 coins más buscados en CoinGecko hoy.
    Los coins trending suelen subir 10-50% en las próximas 24-48h.
    Guarda: trending_coins.json con fecha, coin_id, rank.
    """
    print("[Trending] Actualizando CoinGecko trending coins...")
    url = "https://api.coingecko.com/api/v3/search/trending"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"[Trending] ERROR: {e}"); return

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    coins = []
    for item in data.get("coins", []):
        coin = item.get("item", {})
        coins.append({
            "rank": coin.get("score", 0),
            "coin_id": coin.get("id", ""),
            "symbol": coin.get("symbol", "").upper(),
            "name": coin.get("name", ""),
        })

    out = DATA_DIR / "trending_coins.json"
    history = []
    if out.exists():
        try:
            history = json.loads(out.read_text())
        except:
            history = []

    # Eliminar entradas del día actual y añadir las nuevas
    history = [e for e in history if e.get("date") != today]
    history.append({"date": today, "coins": coins})
    history = history[-90:]  # mantener 90 días de histórico

    out.write_text(json.dumps(history, indent=2))
    symbols = [c["symbol"] for c in coins]
    print(f"[Trending] {today}: {', '.join(symbols)} → {out.name}")

    # También guardar versión CSV por coin para el backtesting
    csv_out = DATA_DIR / "trending_coins.csv"
    existing_rows = []
    if csv_out.exists():
        with open(csv_out) as f:
            existing_rows = [r for r in csv.DictReader(f) if r["date"] != today]

    new_rows = []
    for entry in history[-1:]:  # solo hoy
        for coin in entry["coins"]:
            new_rows.append({
                "date": today,
                "symbol": coin["symbol"],
                "rank": coin["rank"],
            })

    with open(csv_out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "symbol", "rank"])
        w.writeheader()
        w.writerows(existing_rows + new_rows)

    return coins


# ── 4. Binance 24h Volume Spikes ──────────────────────────────────────────────
def update_binance_volume_spikes():
    """
    Detecta pares USDC en Binance con volumen 24h anormalmente alto.
    Usa la API pública de Binance (sin key, sin registro).
    Un spike de volumen suele preceder o acompañar a grandes movimientos.
    """
    print("[Binance] Detectando spikes de volumen (API pública)...")

    # Tickers de nuestros pares de interés
    our_symbols = [
        "BTCUSDC", "SOLUSDC", "LINKUSDC", "PEPEUSDC", "SHIBUSDC",
        "BONKUSDC", "WIFUSDC", "TURBOUSDC", "FLOKIUSDC", "DOGEUSDC",
    ]

    url = "https://api.binance.com/api/v3/ticker/24hr"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=20) as r:
            all_tickers = json.loads(r.read())
    except Exception as e:
        print(f"[Binance] ERROR: {e}"); return

    # Filtrar nuestros pares
    tickers = {t["symbol"]: t for t in all_tickers if t["symbol"] in our_symbols}

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = DATA_DIR / "binance_volume.csv"

    existing_rows = []
    if out.exists():
        with open(out) as f:
            existing_rows = [r for r in csv.DictReader(f) if r["date"] != today]

    new_rows = []
    for sym, ticker in sorted(tickers.items()):
        coin = sym.replace("USDC", "")
        vol_usdc = float(ticker.get("quoteVolume", 0))
        price_change_pct = float(ticker.get("priceChangePercent", 0))
        count = int(ticker.get("count", 0))  # number of trades

        new_rows.append({
            "date": today,
            "coin": coin,
            "vol_usdc": round(vol_usdc, 0),
            "price_chg_24h": round(price_change_pct, 2),
            "trade_count": count,
        })
        direction = "↑" if price_change_pct > 0 else "↓"
        print(f"  {coin:8s}: vol=${vol_usdc/1e6:.1f}M  {direction}{abs(price_change_pct):.1f}%  trades={count:,}")

    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "coin", "vol_usdc", "price_chg_24h", "trade_count"])
        w.writeheader()
        w.writerows(existing_rows + new_rows)

    print(f"[Binance] {len(new_rows)} pares → {out.name}")
    return new_rows


# ── 5. RSS News Sentiment ──────────────────────────────────────────────────────
def fetch_rss_sentiment(hours_back: int = 24):
    """
    Analiza noticias RSS de las últimas N horas y genera score por coin.
    Fuentes: Cointelegraph, Decrypt, Reddit, Google News — GRATIS, sin key.
    """
    print(f"[RSS] Analizando noticias crypto de las últimas {hours_back}h...")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    coin_scores = {c: [] for c in COIN_KEYWORDS}
    total_articles = 0
    source_stats = []

    for feed_url in RSS_FEEDS:
        try:
            req = urllib.request.Request(
                feed_url,
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/rss+xml,*/*"}
            )
            with urllib.request.urlopen(req, timeout=12) as r:
                raw = r.read()
            root = ET.fromstring(raw)
        except Exception as e:
            print(f"[RSS] SKIP {feed_url.split('/')[2]}: {e}"); continue

        feed_articles = 0
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").lower()
            desc  = (item.findtext("description") or "").lower()
            text  = title + " " + desc
            pub   = item.findtext("pubDate") or ""

            # Parsear fecha
            try:
                from email.utils import parsedate_to_datetime
                pub_dt = parsedate_to_datetime(pub)
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                if pub_dt < cutoff:
                    continue
            except:
                pass  # Si no podemos parsear la fecha, incluir igual

            for coin, keywords in COIN_KEYWORDS.items():
                if any(kw in text for kw in keywords):
                    bull = sum(1 for w in BULLISH_WORDS if w in text)
                    bear = sum(1 for w in BEARISH_WORDS if w in text)
                    if bull + bear > 0:
                        score = (bull - bear) / (bull + bear)
                        coin_scores[coin].append(score)

            total_articles += 1
            feed_articles += 1

        source = feed_url.split('/')[2].replace("www.", "").replace("news.google.com", "GoogleNews")
        source_stats.append(f"{source}:{feed_articles}")

    # Guardar score diario
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = DATA_DIR / "rss_sentiment.csv"
    existing = []
    if out.exists():
        with open(out) as f:
            existing = [r for r in csv.DictReader(f) if r["date"] != today]

    new_rows = []
    for coin, scores in coin_scores.items():
        avg_score = round(sum(scores)/len(scores), 3) if scores else 0.0
        new_rows.append({
            "date": today, "coin": coin,
            "score": avg_score, "articles": len(scores)
        })

    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "coin", "score", "articles"])
        w.writeheader()
        w.writerows(existing + new_rows)

    print(f"[RSS] {total_articles} artículos | {' | '.join(source_stats)}")
    for r in sorted(new_rows, key=lambda x: -abs(x["score"])):
        if r["articles"] > 0:
            sentiment = "BULLISH" if r["score"] > 0.1 else "BEARISH" if r["score"] < -0.1 else "neutral"
            print(f"      {r['coin']:6s}: {r['score']:+.2f} ({r['articles']} arts) → {sentiment}")


# ── Main ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick",    action="store_true", help="Solo F&G")
    parser.add_argument("--trending", action="store_true", help="Solo CoinGecko trending + Binance spikes")
    parser.add_argument("--whales",   action="store_true", help="Solo whale volume detector")
    parser.add_argument("--news",     action="store_true", help="Solo noticias RSS")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  Sentiment Pipeline — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    if args.quick:
        update_fear_greed()
    elif args.trending:
        update_coingecko_trending()
        update_binance_volume_spikes()
    elif args.whales:
        update_whale_volume()
    elif args.news:
        fetch_rss_sentiment()
    else:
        update_fear_greed()
        update_whale_volume()
        update_coingecko_trending()
        update_binance_volume_spikes()
        fetch_rss_sentiment()

    print("\nDone.\n")
