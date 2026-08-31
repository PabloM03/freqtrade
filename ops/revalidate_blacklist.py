#!/usr/bin/env python3
"""
Revalidación semestral de la blacklist: testea pares descartados previamente
con datos recientes para detectar si alguno ha mejorado su comportamiento.

Uso:
  python ops/revalidate_blacklist.py                    # últimos 6 meses
  python ops/revalidate_blacklist.py --months 12        # último año
  python ops/revalidate_blacklist.py --coins ENA SOL    # solo estos coins

Criterios (iguales que validate_pairs.py):
  - WR >= 70%, Trades >= 3, Avg profit > 0.5%, Total profit > 0

Output: solo reporte — nunca modifica configs automáticamente.
El usuario decide qué hacer con los candidatos promovibles.
"""
import argparse
import json
import os
import re
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONFIG_BASE = ROOT / "config.base.json"
CONFIG_BACKTEST = ROOT / "config.backtest.json"
CONFIG_SECRETS = next(
    (p for p in [ROOT / "config.secrets.json", ROOT / "ops" / "config.secrets.json"] if p.exists()),
    ROOT / "config.secrets.json",
)

MIN_WR = 0.70
MIN_TRADES = 3
MIN_AVG_PROFIT = 0.5
MIN_TOTAL_PROFIT = 0

# Excluidos permanentemente — no tienen sentido para esta estrategia reversal
FOREVER_EXCLUDED = {
    "ETH", "ADA", "XRP", "LTC", "BNB", "WBTC", "WETH", "DOGE", "FLOKI",
    "PEPE", "SHIB", "NEIRO", "MEME", "BOME", "U", "AUD", "EUR", "USD1", "FDUSD",
    "GUN",  # catastrófico (-$205, 50% WR con 12T — daño estructural probado)
}


def load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def save_json(path: Path, data: dict):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def run(cmd: list[str], cwd=ROOT, timeout=600) -> tuple[int, str, str]:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout, r.stderr


def get_blacklist_coins() -> list[str]:
    cfg = load_json(CONFIG_BASE)
    coins = []
    for pattern in cfg["exchange"]["pair_blacklist"]:
        m = re.match(r"^([A-Z0-9]+)/\.\*$", pattern)
        if m:
            coin = m.group(1)
            if coin not in FOREVER_EXCLUDED:
                coins.append(coin)
    return sorted(coins)


def get_whitelist_bases() -> set[str]:
    cfg = load_json(CONFIG_BASE)
    return {p.split("/")[0] for p in cfg["exchange"]["pair_whitelist"]}


def run_backtest_single(pair_usdc: str, timerange: str) -> dict | None:
    # Tmp config: par objetivo + BTC (necesario para macro_ok filter)
    bt_cfg = load_json(CONFIG_BACKTEST)
    pairs = [pair_usdc]
    if pair_usdc != "BTC/USD":
        pairs.append("BTC/USD")
    bt_cfg["exchange"]["pair_whitelist"] = pairs
    tmp_cfg = ROOT / "config.backtest.revalidate.tmp.json"
    save_json(tmp_cfg, bt_cfg)

    try:
        code, *_ = run([
            "conda", "run", "-n", "freqtrade", "freqtrade", "backtesting",
            "-c", str(CONFIG_BASE), "-c", str(tmp_cfg),
            "-c", str(CONFIG_SECRETS),
            "-s", "MyStrategy",
            "--timerange", timerange,
            "--cache", "none"
        ], timeout=600)
    except Exception:
        return None
    finally:
        tmp_cfg.unlink(missing_ok=True)

    if code != 0:
        return None

    results_dir = ROOT / "user_data" / "backtest_results"
    zips = sorted(results_dir.glob("*.zip"), key=os.path.getmtime, reverse=True)
    if not zips:
        return None

    with zipfile.ZipFile(zips[0]) as z:
        json_files = [n for n in z.namelist() if n.endswith(".json") and "meta" not in n and "config" not in n and "MyStrategy" not in n]
        if not json_files:
            return None
        with z.open(json_files[0]) as fh:
            data = json.load(fh)

    strat = data.get("strategy", {}).get("MyStrategy", {})
    if not strat:
        return None

    trades = strat.get("trades", [])
    pair_trades = [t for t in trades if t.get("pair") == pair_usdc]

    if not pair_trades:
        return {"pair": pair_usdc, "trades": 0, "wr": 0, "avg_profit": 0, "total_profit": 0}

    wins = sum(1 for t in pair_trades if t["profit_ratio"] > 0)
    wr = wins / len(pair_trades)
    avg_profit = sum(t["profit_ratio"] for t in pair_trades) / len(pair_trades) * 100
    total_profit = sum(t["profit_abs"] for t in pair_trades)

    return {
        "pair": pair_usdc,
        "trades": len(pair_trades),
        "wr": wr,
        "avg_profit": avg_profit,
        "total_profit": total_profit,
    }


