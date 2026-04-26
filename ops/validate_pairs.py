#!/usr/bin/env python3
"""
Gestión automática de la whitelist: cada ejecución reconstruye la whitelist
desde cero con todos los pares que cumplen criterios de rendimiento.

Diseño:
  - La whitelist se SOBREESCRIBE cada día con los mejores pares del momento.
  - La blacklist en config.base.json es SOLO MANUAL — este script nunca la toca.
  - BTC/USDC siempre se incluye (referencia para el filtro macro_ok).

Flujo:
  1. Candidatos = top-40 Binance por volumen + pares de whitelist actual
     (excluyendo NEVER_INCLUDE y la blacklist manual)
  2. Para cada candidato: descarga datos si no existen, corre backtest
  3. Nueva whitelist = BTC + todos los que pasan criterios (≥3T, WR≥70%...)
  4. Sobreescribe whitelist en config.base.json y config.backtest.json
  5. Commit + push si hubo cambios

Criterios de aprobación:
  WR >= 70%, Trades >= 3, Avg profit > 0.5%, Total profit > 0

Uso:
  python ops/validate_pairs.py                # reconstruye whitelist completa
  python ops/validate_pairs.py --dry-run      # preview sin modificar nada
  python ops/validate_pairs.py --no-download  # no descarga datos nuevos
  python ops/validate_pairs.py --pairs BTC BONK WIF  # evalúa solo estos
"""
import argparse
import json
import os
import re
import subprocess
import urllib.request
import zipfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONFIG_BASE = ROOT / "config.base.json"
CONFIG_PAIRS = ROOT / "config.pairs.json"   # whitelist dinámica — no en git, no sobreescrita por deploys
CONFIG_BACKTEST = ROOT / "config.backtest.json"
CONFIG_SECRETS = next(
    (p for p in [ROOT / "config.secrets.json", ROOT / "ops" / "config.secrets.json"] if p.exists()),
    ROOT / "config.secrets.json",
)

MIN_WR = 0.70
MIN_TRADES = 3
MIN_AVG_PROFIT = 0.5
MIN_TOTAL_PROFIT = 0

# Nunca se incluyen — ni aunque pasen backtest. No se tocan por script.
NEVER_INCLUDE = {
    "SOL", "PEPE", "SHIB", "DOGE", "ADA", "XRP", "LTC", "AVAX",
    "FLOKI", "BNB", "WBTC", "WETH",
    "MEME", "NEIRO", "BOME", "SUI", "ORDI",
    "TIA", "WLD", "DOT",
    "AAVE", "TAO", "ENJ", "BLUR", "ZRO",
    "U", "AUD", "EUR", "USD1", "FDUSD",
    "GUN",
}


def run(cmd: list[str], cwd=ROOT, timeout=300) -> tuple[int, str, str]:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout, r.stderr


def load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def save_json(path: Path, data: dict):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def get_current_whitelist() -> list[str]:
    return load_json(CONFIG_BASE)["exchange"]["pair_whitelist"]


def get_manual_blacklist_bases() -> set[str]:
    """Lee la blacklist manual del config — este script nunca la modifica."""
    bases = set()
    for pattern in load_json(CONFIG_BASE)["exchange"]["pair_blacklist"]:
        m = re.match(r"^([A-Z0-9]+)/", pattern)
        if m:
            bases.add(m.group(1))
    return bases


