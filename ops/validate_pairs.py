#!/usr/bin/env python3
"""
Auto-validación de pares: descarga datos, testea con params actuales,
actualiza whitelist/blacklist en config.base.json y config.backtest.json.

Uso:
  python ops/validate_pairs.py                      # valida pares del VolumePairList vs whitelist actual
  python ops/validate_pairs.py --pairs DYDX TIA LDO # valida pares específicos
  python ops/validate_pairs.py --dry-run             # solo muestra resultados sin modificar configs
  python ops/validate_pairs.py --timerange 20240101-20251231  # rango custom

Criterios de aprobación:
  - WR >= 70% (al menos 7 de cada 10 trades ganadores)
  - Profit total > 0 (positivo)
  - Trades >= 3 (mínimo estadístico)
  - Avg profit > 0.5% por trade
"""
import argparse
import json
import os
import re
import subprocess
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONFIG_BASE = ROOT / "config.base.json"
CONFIG_BACKTEST = ROOT / "config.backtest.json"
CONFIG_SECRETS = next(
    (p for p in [ROOT / "config.secrets.json", ROOT / "ops" / "config.secrets.json"] if p.exists()),
    ROOT / "config.secrets.json",
)

# Criterios de aprobación
MIN_WR = 0.70        # 70% win rate mínimo
MIN_TRADES = 3       # mínimo 3 trades para ser estadísticamente relevante
MIN_AVG_PROFIT = 0.5 # 0.5% avg profit por trade
MIN_TOTAL_PROFIT = 0  # profit total positivo

