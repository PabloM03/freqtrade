#!/usr/bin/env python3
"""
ops/analyze_news.py — Análisis temático de noticias crypto con Claude AI
=========================================================================
Diferencia clave vs sentiment simple (keywords bullish/bearish):
  - Keyword: "AI" aparece en noticia → sentiment neutro
  - Claude: "OpenAI lanza nuevo modelo" → tema: AI_crypto → LINK/SOL subirán
  - Claude: "Trump firma orden pro-crypto" → tema: macro_btc → todo sube
  - Claude: "SEC demanda a exchange" → tema: regulation → todo baja

El modelo interpreta el CONTEXTO y las CONSECUENCIAS para cada coin,
no solo si aparecen palabras clave.

Mapa temático para nuestras 8 monedas:
  BTC    — bitcoin macro, ETF, institutional, strategic reserve, halving
  SOL    — solana ecosystem, DeFi SOL, NFT SOL, AI en Solana
  LINK   — oráculos, AI+data, RWA (Real World Assets), DeFi data feeds
  PEPE   — meme coin general, virality, meme season
  SHIB   — shiba/doge meme, dog coins
  BONK   — meme Solana, Solana ecosystem meme
  WIF    — meme Solana, dog meme
  TURBO  — meme coin, AI-generated meme

USO:
  python3 ops/analyze_news.py              # analiza noticias RSS de hoy
  python3 ops/analyze_news.py --hours 48   # últimas 48h de noticias
  python3 ops/analyze_news.py --dry-run    # muestra análisis sin guardar

SALIDA:
  user_data/data/sentiment/news_themes.json   — señales diarias por coin
  user_data/data/sentiment/news_themes.csv    — histórico para backtest

REQUIERE:
  pip install anthropic  (o conda install -c conda-forge anthropic)
  ANTHROPIC_API_KEY en ops/.env
"""

import json, csv, time, argparse, urllib.request, xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT     = Path(__file__).parent.parent
DATA_DIR = ROOT / "user_data" / "data" / "sentiment"
DATA_DIR.mkdir(parents=True, exist_ok=True)
ENV_FILE = Path(__file__).parent / ".env"


def load_env() -> dict:
    tokens = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                tokens[k.strip()] = v.strip()
    return tokens

ENV = load_env()
ANTHROPIC_KEY = ENV.get("ANTHROPIC_API_KEY", "")

# ── Mapeo temático → coins afectadas ──────────────────────────────────────────
# Cada tema tiene sus coins "primarias" (directamente afectadas) y
# secundarias (indirectamente afectadas).
THEME_COIN_MAP = {
    "ai_crypto": {
        "primary":   ["LINK", "SOL"],          # oráculos AI + Solana AI ecosystem
        "secondary": ["BTC"],                  # momentum general
        "notes": "AI en blockchain: oráculos de datos (LINK), computación (SOL)"
    },
    "macro_btc": {
        "primary":   ["BTC"],
        "secondary": ["SOL", "LINK", "PEPE", "SHIB", "BONK", "WIF", "TURBO"],
        "notes": "BTC macro (ETF, institucional, reserva estratégica, halving)"
    },
    "defi": {
        "primary":   ["LINK", "SOL"],
        "secondary": ["BTC"],
        "notes": "DeFi, DEX, lending, oráculos de precio"
    },
    "meme_season": {
        "primary":   ["PEPE", "SHIB", "BONK", "WIF", "TURBO"],
        "secondary": ["DOGE"],
        "notes": "Meme coins en general, virality, social media frenzy"
    },
    "solana_ecosystem": {
        "primary":   ["SOL", "BONK", "WIF"],
        "secondary": ["TURBO"],
        "notes": "Actualizaciones de Solana, proyectos SOL, memes SOL"
    },
    "regulation_positive": {
        "primary":   ["BTC", "SOL", "LINK"],
        "secondary": ["PEPE", "SHIB", "BONK", "WIF", "TURBO"],
        "notes": "Regulación favorable, ETF aprobado, claridad legal"
    },
    "regulation_negative": {
        "primary":   ["BTC", "SOL", "LINK"],
        "secondary": ["PEPE", "SHIB", "BONK", "WIF", "TURBO"],
        "notes": "SEC, ban, demanda, prohibición"
    },
    "hack_exploit": {
        "primary":   [],
        "secondary": ["BTC", "SOL", "LINK"],
        "notes": "Hack de protocolo, exploit, pérdidas de fondos"
    },
    "btc_dominance_up": {
        "primary":   ["BTC"],
        "secondary": [],
        "notes": "BTC sube mientras altcoins caen (rotación a BTC)"
    },
    "altcoin_season": {
        "primary":   ["SOL", "LINK", "PEPE", "BONK", "WIF"],
        "secondary": ["TURBO", "SHIB"],
        "notes": "Altcoin season: rotación de BTC a altcoins"
    },
    "trump_crypto": {
        "primary":   ["BTC", "SOL"],
        "secondary": ["LINK", "PEPE", "BONK", "WIF", "TURBO"],
        "notes": "Trump, políticas pro-crypto, reserva estratégica"
    },
    "exchange_listing": {
        "primary":   [],   # se rellena dinámicamente si detecta el coin
        "secondary": [],
        "notes": "Listing en exchange mayor (Binance, Coinbase, etc.)"
    },
    "unrelated": {
        "primary":   [],
        "secondary": [],
        "notes": "Noticia no relacionada con crypto"
    },
}