def get_binance_usdc_top(top_n: int = 40) -> set[str]:
    try:
        url = "https://api.binance.com/api/v3/ticker/24hr"
        req = urllib.request.Request(url, headers={"User-Agent": "freqtrade-validator/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            tickers = json.loads(resp.read())
        usdc = [t for t in tickers if t["symbol"].endswith("USDC") and not t["symbol"].endswith("BUSDC")]
        usdc.sort(key=lambda t: float(t["quoteVolume"]), reverse=True)
        bases = set()
        for t in usdc[:top_n]:
            base = t["symbol"].replace("USDC", "")
            if re.match(r"^[A-Z0-9]+$", base):
                bases.add(base)
        return bases
    except Exception as e:
        print(f"  ⚠️  Binance API no disponible: {e}")
        return set()


def download_pair_data(pair_usdc: str, timerange: str) -> bool:
    print(f"  Descargando datos para {pair_usdc}...")
    try:
        code, _, err = run([
            "conda", "run", "-n", "freqtrade", "freqtrade", "download-data",
            "-c", str(CONFIG_BASE), "-c", str(CONFIG_BACKTEST), "-c", str(CONFIG_SECRETS),
            "--pairs", pair_usdc, "--timeframes", "15m", "--timerange", timerange, "--prepend",
        ], timeout=600)
    except subprocess.TimeoutExpired:
        print(f"  ⚠️  Timeout descargando datos (>600s) — saltado")
        return False
    if code != 0:
        print(f"  ⚠️  Error descargando: {err[-200:]}")
        return False
    return True


def run_backtest_single(pair_usdc: str, timerange: str) -> dict | None:
    bt_cfg = load_json(CONFIG_BACKTEST)
    pairs = [pair_usdc]
    if pair_usdc != "BTC/USDC":
        pairs.append("BTC/USDC")
    bt_cfg["exchange"]["pair_whitelist"] = pairs
    tmp_cfg = ROOT / "config.backtest.tmp.json"
    save_json(tmp_cfg, bt_cfg)
    try:
        try:
            code, *_ = run([
                "conda", "run", "-n", "freqtrade", "freqtrade", "backtesting",
                "-c", str(CONFIG_BASE), "-c", str(tmp_cfg), "-c", str(CONFIG_SECRETS),
                "-s", "MyStrategy", "--timerange", timerange, "--cache", "none",
            ], timeout=300)
        except subprocess.TimeoutExpired:
            print(f"  ⚠️  Timeout en backtest (>300s) — saltado")
            return None
        if code != 0:
            return None
        results_dir = ROOT / "user_data" / "backtest_results"
        zips = sorted(results_dir.glob("*.zip"), key=os.path.getmtime, reverse=True)
        if not zips:
            return None
        with zipfile.ZipFile(zips[0]) as z:
            json_files = [n for n in z.namelist()
                          if n.endswith(".json") and "meta" not in n
                          and "config" not in n and "MyStrategy" not in n]
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
        return {"pair": pair_usdc, "trades": len(pair_trades), "wr": wr,
                "avg_profit": avg_profit, "total_profit": total_profit}
    finally:
        tmp_cfg.unlink(missing_ok=True)


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


def overwrite_whitelist(new_whitelist: list[str]):
    # Escribe config.pairs.json (servidor, no en git) con la whitelist dinámica
    save_json(CONFIG_PAIRS, {"exchange": {"pair_whitelist": new_whitelist}})
    # Actualiza también config.backtest.json para que los backtests locales sean consistentes
    cfg = load_json(CONFIG_BACKTEST)
    cfg["exchange"]["pair_whitelist"] = new_whitelist
    save_json(CONFIG_BACKTEST, cfg)


def main():
    parser = argparse.ArgumentParser(description="Reconstruye la whitelist con los pares que funcionan hoy")
    parser.add_argument("--pairs", nargs="+", help="Evalúa solo estos pares (sin /USDC) — no sobreescribe")
    parser.add_argument("--dry-run", action="store_true", help="Muestra resultado sin modificar configs")
    parser.add_argument("--no-download", action="store_true", help="No descarga datos nuevos")
    default_timerange = f"{(date.today() - timedelta(days=182)).strftime('%Y%m%d')}-{date.today().strftime('%Y%m%d')}"
    parser.add_argument("--timerange", default=default_timerange)
    args = parser.parse_args()

    print("=" * 60)
    print("🔄 RECONSTRUCCIÓN AUTOMÁTICA DE WHITELIST")
    print(f"   Rango: {args.timerange}")
    print("=" * 60)

    manual_bl = get_manual_blacklist_bases()
    excluded = NEVER_INCLUDE | manual_bl | {"BTC"}  # BTC se añade siempre al final

    if args.pairs:
        # Modo evaluación manual — no sobreescribe, solo informa
        candidates = [c.upper() for c in args.pairs if c.upper() not in excluded]
    else:
        current_wl_bases = {p.split("/")[0] for p in get_current_whitelist()} - excluded
        binance_top = get_binance_usdc_top(40) - excluded
        candidates = sorted(current_wl_bases | binance_top)

    print(f"\nCandidatos a evaluar: {len(candidates)}")

    approved = []  # (pair, stats)
    rejected = []  # (pair, stats, reason)
    no_data  = []  # pair

    for coin in candidates:
        pair = f"{coin}/USDC"
        feather = ROOT / "user_data" / "data" / "binance" / f"{coin}_USDC-15m.feather"
        print(f"\n{'─'*50}")
        print(f"📊 {pair}")

        if not feather.exists():
            if args.no_download:
                print(f"  ⏭️  Sin datos locales — saltado (--no-download)")
                no_data.append(pair)
                continue
            if not download_pair_data(pair, args.timerange):
                print(f"  ❌ No se pudieron descargar datos")
                no_data.append(pair)
                continue

        stats = run_backtest_single(pair, args.timerange)
        if stats is None:
            print(f"  ❌ Backtest falló")
            no_data.append(pair)
            continue

        passed, reason = evaluate(stats)
        if passed:
            print(f"  ✅ PASA: {reason}")
            approved.append((pair, stats))
        else:
            if stats["trades"] < MIN_TRADES:
                print(f"  ⏭️  {reason} — sin datos suficientes, ignorado")
                no_data.append(pair)
            else:
                print(f"  ❌ NO PASA: {reason}")
                rejected.append((pair, stats, reason))

    # Construir nueva whitelist: BTC siempre primero, luego aprobados por profit desc
    new_whitelist = ["BTC/USDC"] + [p for p, _ in sorted(approved, key=lambda x: x[1]["total_profit"], reverse=True)]

    # Resumen
    print(f"\n{'='*60}")
    print("📋 RESULTADO")
    print(f"{'='*60}")
    print(f"\n✅ Nueva whitelist ({len(new_whitelist)} pares):")
    for p in new_whitelist:
        stats_str = ""
        for pair, stats in approved:
            if pair == p:
                stats_str = f"  {stats['trades']}T, {stats['wr']*100:.1f}% WR, +${stats['total_profit']:.0f}"
        print(f"  {p}{stats_str}")

    if rejected:
        print(f"\n❌ Excluidos por rendimiento ({len(rejected)}):")
        for pair, stats, reason in rejected:
            print(f"  {pair}: {stats['trades']}T, ${stats['total_profit']:.0f} — {reason}")

    if no_data:
        print(f"\n⏭️  Sin datos suficientes ({len(no_data)}): {', '.join(no_data)}")

    if args.dry_run or args.pairs:
        print("\n⚠️  DRY RUN / modo --pairs — no se modifica ningún config")
        return

    # Comparar con whitelist actual
    current_wl = get_current_whitelist()
    if set(new_whitelist) == set(current_wl):
        print("\nℹ️  Whitelist sin cambios — nada que commitear.")
        return

    added   = set(new_whitelist) - set(current_wl)
    removed = set(current_wl) - set(new_whitelist)
    print(f"\n🔧 Sobreescribiendo whitelist...")
    if added:
        print(f"  + Añadidos: {', '.join(sorted(added))}")
    if removed:
        print(f"  - Eliminados: {', '.join(sorted(removed))}")

    overwrite_whitelist(new_whitelist)
    print("\n✅ config.pairs.json actualizado.")

    # Reiniciar freqtrade para que cargue la nueva whitelist
    r = subprocess.run(["sudo", "systemctl", "restart", "freqtrade"], cwd=ROOT)
    if r.returncode == 0:
        print("🔄 freqtrade reiniciado con la nueva whitelist.")
    else:
        print("⚠️  No se pudo reiniciar freqtrade — reinícialo manualmente: sudo systemctl restart freqtrade")


if __name__ == "__main__":
    main()
