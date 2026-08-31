#!/usr/bin/env python3
"""
Gestión automática de la whitelist — diseño a prueba de automatizaciones.

Tres categorías de pares:

  CORE_PAIRS      — validados manualmente, SIEMPRE en whitelist.
                    El script los evalúa informativamente pero NUNCA los elimina.
                    Solo se eliminan moviéndolos a pair_blacklist en config.base.json.

  REJECTED_PAIRS  — probados y rechazados, o incompatibles con la estrategia.
                    El script NUNCA los añade aunque pasen un backtest de corto plazo.

  Auto-discovered — pares de Kraken top-40 que no son CORE ni REJECTED.
                    Se añaden si pasan criterios estrictos (≥3T, WR≥75%, avg≥0.8%, $5+).
                    Se eliminan solo con evidencia sólida (≥8T, WR<50%).

Flujo:
  1. Candidatos = top-40 Kraken + whitelist actual — excluidos REJECTED y blacklist manual
  2. CORE_PAIRS: evaluar informativamente, siempre incluir en whitelist
  3. No-CORE: backtest → añadir/preservar/eliminar según criterios
  4. Nueva whitelist = BTC + CORE + auto-aprobados + preservados
  5. Si hay cambios: sobreescribir configs, reiniciar bot, push [skip ci]

Uso:
  python ops/validate_pairs.py                # reconstruye whitelist completa
  python ops/validate_pairs.py --dry-run      # preview sin modificar nada
  python ops/validate_pairs.py --no-download  # no descarga datos nuevos
  python ops/validate_pairs.py --pairs BTC BONK WIF  # evalúa solo estos (sin sobreescribir)
"""
import argparse
import json
import os
import re
import subprocess
import zipfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONFIG_BASE = ROOT / "config.base.json"
CONFIG_BACKTEST = ROOT / "config.backtest.json"
CONFIG_SECRETS = next(
    (p for p in [ROOT / "config.secrets.json", ROOT / "ops" / "config.secrets.json"] if p.exists()),
    ROOT / "config.secrets.json",
)

# ---------------------------------------------------------------------------
# Freqtrade binary
# ---------------------------------------------------------------------------
def _find_freqtrade() -> list[str]:
    for candidate in [
        "/home/ubuntu/miniconda3/envs/freqtrade/bin/freqtrade",
        "/home/pablom03/anaconda3/envs/freqtrade/bin/freqtrade",
    ]:
        if Path(candidate).exists():
            return [candidate]
    return ["conda", "run", "-n", "freqtrade", "freqtrade"]

FREQTRADE = _find_freqtrade()

# ---------------------------------------------------------------------------
# Listas de control — la única forma de mover un par entre categorías es
# editando este fichero manualmente y haciendo commit.
# ---------------------------------------------------------------------------

# Validados manualmente — backtest completo + WR histórica sólida.
# SIEMPRE en whitelist; el script nunca los elimina automáticamente.
CORE_PAIRS = {
    "BONK", "WIF", "TURBO", "PNUT", "PENGU", "FET", "ACT", "HBAR",
    "JTO", "LDO", "LINK", "NEAR", "OP", "TON", "SPK",
}

# Probados y rechazados, o incompatibles estructuralmente.
# El script NUNCA los añade aunque superen el backtest de corto plazo.
REJECTED_PAIRS = {
    # Grandes caps — demasiado estables, nunca disparan la estrategia
    "TRX", "CFG", "BNB",
    # Testados y fallaron (memoria histórica)
    "SOL", "PEPE", "SHIB", "DOGE", "ADA", "ETH", "XRP", "AVAX", "LTC",
    "MEME", "NEIRO", "TIA", "WLD", "DYDX", "DOT", "GUN", "AAVE", "TAO",
    "ENA", "ENJ", "BLUR", "ZRO", "FLOKI", "LUNC", "LUNA",
    # Añadidos por el auto-script en bull market con datos insuficientes
    "APE", "RUNE", "GIGGLE", "EIGEN", "RENDER",
}

# ---------------------------------------------------------------------------
# Criterios de evaluación
# ---------------------------------------------------------------------------

# Para AÑADIR un par no-core nuevo
ADD_MIN_TRADES = 3
ADD_MIN_WR = 0.75
ADD_MIN_AVG_PROFIT = 0.8   # %
ADD_MIN_TOTAL_PROFIT = 5   # USD

