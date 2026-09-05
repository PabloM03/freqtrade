#!/usr/bin/env python3
"""
validate_pairs_prop.py — Actualización mensual de pares del bot prop (Kraken Prop challenge).

Universo fijo: solo pares disponibles en la plataforma Kraken Prop.
Lógica: backtest rolling 12 meses → selecciona top N por WR y profit.
Aplica directamente en config.prop.json (gitignored) + reinicia freqtrade-prop.
"""
import json, os, re, shutil, subprocess, sys
from datetime import datetime, timedelta
from pathlib import Path

# ── Configuración ────────────────────────────────────────────────────────────
BASE      = Path("/home/ubuntu/freqtrade")
OPS       = BASE / "ops"
PROP_CFG  = OPS / "config.prop.json"
DATA_DIR  = BASE / "user_data/data/kraken"
LOG_TAG   = "[validate_pairs_prop]"

# Universo completo de pares disponibles en Kraken Prop (hardcoded — no modificar sin revisar la plataforma)
PROP_UNIVERSE = [
    "AAVE", "ADA", "AIXBT", "ALGO", "APT", "ARB", "ASTER", "ATOM",
    "AVAX", "BCH", "BNB", "BTC", "DOGE", "DOT", "ETC", "ETH",
    "FARTCOIN", "FIL", "GRASS", "HBAR", "PUMP", "RENDER", "SOL",
    "STX", "SUI", "TAO", "TIA", "TRUMP", "TRX", "UNI", "VIRTUAL",
    "WIF", "WLD", "XRP", "ZEC",
]

CORE_PAIRS     = {"BTC"}          # siempre incluidos aunque no pasen el filtro
MIN_TRADES     = 2                # mínimo de trades para considerar el par
MIN_WR         = 0.65             # win rate mínimo para seleccionar
MIN_PROFIT     = 0.0              # profit total mínimo (USD)
MAX_PAIRS      = 6                # máximo de pares en el prop bot
TIMERANGE_DAYS = 365              # ventana rolling en días

FREQTRADE = str(BASE.parent / "miniconda3/envs/freqtrade/bin/freqtrade")

# ── Helpers ──────────────────────────────────────────────────────────────────
def log(msg):
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{ts} {LOG_TAG} {msg}", flush=True)

def pairs_with_data():
    """Retorna los pares del universo Prop que tienen datos 15m en local."""
    available = []
    for coin in PROP_UNIVERSE:
        path = DATA_DIR / f"{coin}_USD-15m.feather"
        if path.exists():
            available.append(f"{coin}/USD")
        else:
            log(f"  sin datos: {coin}/USD — omitido")
    return available

def run_backtest(pairs: list[str], timerange: str) -> str:
    """Ejecuta backtest y devuelve stdout."""
    tmp_cfg = OPS / "config.prop_validate_tmp.json"
    tmp_cfg.write_text(json.dumps({
        "pairs": pairs,
        "pairlists": [{"method": "StaticPairList"}],
        "max_open_trades": 1,
    }))
    try:
        result = subprocess.run(
            [FREQTRADE, "backtesting",
             "-c", str(BASE / "config.base.json"),
             "-c", str(tmp_cfg),
             "-c", str(OPS / "config.secrets.json"),
             "-s", "MyStrategy",
             "--timerange", timerange,
             "--cache", "none"],
            capture_output=True, text=True, timeout=1200,
            cwd=str(BASE)
        )
        return result.stdout + result.stderr
    finally:
        tmp_cfg.unlink(missing_ok=True)

def parse_pair_results(output: str) -> dict:
    """
    Parsea la tabla BACKTESTING REPORT del output de freqtrade.
    Retorna dict: pair -> {trades, wr, profit_usd}
    """
    results = {}
    in_table = False
    for line in output.splitlines():
        if "BACKTESTING REPORT" in line:
            in_table = True
            continue
        if not in_table:
            continue
        # línea de datos: │  WIF/USD │  6 │ ...
        m = re.match(r"[│┃]\s+([\w/]+)\s+[│┃]\s+(\d+)\s+[│┃]\s+[-\d.]+\s+[│┃]\s+([-\d.]+)\s+[│┃].*[│┃]\s+(\d+)\s+\d+\s+(\d+)\s+([\d.]+)\s*[│┃]", line)
        if not m:
            continue
        pair     = m.group(1).strip()
        trades   = int(m.group(2))
        profit   = float(m.group(3))
        wins     = int(m.group(4))
        losses   = int(m.group(5))
        wr_str   = m.group(6)
        wr       = float(wr_str) / 100 if float(wr_str) > 1 else float(wr_str)
        if pair == "TOTAL":
            break
        results[pair] = {"trades": trades, "wr": wr, "profit_usd": profit, "wins": wins, "losses": losses}
    return results