OUR_COINS = ["BTC", "SOL", "LINK", "PEPE", "SHIB", "BONK", "WIF", "TURBO"]

RSS_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://decrypt.co/feed",
    "https://news.google.com/rss/search?q=crypto+bitcoin&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=trump+bitcoin+crypto&hl=en-US&gl=US&ceid=US:en",
    "https://www.reddit.com/r/CryptoCurrency/.rss",
]

ANALYSIS_PROMPT = """\
Eres un analista de trading crypto experto. Analiza este titular de noticias y determina \
su impacto en criptomonedas específicas.

Titular: {headline}
Descripción: {description}

Nuestras monedas: BTC, SOL, LINK, PEPE, SHIB, BONK, WIF, TURBO

Temas posibles:
- ai_crypto: Noticias de IA aplicada a blockchain (oráculos AI, computación descentralizada, agentes AI) → afecta LINK, SOL
- macro_btc: Bitcoin ETF, reserva estratégica, bancos comprando BTC, halving → afecta BTC y todo
- defi: DeFi, DEX, oráculos de precio → afecta LINK, SOL
- meme_season: Meme coins virales, tendencias sociales, meme season → afecta PEPE, SHIB, BONK, WIF, TURBO
- solana_ecosystem: Actualizaciones de Solana, TVL Solana, proyectos en SOL → afecta SOL, BONK, WIF
- regulation_positive: ETF aprobado, regulación favorable, claridad legal → bullish para todo
- regulation_negative: SEC, ban, demanda, ilegal → bearish para todo
- hack_exploit: Hack, exploit, pérdida de fondos → bearish específico o general
- trump_crypto: Trump, política pro-crypto, órdenes ejecutivas crypto → afecta BTC, SOL
- altcoin_season: Rotación a altcoins, BTC.D bajando → afecta altcoins
- exchange_listing: Listing en Binance/Coinbase de una coin → afecta esa coin específica
- unrelated: No relacionado con crypto o impacto mínimo

Devuelve EXACTAMENTE este JSON y nada más:
{{
  "theme": "<tema_principal>",
  "sentiment": "<bullish|bearish|neutral>",
  "confidence": <0.0-1.0>,
  "affected_coins": ["COIN1", "COIN2"],
  "intensity": <0.0-1.0>,
  "reasoning": "<una frase explicando por qué>"
}}

Reglas:
1. Solo incluye coins de nuestra lista que estén DIRECTAMENTE afectadas
2. Para temas macro (macro_btc, regulation_*): incluye todas las coins relevantes
3. confidence >= 0.7 solo si el impacto es claro e inequívoco
4. Si la noticia es irrelevante o incierta → theme: "unrelated", confidence < 0.3
5. Sé conservador: mejor pocos coins afectados que muchos con baja confianza"""


