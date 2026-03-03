# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **freqtrade** crypto trading bot configured for Binance spot trading with USDC as stake currency. The active strategy (`MyStrategy`) is implemented in `user_data/strategies/CombinedBinHAndCluc.py`.

**Current config summary:**
- Exchange: Binance (spot, USDC)
- Pairs: BTC, ETH, SOL, DOGE, ADA, LINK, PEPE, SHIB, BONK, WIF, TURBO (vs USDC) — 11 pairs, VolumePairList top-40
- Timeframe: **15m** (migrated from 1h → more trades)
- Max open trades: 5 | Stake: **unlimited** (~200 USDC/trade with 1000 USDC wallet)
- Blacklisted: XRP, AVAX, LTC (0 wins across 2 years, consistent stop-losses)
- Dry-run: enabled (1000 USDC simulated wallet)
- API server: `0.0.0.0:8080`

## Common Commands

```bash
# freqtrade via conda (no .venv — use conda env)
conda run -n freqtrade freqtrade trade -c config.json

# Backtesting
conda run -n freqtrade freqtrade backtesting -c config.json -c config.backtest.json -s MyStrategy --timerange 20240101-20241231 --cache none

# Download historical data
conda run -n freqtrade freqtrade download-data -c config.json -c config.backtest.json --timeframes 15m --timerange 20230101-20260303 --prepend

# Hyperopt (parameter optimization)
conda run -n freqtrade freqtrade hyperopt -c config.json -s MyStrategy --spaces buy sell stoploss trailing --epochs 300

# Plot strategy on data
conda run -n freqtrade freqtrade plot-dataframe -c config.json -s MyStrategy

# Create a new strategy from template
conda run -n freqtrade freqtrade new-strategy -s MyNewStrategy

# Switch active strategy and restart service (on server)
./change.Strategy.sh MyNewStrategy.py
```

## Architecture

### Core framework (`freqtrade/`)
The bot follows a clear pipeline on each tick (~5s):
1. `FreqtradeBot` (`freqtradebot.py`) orchestrates the main loop
2. Fetches OHLCV candles via `exchange/` (CCXT wrapper)
3. Passes dataframes through strategy's `populate_indicators()` → `populate_entry_trend()` → `populate_exit_trend()`
4. Executes orders, then calls `custom_stoploss()` and `custom_exit()` per open trade
5. Sends updates via `rpc/` (Telegram, REST API, WebSocket)

Trades are persisted in `trades.sqlite` (SQLAlchemy models in `persistence/`).

### Strategy interface (`IStrategy`)
Strategies live in `user_data/strategies/` and extend `IStrategy`. Key methods to implement:
- `populate_indicators(dataframe, metadata)` — add columns to the OHLCV dataframe
- `populate_entry_trend(dataframe, metadata)` — set `dataframe['enter_long'] = 1`
- `populate_exit_trend(dataframe, metadata)` — set `dataframe['exit_long'] = 1`
- `custom_stoploss(...)` — dynamic per-trade trailing stop (return float 0..1 from open price)
- `custom_exit(...)` — advanced exit conditions (return reason string or None)

### Active strategy: `CombinedBinHAndCluc.py`
**15m reversal strategy** targeting structural support levels with higher trade frequency than 1h. Key design:

**Indicator scaling (hybrid approach):**
- **Signal oscillators** (original periods, reactive to 15m): RSI(14), MACD(12,26,9), StochRSI(14,3,3)
- **Trend/structure indicators** (×4 scaled for temporal equivalence): EMA8→EMA32(8h), EMA20→EMA80(20h), EMA50→EMA200(50h), ATR(56), ADX(56)
- **BB windows** (already scaled): BB80 (20h equiv), BB180 (45h equiv)
- **Rolling lookbacks** (×4): ll_8→32, ll_10→40, ll_20→80, hh_20→80, roc5→roc20

**6 entry conditions (A–F):**
- **A** `A_local_min`: loc_trough + ll_10 + bb_deep_zone(≤0.20) + RSI turning up + green candle + vol_spike + MACD>0
- **B** `B_bb_reentry`: 2+ consecutive candles below BB80 → crossing back above + RSI up + MACD not worsening
- **C** `C_stochrsi`: StochRSI(14,3,3) cross oversold (k>d, both <25) + MACD not worsening + EMA80 flat over 4h (shift(16))
- **D** `D_capitulation`: big drop + tail ≥ ATR(56) × 1.15 + green candle
- **E** `E_ema8_pullback`: cross above EMA32 + EMA32 rising + RSI strong
- **F** `F_rsi_extreme`: RSI < 25 + RSI up + MACD not worsening + vol_spike + bb_zone_ok