def evaluate(stats: dict) -> tuple[bool, str]:
    if stats["trades"] == 0:
        return False, "0 trades"
    if stats["trades"] < MIN_TRADES:
        return False, f"solo {stats['trades']} trades"
    if stats["wr"] < MIN_WR:
        return False, f"WR {stats['wr']*100:.1f}%"
    if stats["total_profit"] <= MIN_TOTAL_PROFIT:
        return False, f"profit ${stats['total_profit']:.2f} ≤ 0"
    if stats["avg_profit"] < MIN_AVG_PROFIT:
        return False, f"avg {stats['avg_profit']:.2f}%"
    return True, f"{stats['trades']}T, {stats['wr']*100:.1f}% WR, +${stats['total_profit']:.0f}"


def main():
    parser = argparse.ArgumentParser(description="Revalidación semestral de la blacklist")
    parser.add_argument("--coins", nargs="+", help="Coins específicos a re-testear (sin /USD)")
    parser.add_argument("--timerange", default="20240101-20251231",
                        help="Rango de backtest (default: 20240101-20251231 — datos completos garantizados)")
    args = parser.parse_args()

    timerange = args.timerange

    if args.coins:
        candidates = [c.upper() for c in args.coins]
    else:
        candidates = get_blacklist_coins()

    wl_bases = get_whitelist_bases()
    candidates = [c for c in candidates if c not in wl_bases]

    print("=" * 60)
    print(f"🔄 REVALIDACIÓN DE BLACKLIST")
    print(f"   Rango: {timerange}")
    print("=" * 60)

    if not candidates:
        print("No hay candidatos en la blacklist para revalidar.")
        return

    print(f"\nCoins a re-testear ({len(candidates)}): {', '.join(candidates)}\n")

    promotable = []
    still_bad = []
    no_data = []

    for coin in candidates:
        pair = f"{coin}/USD"
        feather = ROOT / "user_data" / "data" / "kraken" / f"{coin}_USD-15m.feather"
        print(f"{'─'*50}")
        print(f"🔍 {pair}...")

        if not feather.exists():
            print(f"  ⚠️  Sin datos locales — ejecutar download-data primero")
            no_data.append(coin)
            continue

        stats = run_backtest_single(pair, timerange)
        if stats is None:
            print(f"  ❌ Backtest falló")
            no_data.append(coin)
            continue

        passed, reason = evaluate(stats)
        if passed:
            print(f"  ✅ MEJORADO: {reason}")
            promotable.append((coin, stats))
        else:
            t = stats["trades"]
            p = stats["total_profit"]
            print(f"  ✗  Sigue mal: {t}T, ${p:.0f} — {reason}")
            still_bad.append((coin, stats, reason))

    print(f"\n{'='*60}")
    print("📋 RESUMEN REVALIDACIÓN")
    print(f"{'='*60}")

    if promotable:
        print(f"\n✅ CANDIDATOS A PROMOVER ({len(promotable)}) — considera añadir a whitelist:")
        for coin, stats in promotable:
            print(f"  {coin}/USD: {stats['trades']}T, {stats['wr']*100:.1f}% WR, +${stats['total_profit']:.0f} ({stats['avg_profit']:.2f}% avg)")
        print(f"\n  ➡️  Para añadir: python ops/validate_pairs.py --pairs {' '.join(c for c, _ in promotable)} --no-download --timerange 20240101-YYYYMMDD")
    else:
        print("\n  Sin candidatos a promover en este período.")

    if still_bad:
        print(f"\n✗  Siguen en blacklist ({len(still_bad)}):")
        for coin, stats, reason in still_bad:
            print(f"  {coin}: {stats['trades']}T, ${stats['total_profit']:.0f} — {reason}")

    if no_data:
        print(f"\n⚠️  Sin datos ({len(no_data)}): {', '.join(no_data)}")
        print(f"   Descargar con: freqtrade download-data --dl-trades --pairs {' '.join(f'{c}/USD' for c in no_data)} --timeframes 15m")


if __name__ == "__main__":
    main()
