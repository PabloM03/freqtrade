# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **freqtrade** crypto trading bot configured for Binance spot trading with USDC as stake currency. The active strategy (`MyStrategy`) is implemented in `user_data/strategies/CombinedBinHAndCluc.py`.

**Current config summary:**
- Exchange: Binance (spot, USDC)
- Pairs: **17 pairs** — BTC/ACT/BONK/FET/HBAR/JTO/NEAR/PENGU/PNUT/TON/TURBO/WIF/SYN/HEMI/TUT/MMT/PLUME (managed weekly by `validate_pairs.py`)
- Timeframe: **15m**
- Max open trades: 3 | Stake: **unlimited** (~333 USDC/trade with 1000 USDC wallet)
- Blacklisted (losing pairs): CHZ, SEI, SPK, SAGA, OP, LINK, LDO, ALGO, INJ, ARB, XRP, AVAX, LTC, DOGE, ETH, ADA, FLOKI, SOL, PEPE, SHIB, and others
- Dry-run: enabled (1000 USDC simulated wallet)
- API server: `0.0.0.0:8080`

## Config Management

Config is split into two files to allow versioning without exposing credentials:

| File | Git | Purpose |
|------|-----|---------|
| `config.base.json` | ✅ committed | All non-sensitive settings (pairs, timeframe, pairlists, etc.) |
| `config.secrets.json` | ❌ gitignored | API keys, Telegram token, API server credentials |
| `config.secrets.json.example` | ✅ committed | Template showing required secret fields |
| `config.backtest.json` | ✅ committed | StaticPairList override for reproducible backtests |

**Setup on a new machine:** copy `config.secrets.json.example` → `config.secrets.json` and fill in values.

**Server:** `ops/trade.sh` launches `config.base.json + ops/config.secrets.json` (credentials live in `ops/` on the server, excluded from rsync).

## Common Commands