**Triple trend filter (ema50_ok) — uses hyperopt-tuned params:**
- EMA200(15m) not falling >1.8% in 48h (shift(192) × 0.982)
- EMA80(15m) not falling >1.4% in 24h (shift(96) × 0.986)
- close >= EMA200(15m) × **0.992** (stricter than default 0.978 — tighter filter)

**Custom exits:** crash guard, hard_tp (25%), peak exits ≥2.4%, HH+EMA32 break ≥4.4%

**Hyperopt parameters** (saved in `CombinedBinHAndCluc.json`, loaded automatically):
- `buy_c_stoch_max=32`, `buy_bb_zone_ok=0.68`, `buy_a_rsi_prev_max=42`, `buy_f_rsi_max=35`
- `buy_ema50_close_pct=0.992`, `buy_ema50_slope_48h=0.982`, `buy_ema20_slope_24h=0.986`
- `sell_peak_min_profit=0.024`, `sell_hh_ema_min=0.044`, `stoploss=-0.06`

**Backtest results (15m hybrid hyperopt, ~200 USDC/trade, 11 pairs, no AVAX/XRP/LTC):**
- 2024: **15 trades, 60% WR, +80.22 USDC (+8.02%)**, max drawdown 3.63%
- 2025: **22 trades, 54.5% WR, +96.25 USDC (+9.62%)**, max drawdown 3.62% (vs market -54.36%)
- Combined 2 years: **+176.47 USDC (+17.6%)** — 37 trades, 56.8% WR avg

**Iteration history (15m):**
- Baseline pre-hyperopt: 34 trades, 44.1% WR, +185.55 USDC (2 years)
- Hyperopt pure (-30% SL): 86.7% WR in 2024 — OVERFITTED (DOGE -30% in 2025)
- Hybrid (-6% SL + hyperopt entry/exit): **37 trades, 57% WR, +176.47 USDC** ← CURRENT

**1h baseline (for comparison):**
- 2024: 9 trades, 55.6% WR, +39.87 USDC — 2025: 6 trades, 66.7% WR, +273.55 USDC (BONK outlier)
- 15m hybrid gives better WR (57% vs 44% baseline 15m) with consistent drawdown ≤3.6%

### Deployment & CI/CD
- **GitHub Actions** (`.github/workflows/deploy-freqtrade.yml`): pushes to `develop` trigger an `rsync` to the production server and restart the systemd service. `config.json` is **excluded** from sync to preserve live credentials.
- **Systemd service**: `freqtrade.service` runs the bot as a daemon; restart via `sudo systemctl restart freqtrade`.
- **`ops/trade.sh`**: production start script (uses `ops/config.withparams.json`, not root `config.json`).
- **`ops/train_and_deploy.sh`**: rolling hyperopt script — downloads 200 days of data, runs 1200 epochs, deploys `ops/params.json` atomically, then restarts the service.

### Pairlist & filtering
The active pairlist uses `VolumePairList` (top 40 by quote volume ≥100K USDC, refreshed every 15 min). A fixed whitelist of 11 quality pairs seeds the list. `config.backtest.json` overrides to `StaticPairList` for reproducible backtests. The blacklist enforces `*/USDC` only, and explicitly excludes XRP, AVAX, and LTC (consistent losing pairs across all timeframes tested).

## Key Files

| File | Purpose |
|------|---------|
| `config.json` | Bot configuration (exchange, pairs, stake, API server) |
| `user_data/strategies/CombinedBinHAndCluc.py` | Active strategy (`MyStrategy`) |
| `config.backtest.json` | Backtest override (StaticPairList, 11 pairs) |
| `ops/trade.sh` | Production start script |
| `ops/train_and_deploy.sh` | Periodic hyperopt + atomic deploy |
| `change.Strategy.sh` | Switch strategy + restart service |
| `freqtrade.service` | Systemd unit template |
| `.github/workflows/deploy-freqtrade.yml` | CI/CD deploy pipeline |

## Important Notes

- **Never pass CLI flags that override strategy parameters** when running in production — strategy reads from JSON config (`ops/config.withparams.json`).
- `config.json` contains API credentials and is excluded from CI/CD sync. Keep it out of commits.
- When modifying `CombinedBinHAndCluc.py`, all tunable constants are at the top of the file — prefer changing those constants over touching the logic.
- The `develop` branch is the main working branch (matches CI/CD trigger and freqtrade's own convention).
- Use `conda run -n freqtrade` to run freqtrade — there is no `.venv`, the environment is in anaconda.
- `config.backtest.json` is gitignored but must exist locally to run backtests.
