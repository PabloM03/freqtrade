# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **freqtrade** crypto trading bot configured for Binance spot trading with USDC as stake currency. The active strategy (`MyStrategy`) is implemented in `user_data/strategies/CombinedBinHAndCluc.py`.

**Current config summary:**
- Exchange: Binance (spot, USDC)
- Pairs: SOL, PEPE, DOGE, SHIB, BONK, WIF, TURBO, LTC (against USDC)
- Timeframe: 5m
- Max open trades: 3 | Stake: 25 USDC
- Dry-run: enabled (1000 USDC simulated wallet)
- API server: `0.0.0.0:8080`

## Common Commands

```bash
# Activate virtual environment first
source .venv/bin/activate

# Run the bot (uses config.json, dry_run=true by default)
freqtrade trade -c config.json

# Backtesting
freqtrade backtesting -c config.json -s MyStrategy --timerange 20240101-20241231

# Download historical data
freqtrade download-data -c config.json --timeframes 5m 1h

# Hyperopt (parameter optimization)
freqtrade hyperopt -c config.json -s MyStrategy --spaces buy sell stoploss trailing --epochs 300

# Plot strategy on data
freqtrade plot-dataframe -c config.json -s MyStrategy

# Create a new strategy from template
freqtrade new-strategy -s MyNewStrategy

# Run tests
pytest tests/

# Run a single test file
pytest tests/test_freqtradebot.py -v

# Run tests with coverage
pytest --cov=freqtrade tests/

# Switch active strategy and restart service (on server)
./change.Strategy.sh MyNewStrategy.py
```

## Architecture

### Core framework (`freqtrade/`)
The bot follows a clear pipeline on each tick (~5s):
1. `FreqtradeBot` (`freqtradebot.py`) orchestrates the main loop
2. Fetches OHLCV candles via `exchange/` (CCXT wrapper)
3. Passes dataframes through strategy's `populate_indicators()` → `populate_buy_trend()` → `populate_sell_trend()`
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
Low-frequency, high-probability strategy targeting structural support levels. Key design:
- **6 entry conditions (A–F):** local minimum reversals, BB re-entries, StochRSI oversold, capitulation patterns, EMA8 pullbacks, double-touch in value zone
- **Anti-chase filters:** blocks entries on pumps, breakouts, or near recent highs
- **ATR-based adaptive trailing stop:** switches multipliers based on ADX strength and ROC momentum
- **Crash guard:** detects sudden drops and exits early
- **All tunable parameters** are global constants at the top of the file (e.g. `FEE_RATE`, `STOPLOSS_ABS`, `HARD_TP`)

### Deployment & CI/CD
- **GitHub Actions** (`.github/workflows/deploy-freqtrade.yml`): pushes to `develop` trigger an `rsync` to the production server and restart the systemd service. `config.json` is **excluded** from sync to preserve live credentials.
- **Systemd service**: `freqtrade.service` runs the bot as a daemon; restart via `sudo systemctl restart freqtrade`.
- **`ops/trade.sh`**: production start script (uses `ops/config.withparams.json`, not root `config.json`).
- **`ops/train_and_deploy.sh`**: rolling hyperopt script — downloads 200 days of data, runs 1200 epochs, deploys `ops/params.json` atomically, then restarts the service.

### Pairlist & filtering
The active pairlist uses `VolumePairList` (top 9 by quote volume, refreshed every 15 min). The static whitelist in `config.json` overrides this during backtesting. The blacklist regex `.*/(?!USDC$).*` enforces that only `*/USDC` pairs are ever traded.

## Key Files

| File | Purpose |
|------|---------|
| `config.json` | Bot configuration (exchange, pairs, stake, API server) |
| `user_data/strategies/CombinedBinHAndCluc.py` | Active strategy (`MyStrategy`) |
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