# Pares que nunca deben añadirse (blacklist fija — probados y fallidos o riesgosos)
PERMANENT_BLACKLIST = {
    # Siempre excluidos (grandes caps que no encajan en estrategia reversal)
    "SOL", "PEPE", "SHIB", "DOGE", "ETH", "ADA", "XRP", "LTC", "AVAX",
    "FLOKI", "BNB", "WBTC", "WETH",
    # Testados y rechazados por backtest negativo
    "MEME", "NEIRO", "BOME", "SUI", "ORDI",
    "TIA", "WLD", "DOT", "DYDX",
    # Excluidos por naturaleza (no son coins tradables para esta estrategia)
    "U", "AUD", "EUR", "USD1", "FDUSD",
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
    cfg = load_json(CONFIG_BASE)
    return cfg["exchange"]["pair_whitelist"]


def get_current_blacklist_bases() -> set[str]:
    """Extrae los nombres base de los pares en la blacklist (ej: 'SOL' de 'SOL/.*')"""
    cfg = load_json(CONFIG_BASE)
    bases = set()
    for pattern in cfg["exchange"]["pair_blacklist"]:
        # extrae el nombre base antes de /
        m = re.match(r"^([A-Z0-9]+)/", pattern)
        if m:
            bases.add(m.group(1))
    return bases


def download_pair_data(pair_usdc: str, timerange: str):
    """Descarga datos históricos para un par."""
    print(f"  Descargando datos para {pair_usdc}...")
    code, _, err = run([
        "conda", "run", "-n", "freqtrade", "freqtrade", "download-data",
        "-c", str(CONFIG_BASE), "-c", str(CONFIG_BACKTEST),
        "-c", str(CONFIG_SECRETS),
        "--pairs", pair_usdc,
        "--timeframes", "15m",
        "--timerange", timerange,
        "--prepend"
    ], timeout=180)
    if code != 0:
        print(f"  ⚠️  Error descargando {pair_usdc}: {err[-200:]}")
        return False
    return True


def run_backtest_single(pair_usdc: str, timerange: str) -> dict | None:
    """Ejecuta backtest de un par solo y devuelve sus stats."""
    # Config temporal con solo este par
    bt_cfg = load_json(CONFIG_BACKTEST)
    bt_cfg["exchange"]["pair_whitelist"] = [pair_usdc]
    tmp_cfg = ROOT / "config.backtest.tmp.json"
    save_json(tmp_cfg, bt_cfg)

    try:
        code, *_ = run([
            "conda", "run", "-n", "freqtrade", "freqtrade", "backtesting",
            "-c", str(CONFIG_BASE), "-c", str(tmp_cfg),
            "-c", str(CONFIG_SECRETS),
            "-s", "MyStrategy",
            "--timerange", timerange,
            "--cache", "none"
        ], timeout=300)

        if code != 0:
            print(f"  ⚠️  Backtest falló para {pair_usdc}")
            return None

        # Encontrar el zip más reciente
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

    finally:
        tmp_cfg.unlink(missing_ok=True)


def evaluate(stats: dict) -> tuple[bool, str]:
    """Decide si el par pasa la validación. Retorna (aprobado, razón)."""
    if stats["trades"] == 0:
        return False, "0 trades en el período"
    if stats["trades"] < MIN_TRADES:
        return False, f"solo {stats['trades']} trades (mínimo {MIN_TRADES})"
    if stats["wr"] < MIN_WR:
        return False, f"WR {stats['wr']*100:.1f}% < {MIN_WR*100:.0f}%"
    if stats["total_profit"] <= MIN_TOTAL_PROFIT:
        return False, f"profit total ${stats['total_profit']:.2f} ≤ 0"
    if stats["avg_profit"] < MIN_AVG_PROFIT:
        return False, f"avg profit {stats['avg_profit']:.2f}% < {MIN_AVG_PROFIT}%"
    return True, f"{stats['trades']}T, {stats['wr']*100:.1f}% WR, +${stats['total_profit']:.0f}"


def add_to_whitelist(pair_usdc: str):
    """Añade un par a la whitelist de config.base.json y config.backtest.json."""
    for cfg_path in [CONFIG_BASE, CONFIG_BACKTEST]:
        cfg = load_json(cfg_path)
        wl = cfg["exchange"]["pair_whitelist"]
        if pair_usdc not in wl:
            wl.append(pair_usdc)
            save_json(cfg_path, cfg)
            print(f"  ✅ Añadido a {cfg_path.name}")


def add_to_blacklist(pair_usdc: str):
    """Añade un par a la blacklist de config.base.json."""
    base = pair_usdc.split("/")[0]
    pattern = f"{base}/.*"
    cfg = load_json(CONFIG_BASE)
    bl = cfg["exchange"]["pair_blacklist"]
    if pattern not in bl:
        # Insertar al principio para que sea visible
        bl.insert(0, pattern)
        save_json(CONFIG_BASE, cfg)
        print(f"  🚫 Blacklisteado en config.base.json: {pattern}")


def get_binance_usdc_pairs(top_n: int = 40) -> set[str]:
    """Consulta Binance REST API y devuelve los top N pares USDC por volumen 24h."""
    try:
        url = "https://api.binance.com/api/v3/ticker/24hr"
        req = urllib.request.Request(url, headers={"User-Agent": "freqtrade-validator/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            tickers = json.loads(resp.read())
        usdc = [
            t for t in tickers
            if t["symbol"].endswith("USDC") and not t["symbol"].endswith("BUSDC")
        ]
        usdc.sort(key=lambda t: float(t["quoteVolume"]), reverse=True)
        bases = set()
        for t in usdc[:top_n]:
            base = t["symbol"].replace("USDC", "")
            if re.match(r"^[A-Z0-9]+$", base):
                bases.add(base)
        return bases
    except Exception as e:
        print(f"  ⚠️  No se pudo consultar Binance API: {e}")
        return set()


def get_pairs_to_test(explicit: list[str] | None) -> list[str]:
    """Determina qué pares probar.

    Sin --pairs explícitos: une pares con datos locales (máquina dev) y pares
    del top-40 de Binance por volumen (servidor sin datos locales), filtrando
    los que ya están en whitelist, blacklist o permanent_blacklist.
    """
    if explicit:
        return [f"{p}/USDC" if "/" not in p else p for p in explicit]

    current_wl_bases = {p.split("/")[0] for p in get_current_whitelist()}
    current_bl_bases = get_current_blacklist_bases()
    excluded = current_wl_bases | current_bl_bases | PERMANENT_BLACKLIST

    # Pares con datos locales (entorno dev)
    data_dir = ROOT / "user_data" / "data" / "binance"
    local_pairs = {
        f.stem.replace("_USDC-15m", "").replace("-15m", "")
        for f in data_dir.glob("*_USDC-15m.feather")
    }

    # Pares del top-40 Binance por volumen (descubrimiento dinámico en servidor)
    binance_pairs = get_binance_usdc_pairs(top_n=40)

    candidates = sorted((local_pairs | binance_pairs) - excluded)
    return [f"{p}/USDC" for p in candidates]


def main():
    parser = argparse.ArgumentParser(description="Auto-validación de pares nuevos")
    parser.add_argument("--pairs", nargs="+", help="Pares a testear (sin /USDC)")
    parser.add_argument("--dry-run", action="store_true", help="Solo mostrar, no modificar configs")
    default_timerange = f"20240101-{date.today().strftime('%Y%m%d')}"
    parser.add_argument("--timerange", default=default_timerange, help="Rango de backtest")
    parser.add_argument("--no-download", action="store_true", help="No descargar datos (ya existen)")
    args = parser.parse_args()

    print("=" * 60)
    print("🔍 VALIDACIÓN AUTOMÁTICA DE PARES")
    print("=" * 60)

    pairs = get_pairs_to_test(args.pairs)
    if not pairs:
        print("No hay pares nuevos que validar.")
        return

    print(f"\nPares a validar: {len(pairs)}")
    for p in pairs:
        print(f"  - {p}")

    approved = []
    rejected = []

    for pair in pairs:
        base = pair.split("/")[0]
        print(f"\n{'─'*50}")
        print(f"📊 Validando {pair}...")

        if base in PERMANENT_BLACKLIST:
            print(f"  ⏭️  Saltado — en blacklist permanente")
            continue

        # Descargar datos si necesario
        if not args.no_download:
            feather = ROOT / "user_data" / "data" / "binance" / f"{base}_USDC-15m.feather"
            if not feather.exists():
                ok = download_pair_data(pair, args.timerange)
                if not ok:
                    print(f"  ❌ No se pudieron descargar datos")
                    continue

        # Backtest
        stats = run_backtest_single(pair, args.timerange)
        if stats is None:
            print(f"  ❌ Backtest falló")
            continue

        passed, reason = evaluate(stats)
        if passed:
            print(f"  ✅ APROBADO: {reason}")
            approved.append((pair, stats))
        else:
            print(f"  ❌ RECHAZADO: {reason}")
            rejected.append((pair, stats, reason))

    # Resumen
    print(f"\n{'='*60}")
    print("📋 RESUMEN")
    print(f"{'='*60}")
    print(f"\n✅ APROBADOS ({len(approved)}):")
    for pair, stats in approved:
        print(f"  {pair}: {stats['trades']}T, {stats['wr']*100:.1f}% WR, +${stats['total_profit']:.0f} ({stats['avg_profit']:.2f}% avg)")

    print(f"\n❌ RECHAZADOS ({len(rejected)}):")
    for pair, stats, reason in rejected:
        t = stats['trades']
        p = stats['total_profit']
        print(f"  {pair}: {t}T, ${p:.0f} — {reason}")

    if args.dry_run:
        print("\n⚠️  DRY RUN — no se modifica ningún config")
        return

    # Aplicar cambios
    if approved or rejected:
        print(f"\n🔧 Actualizando configs...")
        for pair, _ in approved:
            add_to_whitelist(pair)
        for pair, stats, _ in rejected:
            if stats["trades"] >= 3:  # solo blacklist si tuvimos suficientes datos
                add_to_blacklist(pair)

        # Commit y push solo si hay cambios reales en los configs
        subprocess.run(["git", "add", str(CONFIG_BASE), str(CONFIG_BACKTEST)], cwd=ROOT)
        diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT)
        if diff.returncode != 0:
            pairs_str = " ".join(p for p, _ in approved) or "solo rechazados"
            msg = f"feat: auto-validación pares — añadidos: {pairs_str}"
            subprocess.run(["git", "commit", "-m", msg], cwd=ROOT)
            subprocess.run(["git", "push"], cwd=ROOT)
            print("\n🚀 Cambios commiteados y pusheados.")
        else:
            print("\nℹ️  Sin cambios en configs — nada que commitear.")


if __name__ == "__main__":
    main()