# Para ELIMINAR un par no-core ya en whitelist
REMOVE_MIN_TRADES = 4          # basta con 4 trades para juzgar WR
REMOVE_MAX_WR = 0.65           # más cercano al umbral de entrada (75%)
REMOVE_MIN_TOTAL_PROFIT = -10  # USD — eliminar si pierde >$10 con ≥3 trades (sin importar WR)


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def run(cmd: list[str], cwd=ROOT, timeout=300) -> tuple[int, str, str]:
    proc = subprocess.Popen(
        cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, preexec_fn=os.setsid,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return proc.returncode, stdout, stderr
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(proc.pid), 9)
        proc.communicate()
        raise


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
    bases = set()
    for pattern in load_json(CONFIG_BASE)["exchange"]["pair_blacklist"]:
        m = re.match(r"^([A-Z0-9]+)/", pattern)
        if m:
            bases.add(m.group(1))
    return bases


FIAT_CURRENCIES = {
    "EUR", "GBP", "JPY", "CHF", "AUD", "CAD", "KRW", "CNY",
    "HKD", "SGD", "NOK", "SEK", "DKK", "NZD", "MXN", "BRL",
    "INR", "USD", "XAU", "XAG", "XPT", "XPD",
}


def get_kraken_usd_top(top_n: int = 40) -> set[str]:
    try:
        import ccxt
        kraken = ccxt.kraken()
        tickers = kraken.fetch_tickers()
        usd = [(sym, t.get("quoteVolume") or 0)
               for sym, t in tickers.items()
               if sym.endswith("/USD") and sym.split("/")[0] not in FIAT_CURRENCIES]
        usd.sort(key=lambda x: x[1], reverse=True)
        bases = set()
        for sym, _ in usd[:top_n]:
            base = sym.split("/")[0]
            if re.match(r"^[A-Z0-9]+$", base):
                bases.add(base)
        return bases
    except Exception as e:
        print(f"  ⚠️  Kraken API no disponible: {e}")
        return set()