```bash
# freqtrade via conda (no .venv — use conda env)
conda run -n freqtrade freqtrade trade -c config.base.json -c config.secrets.json

# Backtesting — always include config.secrets.json to avoid Telegram schema error
conda run -n freqtrade freqtrade backtesting \
  -c config.base.json -c config.backtest.json -c config.secrets.json \
  -s MyStrategy --timerange 20240201-20251231 --cache none

# Backtesting recent (2025-2026)
conda run -n freqtrade freqtrade backtesting \
  -c config.base.json -c config.backtest.json -c config.secrets.json \
  -s MyStrategy --timerange 20250101-20260301 --cache none

# OOS validation 2022 (bear market stress test)
conda run -n freqtrade freqtrade backtesting \
  -c config.base.json -c config.backtest.json -c config.secrets.json \
  -s MyStrategy --timerange 20220101-20221231 --cache none

# Download historical data
conda run -n freqtrade freqtrade download-data \
  -c config.base.json -c config.backtest.json \
  --timeframes 15m --timerange 20220101-20260901 --prepend

# Hyperopt (parameter optimization — spaces buy+sell only, stoploss is frozen)
conda run -n freqtrade freqtrade hyperopt \
  -c config.base.json -c config.backtest.json -c config.secrets.json \
  -s MyStrategy \
  --spaces buy sell \
  --hyperopt-loss CalmarHyperOptLoss \
  --timerange 20240101-20260901 \
  -e 1500 -j 2 \
  --random-state 42 \
  --min-trades 20

# Plot strategy on data
conda run -n freqtrade freqtrade plot-dataframe -c config.base.json -s MyStrategy

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

### Active strategy: `CombinedBinHAndCluc.py` (v15)
**15m reversal strategy** targeting structural support levels. Enters only on genuine dips; the anti-chase filter intentionally blocks entries in relentless uptrends.

**Indicator scaling (TF_MULT = 4):**
All structure/trend indicators are scaled ×4 to achieve temporal equivalence with what were originally 1h indicators:
- **Signal oscillators** (original periods, reactive to 15m): RSI(14), MACD(12,26,9), StochRSI(14,3,3)
- **Trend/structure indicators** (×4 scaled): EMA8→EMA32(8h), EMA20→EMA80(20h), EMA50→EMA200(50h), ATR(56), ADX(56)
- **BB windows** (already scaled): BB80 (20h equiv), BB180 (45h equiv)
- **Rolling lookbacks** (×4): ll_8→32, ll_10→40, ll_20→80, hh_20→80, roc5→roc20
- **CRITICAL**: rolling windows in `custom_exit` must also use ×4 — e.g. `rolling(6*4)` for 6h, `rolling(20*4)` for 20h

**Entry conditions — ACTIVE:**
- **A** `A_local_min`: loc_trough + ll_10 + bb_deep_zone(≤0.20) + RSI turning up + green candle + vol_spike
- **B** `B_bb_reentry`: 2+ consecutive candles below BB80 → crossing back above + RSI up + MACD not worsening
- **C** `C_stochrsi`: StochRSI(14,3,3) cross oversold (k>d, both <25) + MACD not worsening + EMA80 flat over 4h
- **F** `F_rsi_extreme`: RSI < 37 + RSI up + MACD not worsening + vol_spike + bb_zone_ok + **ai_score > -0.25** (news gate)
- **H** `H_panic_fear`: Fear&Greed < 30 (Extreme Fear) + loc_trough + RSI < 42 + RSI up + MACD + vol_spike + bb_zone
- **K** `K_capitulation`: big drop + tail ≥ ATR(56) × 1.15 + green candle (replaces old D with tighter filters)
- **I** `I_rsi_crash`: RSI < 18 + loc_trough + RSI up + MACD + vol_spike + bb_percent ≤ 0.35 — max capitulation bypass
- **J** `J_ai_news`: ai_score ≥ 0.30 + loc_trough + RSI < 50 + RSI up + MACD + vol_spike — live only (backtest ai_score=0)

**Entry conditions — DISABLED (do not re-enable without thorough backtesting):**
- **D** `D_capitulation`: disabled (0 trades — superseded by K with tighter filters)
- **E** `E_ema8_pullback`: disabled — incompatible with -7% SL; 15m wicks hit SL before the bounce
- **G** `G_hammer`: disabled — negative across all pair subsets tested
- **M** `M_ema80`: disabled — ALL variants negative; 15m wicks reach -7% SL before the pullback resolves

**Triple trend filter (`ema50_ok`) — hyperopt-tuned:**
- EMA200(15m) not falling >1.4% in 48h: `shift(192) × 0.986`
- EMA80(15m) not falling >5.2% in 24h: `shift(96) × 0.948`
- `close >= EMA200(15m) × 0.989`

**Stoploss architecture:**
- Class-level `stoploss = -0.07` (–7% floor from open price)
- `custom_stoploss` manages all exits: ATR-based trailing (2.6–3.6×ATR), threshold-based activation (2.5% largecap / 3.5% meme), floor guard (p ≤ –7% → return –0.001 to trigger immediately)
- **Never use trailing_stop JSON config** — creates LIMIT orders in live trading; use custom_stoploss only

**Custom exits:**
- `crash_guard`: exit if sudden drop detected
- `hard_tp`: 50% profit — lets meme coins (BONK/WIF/TURBO) run in bull cycles
- `peak_exit`: profit ≥ 2.7% + local peak detected
- `hh_ema_break`: profit ≥ 5.5% + HH + EMA32 breakdown

**Hyperopt parameters (current — 4 March 2026, CalmarHyperOptLoss):**
- `buy_c_stoch_max=36`, `buy_bb_zone_ok=0.68`, `buy_a_rsi_prev_max=38`, `buy_f_rsi_max=37`
- `buy_ema50_close_pct=0.989`, `buy_ema50_slope_48h=0.986`, `buy_ema20_slope_24h=0.948`
- `buy_g_bb_zone=0.42`, `buy_g_vol_mult=2.8`, `buy_fg_fear=30`
- `sell_peak_min_profit=0.027`, `sell_hh_ema_min=0.055`
- `stoploss=-0.07` — **FROZEN, never touch via hyperopt**
- Stored in: `user_data/strategies/CombinedBinHAndCluc.json`

**Fear & Greed Index integration:**
- Data source: `user_data/data/sentiment/fear_greed.csv` (Alternative.me API, daily)
- H condition fires when F&G < 30 (Extreme Fear) — contrarian entries at peak panic
- Used ONLY as entry signal, never as a blanket blocking filter

**News intelligence pipeline (live only):**
- `ops/fetch_sentiment.py` — daily: Fear&Greed, CoinGecko trending, Binance volume spikes, RSS news
- `ops/analyze_news.py` — Claude API → `ai_score` per coin (–1 to +1) → `news_themes.json`
- **F condition news gate**: blocks F_rsi_extreme if `ai_score ≤ –0.25`
- **J condition**: direct entry if `ai_score ≥ 0.30` + technical conditions
- **Position sizing** (`custom_stake_amount`): ai_score ≥ 0.25 → ×1.5 stake; ≤ –0.25 → ×0.6; neutral → ×1
- In backtest: ai_score = 0 always → no effect on historical results (live only)

**Backtest results (v15, 15m, 17 pairs, ~333 USDC/trade):**

| Period | Trades | WR | Profit | CAGR | Calmar |
|--------|--------|----|--------|------|--------|
| 2024–2025 (in-sample) | 83 | **90.4%** | +$1,099 (+109.9%) | 47.3% | **80.93** |
| 2025–2026 (recent) | 68 | 85.3% | +$578 (+57.8%) | ~58% | ~18 |
| 2022 OOS (bear) | ~1 | 100% | +$6.80 (+0.68%) | — | — |
| 2023 (OOS recovery) | **0** | — | — | — | — |

**Why 0 trades in 2023:** anti-chase filter correctly blocks buying in relentless uptrend. Strategy is reversal-only → only enters on genuine dips. This is by design.

**Why stoploss is –7%:** tight enough to protect capital, wide enough to survive the sharp wicks common in crypto 15m candles. Real drawdown stays 1–7% because entry quality is high (few bad entries → few SL hits). Wider stops were tested up to –34.7% and produced worse Calmar ratios.

**Strategy comparison:**

| Strategy | 2024–2025 WR | Total Profit | Calmar | Status |
|---|---|---|---|---|
| **MyStrategy v15 (CURRENT)** | **90.4%** | **+$1,099** | **80.93** | ✅ DEPLOYED |
| MyStrategy v5 (news+sizing) | 81% | +$555 | 19.19 | superseded |
| MyStrategy v3 (8 pairs) | 82% | +$620 compuesto | — | superseded |
| FreqAI standalone | — | –10.71% 2024 | — | ❌ DISCARDED |
| FreqAI as filter | — | 0 trades 2024 | — | ❌ DISCARDED |

**Iteration history:**
- v1 (Jan 2025): 37 trades, 57% WR, +$176 (2 years)
- v2 (Mar 2026): 52 trades, 75% WR — HARD_TP 25%→50%, G condition, expanded hyperopt
- v3 (Mar 2026): 44 trades, 82% WR — blacklisted DOGE/ETH/ADA, 8-pair list
- v4 (Mar 2026): same + Fear&Greed integration, H_panic_fear condition
- v5 (Mar 2026): 42 trades, 81% WR — news intelligence (I/J conditions, F gate, position sizing)
- v6–v14 (Apr–Jul 2026): pair expansion, K_capitulation, M condition tested and disabled, validate_pairs automation
- **v15 (Jul 2026)**: rolling×4 fix in custom_exit, M disabled definitively, 13→17 pairs via validate_pairs ← **CURRENT**

### Deployment & CI/CD
- **GitHub Actions** (`.github/workflows/deploy-freqtrade.yml`): pushes to `develop` trigger `rsync` to the production server + systemd restart.
- **rsync excludes** (critical — never remove these): `*.sqlite*`, `user_data/strategies/*.json`, `ops/config.secrets.json`, `ops/params.json`, `user_data/data/`, `user_data/models/`, `logs/`
- **`trades.sqlite` preserved**: rsync excludes `*.sqlite`, `*.sqlite-wal`, `*.sqlite-shm` → trade history survives every deploy. **Never delete trades.sqlite.**
- **Server git is NOT updated by rsync** — only physical files are synced. `validate_pairs.py` does its own `git fetch + reset --hard` before pushing whitelist changes.
- **Systemd service**: `freqtrade.service` runs the bot; restart via `sudo systemctl restart freqtrade`.
- **`ops/trade.sh`**: production start — `config.base.json + ops/config.secrets.json`.
- **Server SSH**: `ssh -i ~/oracle/ssh-key-2025-06-22.key ubuntu@151.145.35.106`

### Pairlist & weekly validation
The active pairlist uses `StaticPairList` with 17 pairs (managed by `validate_pairs.py`). `config.backtest.json` also uses `StaticPairList` for reproducible backtests.

**`ops/validate_pairs.py`** runs every Monday at 00:10 UTC (via `cron_daily.sh`):
- Fetches Binance top-40 USDC pairs by volume
- Backtests each candidate on a rolling 1-year window
- Adds pairs with WR ≥ 75% and ≥ 3 trades
- Removes non-core pairs with WR < 65% (≥ 4 trades) OR profit < –$10 (≥ 3 trades)
- Pushes changes to `develop` with `[skip ci]` to avoid triggering deploy

**Core pairs** (never auto-removed by validate_pairs): BTC, BONK, WIF, TURBO

### Quarterly hyperopt (`ops/run_hyperopt.sh`)
Runs on 02:00 UTC on the 1st of Jan/Apr/Jul/Oct:
1. Downloads 15m data from 2022 (includes OOS bear market)
2. Hyperopt on recent window (last 24 months), `CalmarHyperOptLoss`, spaces `buy+sell` only
3. 1500 epochs, `-j 2` (NOT -j -1 — causes OOM crash on the server), `--random-state 42`, `--min-trades 20`
4. OOS stress test: backtest on 2022 alone — WR < 40% → restore backup and abort
5. If OK → restart `freqtrade.service` with new params

Last successful run: **4 March 2026**. July 2026 run crashed (OOM, SIGKILL) — fixed to `-j 2`.

## Key Files

| File | Purpose |
|------|---------|
| `config.base.json` | Bot config (exchange, 17 pairs, StaticPairList) — committed |
| `config.secrets.json` | API keys, Telegram — gitignored (on server: `ops/config.secrets.json`) |
| `config.backtest.json` | Backtest override (StaticPairList, same 17 pairs) — committed |
| `user_data/strategies/CombinedBinHAndCluc.py` | Active strategy (`MyStrategy`) — reversal 15m, v15 |
| `user_data/strategies/CombinedBinHAndCluc.json` | Hyperopt params (auto-exported, excluded from rsync) |
| `ops/validate_pairs.py` | Weekly pair evaluation — backtests candidates, updates whitelist |
| `ops/run_hyperopt.sh` | Quarterly hyperopt + OOS validation + atomic deploy |
| `ops/analyze_news.py` | News intelligence: Claude API → ai_score per coin → `news_themes.json` |
| `ops/fetch_sentiment.py` | Daily pipeline: Fear&Greed + CoinGecko + Binance spikes + RSS |
| `ops/cron_daily.sh` | Cron 00:10 UTC: fetch_sentiment + analyze_news + validate_pairs (Mondays) |
| `ops/trade.sh` | Production start script |
| `ops/setup_server.sh` | One-time server setup: pip install + ops/.env + crontab |
| `freqtrade.service` | Systemd unit template |
| `.github/workflows/deploy-freqtrade.yml` | CI/CD deploy pipeline |

## Hyperopt — Reference

**Loss function**: `CalmarHyperOptLoss` (profit / max drawdown). Never use `OnlyProfitHyperOptLoss` — it ignores drawdown and overfits to bull markets.

**Spaces**: always `buy sell` — **never include `stoploss`**, it is frozen at –7% in the class definition.

**Timerange**: always include 2022 (extreme bear OOS) to avoid overfitting to bull market data.

**Manual command:**
```bash
conda run -n freqtrade freqtrade hyperopt \
  -c config.base.json -c config.backtest.json -c config.secrets.json \
  -s MyStrategy \
  --spaces buy sell \
  --hyperopt-loss CalmarHyperOptLoss \
  --timerange 20220101-20260901 \
  -e 1500 -j 2 \
  --random-state 42 \
  --min-trades 20
```

**OOS validation (mandatory after hyperopt):**
```bash
conda run -n freqtrade freqtrade backtesting \
  -c config.base.json -c config.backtest.json -c config.secrets.json \
  -s MyStrategy --timerange 20220101-20221231 --cache none
```
- WR ≥ 40% in 2022 → accept params (strategy is bull-market reversal, not bear-market — 40% is the floor)
- WR < 40% → discard (overfit to bull market)

**Note**: `--export-params` does not exist in freqtrade. Params are auto-exported to `user_data/strategies/CombinedBinHAndCluc.json` after hyperopt completes.

## Important Notes

- **Stoploss is frozen at –7%**: never change via hyperopt or CLI. `custom_stoploss` manages the trailing logic; the class-level stoploss is a hard floor.
- **Never use `trailing_stop` JSON config** — it creates LIMIT orders in live trading. All trailing is handled by `custom_stoploss`.
- **Always add `-c config.secrets.json`** to backtests and hyperopt — omitting it causes a Telegram config schema error.
- `config.secrets.json` is gitignored. On the server it lives at `ops/config.secrets.json` (excluded from rsync). Copy from `config.secrets.json.example` to set up a new machine.
- **Never delete `trades.sqlite`** — it holds dry-run trade history. At most create a backup.
- When modifying `CombinedBinHAndCluc.py`, all tunable constants are at the top of the file — prefer changing those over touching the logic.
- Use `conda run -n freqtrade` to run freqtrade — there is no `.venv`, the env is in anaconda. For direct Python: `/home/pablom03/anaconda3/envs/freqtrade/bin/python`.
- `--timeframe-detail 5m` crashes with `informative_pairs()` KeyError — never use this flag.
- The `develop` branch is the main working branch (matches CI/CD trigger).
- `config.backtest.json` is committed and used for reproducible backtests (StaticPairList override).