def select_pairs(results: dict, available: list[str]) -> list[str]:
    """Selecciona hasta MAX_PAIRS pares que superen los filtros, siempre incluyendo CORE_PAIRS."""
    selected = []

    # 1. Core pairs primero (si tienen datos)
    for coin in CORE_PAIRS:
        pair = f"{coin}/USD"
        if pair in available:
            selected.append(pair)
            log(f"  CORE {pair} → incluido siempre")

    # 2. Resto ordenado por WR desc, profit desc
    candidates = []
    for pair, r in results.items():
        if pair in selected:
            continue
        if r["trades"] < MIN_TRADES:
            log(f"  {pair}: {r['trades']} trades < {MIN_TRADES} mínimo → omitido")
            continue
        if r["wr"] < MIN_WR:
            log(f"  {pair}: WR {r['wr']:.1%} < {MIN_WR:.0%} → omitido")
            continue
        if r["profit_usd"] < MIN_PROFIT:
            log(f"  {pair}: profit {r['profit_usd']:.2f} USD < {MIN_PROFIT} → omitido")
            continue
        log(f"  {pair}: {r['trades']}T  WR {r['wr']:.1%}  {r['profit_usd']:+.2f} USD → CANDIDATO")
        candidates.append((pair, r))

    candidates.sort(key=lambda x: (x[1]["wr"], x[1]["profit_usd"]), reverse=True)

    for pair, r in candidates:
        if len(selected) >= MAX_PAIRS:
            break
        selected.append(pair)
        log(f"  → SELECCIONADO {pair}")

    # Pares con 0 trades (datos insuficientes / estrategia no entra)
    for pair in available:
        if pair not in results and pair not in selected:
            log(f"  {pair}: 0 trades → omitido")

    return selected

def update_prop_config(new_pairs: list[str]):
    """Actualiza la lista de pares en config.prop.json."""
    backup = PROP_CFG.with_suffix(".json.bak")
    shutil.copy(PROP_CFG, backup)
    cfg = json.loads(PROP_CFG.read_text())
    old_pairs = cfg.get("pairs", [])
    cfg["pairs"] = new_pairs
    cfg["exchange"] = cfg.get("exchange", {})
    cfg["exchange"]["pair_whitelist"] = new_pairs
    PROP_CFG.write_text(json.dumps(cfg, indent=2))
    return old_pairs

def restart_prop_bot():
    subprocess.run(["sudo", "systemctl", "restart", "freqtrade-prop"], check=True)
    log("freqtrade-prop reiniciado")

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    log("=== inicio validate_pairs_prop ===")

    # Rango de fechas rolling
    end   = datetime.utcnow()
    start = end - timedelta(days=TIMERANGE_DAYS)
    timerange = f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"
    log(f"Timerange: {timerange}  |  Universo: {len(PROP_UNIVERSE)} pares")

    # Pares con datos disponibles
    available = pairs_with_data()
    log(f"Con datos locales: {len(available)} pares")

    if not available:
        log("ERROR: ningún par tiene datos — abortando")
        sys.exit(1)

    # Backtest
    log("Ejecutando backtest...")
    output = run_backtest(available, timerange)

    # Parsear resultados
    results = parse_pair_results(output)
    log(f"Pares con trades: {len(results)}")

    if not results:
        log("ERROR: no se pudieron parsear resultados — abortando sin cambios")
        sys.exit(1)

    # Selección
    log("Evaluando candidatos...")
    new_pairs = select_pairs(results, available)

    if not new_pairs:
        log("ERROR: ningún par superó los filtros — manteniendo config actual")
        sys.exit(1)

    log(f"Pares seleccionados ({len(new_pairs)}): {new_pairs}")

    # Actualizar config
    old_pairs = update_prop_config(new_pairs)
    log(f"config.prop.json actualizado  |  antes: {old_pairs}  |  ahora: {new_pairs}")

    # Reiniciar bot prop
    restart_prop_bot()
    log("=== fin validate_pairs_prop ===")

if __name__ == "__main__":
    main()