def download_pair_data(pair_usd: str, timerange: str) -> bool:
    print(f"  Descargando datos para {pair_usd}...")
    try:
        code, _, err = run([
            *FREQTRADE, "download-data",
            "-c", str(CONFIG_BASE), "-c", str(CONFIG_BACKTEST), "-c", str(CONFIG_SECRETS),
            "--pairs", pair_usd, "--timeframes", "15m", "--timerange", timerange,
            "--dl-trades",  # Kraken no soporta OHLCV histórico, requiere trades
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
    if pair_usdc != "BTC/USD":
        pairs.append("BTC/USD")
    bt_cfg["exchange"]["pair_whitelist"] = pairs
    tmp_cfg = ROOT / "config.backtest.tmp.json"
    save_json(tmp_cfg, bt_cfg)
    try:
        try:
            code, *_ = run([
                *FREQTRADE, "backtesting",
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


def evaluate_for_addition(stats: dict) -> tuple[bool | None, str]:
    """Criterio para añadir un par NO-CORE nuevo."""
    if stats["trades"] == 0:
        return False, "0 trades"
    if stats["trades"] < ADD_MIN_TRADES:
        return None, f"solo {stats['trades']}T — insuficiente"
    if stats["wr"] < ADD_MIN_WR:
        return False, f"WR {stats['wr']*100:.1f}% < {ADD_MIN_WR*100:.0f}%"
    if stats["total_profit"] <= ADD_MIN_TOTAL_PROFIT:
        return False, f"profit ${stats['total_profit']:.2f} ≤ ${ADD_MIN_TOTAL_PROFIT}"
    if stats["avg_profit"] < ADD_MIN_AVG_PROFIT:
        return False, f"avg {stats['avg_profit']:.2f}% < {ADD_MIN_AVG_PROFIT}%"
    return True, f"{stats['trades']}T, {stats['wr']*100:.1f}% WR, +${stats['total_profit']:.0f}"


def evaluate_for_removal(stats: dict) -> tuple[bool | None, str]:
    """Criterio para eliminar un par no-core YA en whitelist. None = no hay suficientes datos."""
    # Pérdida severa con mínimo de datos → eliminar sin esperar a REMOVE_MIN_TRADES
    if stats["trades"] >= 3 and stats["total_profit"] < REMOVE_MIN_TOTAL_PROFIT:
        return True, f"eliminar: profit ${stats['total_profit']:.2f} < ${REMOVE_MIN_TOTAL_PROFIT} con {stats['trades']}T"
    if stats["trades"] < REMOVE_MIN_TRADES:
        return None, f"solo {stats['trades']}T — insuficiente para juzgar (necesita ≥{REMOVE_MIN_TRADES})"
    if stats["wr"] < REMOVE_MAX_WR:
        return True, f"eliminar: WR {stats['wr']*100:.1f}% < {REMOVE_MAX_WR*100:.0f}% con {stats['trades']}T"
    return False, f"mantener: {stats['trades']}T, {stats['wr']*100:.1f}% WR, ${stats['total_profit']:.0f}"


def overwrite_whitelist(new_whitelist: list[str]):
    for cfg_path in [CONFIG_BASE, CONFIG_BACKTEST]:
        cfg = load_json(cfg_path)
        cfg["exchange"]["pair_whitelist"] = new_whitelist
        save_json(cfg_path, cfg)


def main():
    parser = argparse.ArgumentParser(description="Gestión de whitelist con protección de pares core")
    parser.add_argument("--pairs", nargs="+", help="Evalúa solo estos pares (sin /USD) — no sobreescribe")
    parser.add_argument("--dry-run", action="store_true", help="Muestra resultado sin modificar configs")
    parser.add_argument("--no-download", action="store_true", help="No descarga datos nuevos")
    default_timerange = f"{(date.today() - timedelta(days=365)).strftime('%Y%m%d')}-{date.today().strftime('%Y%m%d')}"
    parser.add_argument("--timerange", default=default_timerange)
    args = parser.parse_args()

    print("=" * 60)
    print("🔄 GESTIÓN AUTOMÁTICA DE WHITELIST")
    print(f"   Rango: {args.timerange}")
    print(f"   Core pairs: {len(CORE_PAIRS)} (siempre preservados)")
    print(f"   Rejected pairs: {len(REJECTED_PAIRS)} (nunca añadidos)")
    print("=" * 60)

    blacklisted = get_manual_blacklist_bases()
    # REJECTED se trata como blacklist para candidatos, BTC siempre incluido por separado
    excluded_from_candidates = blacklisted | REJECTED_PAIRS | {"BTC"}

    if args.pairs:
        candidates = [c.upper() for c in args.pairs if c.upper() not in excluded_from_candidates]
    else:
        current_wl_bases = {p.split("/")[0] for p in get_current_whitelist()} - excluded_from_candidates
        kraken_top = get_kraken_usd_top(40) - excluded_from_candidates
        candidates = sorted(current_wl_bases | kraken_top)

    current_wl_set = set(get_current_whitelist())

    # --- Evaluar CORE_PAIRS (informativamente — nunca se eliminan) ---
    print(f"\n{'='*60}")
    print("📌 CORE PAIRS (evaluación informativa, siempre preservados)")
    print(f"{'='*60}")
    for coin in sorted(CORE_PAIRS):
        if coin in blacklisted:
            print(f"  ⛔ {coin}/USD — en blacklist manual, excluido")
            continue
        pair = f"{coin}/USD"
        feather = ROOT / "user_data" / "data" / "kraken" / f"{coin}_USD-15m.feather"
        if not feather.exists():
            print(f"  📊 {pair}: sin datos locales — preservado sin evaluar")
            continue
        stats = run_backtest_single(pair, args.timerange)
        if stats is None:
            print(f"  📊 {pair}: backtest falló — preservado sin evaluar")
        elif stats["trades"] == 0:
            print(f"  📊 {pair}: 0 trades en ventana (mercado quieto) — preservado")
        else:
            should_remove, reason = evaluate_for_removal(stats)
            if should_remove is True:
                print(f"  ⚠️  {pair}: {reason} — AVISO (es CORE, se mantiene de todos modos)")
            elif should_remove is None:
                print(f"  ✅ {pair}: {stats['trades']}T, {stats['wr']*100:.1f}% WR, +${stats['total_profit']:.0f} (datos insuficientes para juzgar)")
            else:
                print(f"  ✅ {pair}: {stats['trades']}T, {stats['wr']*100:.1f}% WR, +${stats['total_profit']:.0f}")

    # --- Evaluar candidatos no-CORE ---
    # Excluir CORE_PAIRS del bucle normal (ya tratados arriba)
    non_core_candidates = [c for c in candidates if c not in CORE_PAIRS]
    print(f"\n{'='*60}")
    print(f"🔍 AUTO-DISCOVERY ({len(non_core_candidates)} candidatos no-core)")
    print(f"{'='*60}")

    auto_approved = []   # nuevos o existentes no-core que pasan
    auto_rejected = []   # existentes no-core con evidencia sólida de fallo
    no_data_pairs = []   # sin datos suficientes

    for coin in non_core_candidates:
        pair = f"{coin}/USD"
        is_existing = pair in current_wl_set
        feather = ROOT / "user_data" / "data" / "kraken" / f"{coin}_USD-15m.feather"
        print(f"\n{'─'*50}")
        print(f"📊 {pair}{' [en whitelist]' if is_existing else ' [nuevo]'}")

        if not feather.exists():
            if args.no_download:
                print(f"  ⏭️  Sin datos locales — saltado (--no-download)")
                no_data_pairs.append(pair)
                continue
            if not download_pair_data(pair, args.timerange):
                print(f"  ❌ No se pudieron descargar datos")
                no_data_pairs.append(pair)
                continue

        stats = run_backtest_single(pair, args.timerange)
        if stats is None:
            print(f"  ❌ Backtest falló")
            no_data_pairs.append(pair)
            continue

        if is_existing:
            should_remove, reason = evaluate_for_removal(stats)
            if should_remove is True:
                print(f"  ❌ ELIMINAR: {reason}")
                auto_rejected.append((pair, stats, reason))
            elif should_remove is None:
                print(f"  ⏭️  PRESERVAR: {reason}")
                no_data_pairs.append(pair)
            else:
                print(f"  ✅ MANTENER: {reason}")
                auto_approved.append((pair, stats))
        else:
            passed, reason = evaluate_for_addition(stats)
            if passed is True:
                print(f"  ✅ AÑADIR: {reason}")
                auto_approved.append((pair, stats))
            elif passed is None:
                print(f"  ⏭️  SALTAR: {reason}")
                no_data_pairs.append(pair)
            else:
                print(f"  ❌ RECHAZAR: {reason}")
                auto_rejected.append((pair, stats, reason))

    # --- Construir nueva whitelist ---
    # 1. BTC (siempre)
    # 2. CORE_PAIRS no blacklisteados (siempre, en orden fijo)
    # 3. Auto-aprobados (ordenados por profit descendente)
    # 4. Existentes no-core preservados por datos insuficientes
    core_in_wl = [f"{c}/USD" for c in sorted(CORE_PAIRS) if c not in blacklisted]
    preserved_non_core = [p for p in no_data_pairs if p in current_wl_set and p != "BTC/USD"]
    new_whitelist = (
        ["BTC/USD"]
        + core_in_wl
        + [p for p, _ in sorted(auto_approved, key=lambda x: x[1]["total_profit"], reverse=True)]
        + sorted(p for p in preserved_non_core if p not in set(core_in_wl))
    )

    # --- Resumen ---
    print(f"\n{'='*60}")
    print("📋 RESULTADO FINAL")
    print(f"{'='*60}")
    print(f"\n✅ Nueva whitelist ({len(new_whitelist)} pares):")
    approved_map = {p: s for p, s in auto_approved}
    for p in new_whitelist:
        coin = p.split("/")[0]
        if coin in CORE_PAIRS:
            print(f"  📌 {p}  [CORE]")
        elif p in approved_map:
            s = approved_map[p]
            print(f"  🆕 {p}  {s['trades']}T, {s['wr']*100:.1f}% WR, +${s['total_profit']:.0f}")
        else:
            print(f"  💾 {p}  (preservado)")

    if auto_rejected:
        print(f"\n❌ Excluidos ({len(auto_rejected)}):")
        for pair, stats, reason in auto_rejected:
            coin = pair.split("/")[0]
            tag = " [CORE — ignorado]" if coin in CORE_PAIRS else ""
            print(f"  {pair}: {reason}{tag}")

    if args.dry_run or args.pairs:
        print("\n⚠️  DRY RUN / modo --pairs — no se modifica ningún config")
        return

    current_wl = get_current_whitelist()
    if set(new_whitelist) == set(current_wl):
        print("\nℹ️  Whitelist sin cambios — nada que commitear.")
        return

    added   = set(new_whitelist) - set(current_wl)
    removed = set(current_wl) - set(new_whitelist)
    print(f"\n🔧 Aplicando cambios...")
    if added:
        print(f"  + Añadidos: {', '.join(sorted(added))}")
    if removed:
        print(f"  - Eliminados: {', '.join(sorted(removed))}")

    # Sincronizar con origin/develop antes de commitear (rsync no actualiza .git/)
    subprocess.run(["git", "fetch", "origin", "develop"], cwd=ROOT, capture_output=True)
    subprocess.run(["git", "reset", "--hard", "origin/develop"], cwd=ROOT, capture_output=True)

    overwrite_whitelist(new_whitelist)

    restart = subprocess.run(["sudo", "systemctl", "restart", "freqtrade"], cwd=ROOT)
    if restart.returncode == 0:
        print("\n🔄 Servicio freqtrade reiniciado con la nueva whitelist.")
    else:
        print(f"\n⚠️  systemctl restart falló — whitelist actualizada pero bot NO reiniciado.")

    subprocess.run(["git", "add", str(CONFIG_BASE), str(CONFIG_BACKTEST)], cwd=ROOT)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT)
    if diff.returncode != 0:
        parts = []
        if added:
            parts.append(f"+{' '.join(sorted(added))}")
        if removed:
            parts.append(f"-{' '.join(sorted(removed))}")
        msg = f"chore(whitelist): {', '.join(parts)} [skip ci]"
        subprocess.run(["git", "commit", "-m", msg], cwd=ROOT)
        push = subprocess.run(["git", "push", "origin", "HEAD:develop"], cwd=ROOT)
        if push.returncode == 0:
            print("📝 Whitelist commiteada en GitHub (historial — sin pipeline).")
        else:
            print("⚠️  Commit OK pero git push FALLÓ — revisar SSH deploy key del servidor.")


if __name__ == "__main__":
    main()