def fetch_recent_news(hours_back: int = 24) -> list[dict]:
    """Descarga y parsea artículos RSS de las últimas N horas."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    articles = []
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/rss+xml,*/*"}

    for feed_url in RSS_FEEDS:
        try:
            req = urllib.request.Request(feed_url, headers=headers)
            with urllib.request.urlopen(req, timeout=12) as r:
                root = ET.fromstring(r.read())
        except Exception as e:
            print(f"  [RSS] SKIP {feed_url.split('/')[2]}: {e}"); continue

        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            desc  = (item.findtext("description") or "").strip()[:600]
            pub   = item.findtext("pubDate") or ""
            link  = item.findtext("link") or ""

            if not title:
                continue

            try:
                from email.utils import parsedate_to_datetime
                pub_dt = parsedate_to_datetime(pub)
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                if pub_dt < cutoff:
                    continue
                pub_str = pub_dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                pub_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

            # Deduplicar por título
            if not any(a["title"] == title for a in articles):
                articles.append({
                    "title": title,
                    "description": desc,
                    "published": pub_str,
                    "source": feed_url.split('/')[2],
                    "url": link,
                })

    print(f"[News] {len(articles)} artículos únicos de las últimas {hours_back}h")
    return articles


def analyze_article_with_claude(title: str, description: str) -> dict:
    """Usa Claude AI para analizar el tema y impacto de una noticia."""
    try:
        import anthropic
    except ImportError:
        return _fallback_keyword_analysis(title, description)

    if not ANTHROPIC_KEY:
        return _fallback_keyword_analysis(title, description)

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",  # rápido y barato (~0.001 USD/call)
            max_tokens=300,
            temperature=0.1,
            messages=[{
                "role": "user",
                "content": ANALYSIS_PROMPT.format(
                    headline=title,
                    description=description[:500] if description else "(sin descripción)"
                )
            }]
        )
        text = msg.content[0].text.strip()
        # Extraer JSON del response
        if "{" in text and "}" in text:
            start = text.index("{")
            end   = text.rindex("}") + 1
            result = json.loads(text[start:end])
            # Filtrar coins no reconocidas
            result["affected_coins"] = [c for c in result.get("affected_coins", []) if c in OUR_COINS]
            return result
    except Exception as e:
        print(f"  [AI] Error en Claude API: {e}")
        return _fallback_keyword_analysis(title, description)

    return _fallback_keyword_analysis(title, description)


def _fallback_keyword_analysis(title: str, description: str) -> dict:
    """Análisis de respaldo sin API key — basado en keywords."""
    text = (title + " " + description).lower()

    # Mapeo simple de keywords → tema
    if any(w in text for w in ["openai", "artificial intelligence", "ai model", "machine learning", "ai agent"]):
        theme, sentiment = "ai_crypto", "bullish"
        coins = ["LINK", "SOL"]
    elif any(w in text for w in ["trump", "strategic reserve", "executive order crypto"]):
        theme, sentiment = "trump_crypto", "bullish"
        coins = ["BTC", "SOL", "BONK", "WIF"]
    elif any(w in text for w in ["etf approved", "spot etf", "bitcoin etf", "blackrock btc"]):
        theme, sentiment = "macro_btc", "bullish"
        coins = ["BTC", "SOL", "LINK"]
    elif any(w in text for w in ["sec lawsuit", "sec charges", "ban", "illegal", "crackdown"]):
        theme, sentiment = "regulation_negative", "bearish"
        coins = ["BTC", "SOL", "LINK"]
    elif any(w in text for w in ["hack", "exploit", "stolen", "drained"]):
        theme, sentiment = "hack_exploit", "bearish"
        coins = ["BTC", "SOL"]
    elif any(w in text for w in ["meme", "pepe", "shib", "bonk", "wif", "turbo"]):
        theme, sentiment = "meme_season", "bullish"
        coins = ["PEPE", "SHIB", "BONK", "WIF", "TURBO"]
    elif any(w in text for w in ["solana", "sol ecosystem", "sol network"]):
        theme, sentiment = "solana_ecosystem", "bullish"
        coins = ["SOL", "BONK", "WIF"]
    else:
        theme, sentiment = "unrelated", "neutral"
        coins = []

    return {
        "theme": theme,
        "sentiment": sentiment,
        "confidence": 0.5,
        "affected_coins": coins,
        "intensity": 0.5,
        "reasoning": "Análisis por keywords (sin API key)",
    }


def aggregate_coin_signals(analyses: list[dict], date: str) -> list[dict]:
    """
    Agrega múltiples análisis de noticias en una señal diaria por coin.
    Pondera por confidence × intensity.
    """
    from collections import defaultdict
    coin_scores = defaultdict(list)

    for analysis in analyses:
        if analysis.get("theme") == "unrelated":
            continue
        conf      = analysis.get("confidence", 0)
        intensity = analysis.get("intensity", 0.5)
        weight    = conf * intensity
        sentiment = analysis.get("sentiment", "neutral")
        score     = weight if sentiment == "bullish" else (-weight if sentiment == "bearish" else 0)

        for coin in analysis.get("affected_coins", []):
            if coin in OUR_COINS:
                coin_scores[coin].append(score)

    rows = []
    for coin in OUR_COINS:
        scores = coin_scores[coin]
        if scores:
            avg_score = sum(scores) / len(scores)
            net_score = sum(scores)
        else:
            avg_score = 0.0
            net_score = 0.0

        rows.append({
            "date": date,
            "coin": coin,
            "ai_score": round(avg_score, 3),       # promedio: -1 a +1
            "ai_net": round(net_score, 3),          # suma: más señales = más impacto
            "ai_articles": len(scores),
        })

    return rows


def run_analysis(hours_back: int = 24, dry_run: bool = False, max_articles: int = 50):
    """Pipeline principal: fetch → analyze → aggregate → save."""
    print(f"\n{'='*60}")
    print(f"  AI News Analysis — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Modelo: claude-haiku-4-5 | API: {'✅ key encontrada' if ANTHROPIC_KEY else '⚠ sin key (fallback keywords)'}")
    print(f"{'='*60}\n")

    # 1. Fetch news
    articles = fetch_recent_news(hours_back)

    # 2. Analyze each article
    analyses = []
    print(f"[AI] Analizando {min(len(articles), max_articles)} artículos...\n")

    for i, art in enumerate(articles[:max_articles]):
        result = analyze_article_with_claude(art["title"], art["description"])
        result["title"]     = art["title"]
        result["published"] = art["published"]
        result["source"]    = art["source"]
        analyses.append(result)

        # Show interesting results
        if result.get("confidence", 0) >= 0.6 and result.get("theme") != "unrelated":
            coins_str = ", ".join(result.get("affected_coins", [])) or "ninguna"
            sent_emoji = "🟢" if result["sentiment"] == "bullish" else ("🔴" if result["sentiment"] == "bearish" else "⚪")
            print(f"  {sent_emoji} [{result['theme']:25s}] conf={result['confidence']:.1f} → {coins_str}")
            print(f"     '{art['title'][:80]}'")
            print(f"     {result.get('reasoning', '')}\n")

        # Rate limiting para Claude API (gratis: ~5 req/min)
        if ANTHROPIC_KEY and (i + 1) % 5 == 0:
            time.sleep(1.2)

    # 3. Aggregate signals
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    coin_signals = aggregate_coin_signals(analyses, today)

    # 4. Show summary
    print(f"\n{'─'*50}")
    print(f"  Señales AI para {today}:")
    print(f"{'─'*50}")
    for row in coin_signals:
        if row["ai_articles"] > 0:
            bar = "█" * min(int(abs(row["ai_score"]) * 10), 10)
            sign = "+" if row["ai_score"] > 0 else ""
            direction = "BULLISH" if row["ai_score"] > 0.2 else ("BEARISH" if row["ai_score"] < -0.2 else "neutral")
            print(f"  {row['coin']:6s}: {sign}{row['ai_score']:+.2f}  {bar:<10}  ({row['ai_articles']} noticias) → {direction}")

    if dry_run:
        print("\n[dry-run] No se guardaron archivos.")
        return

    # 5. Save JSON (señal del día, para live trading)
    json_out = DATA_DIR / "news_themes.json"
    history = []
    if json_out.exists():
        try:
            history = json.loads(json_out.read_text())
        except Exception:
            history = []
    history = [e for e in history if e.get("date") != today]
    history.append({
        "date": today,
        "coin_signals": coin_signals,
        "articles_analyzed": len(analyses),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    })
    history = history[-90:]  # mantener 90 días
    json_out.write_text(json.dumps(history, indent=2, ensure_ascii=False))

    # 6. Save CSV (histórico para backtest futuro)
    csv_out = DATA_DIR / "news_themes.csv"
    existing = []
    if csv_out.exists():
        with open(csv_out) as f:
            existing = [r for r in csv.DictReader(f) if r["date"] != today]
    with open(csv_out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "coin", "ai_score", "ai_net", "ai_articles"])
        w.writeheader()
        w.writerows(existing + coin_signals)

    print(f"\n[AI] Guardado → {json_out.name} + {csv_out.name}")
    print("Done.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Análisis temático de noticias crypto con Claude AI")
    parser.add_argument("--hours",       type=int, default=24, help="Horas de noticias hacia atrás (default: 24)")
    parser.add_argument("--max",         type=int, default=50,  help="Máximo de artículos a analizar (default: 50)")
    parser.add_argument("--dry-run",     action="store_true",   help="Analiza pero no guarda")
    args = parser.parse_args()

    run_analysis(hours_back=args.hours, dry_run=args.dry_run, max_articles=args.max)
