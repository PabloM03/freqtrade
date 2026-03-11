# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **freqtrade** crypto trading bot configured for Binance spot trading with USDC as stake currency. The active strategy (`MyStrategy`) is implemented in `user_data/strategies/CombinedBinHAndCluc.py`.

**Current config summary:**
- Exchange: Binance (spot, USDC)
- Pairs: BTC, SOL, LINK, PEPE, SHIB, BONK, WIF, TURBO (vs USDC) — **8 pairs** (DOGE/ETH/ADA removed: consistently losing)
- Timeframe: **15m** (migrated from 1h → more trades)
- Max open trades: 5 | Stake: **unlimited** (~200 USDC/trade with 1000 USDC wallet)
- Blacklisted: XRP, AVAX, LTC, DOGE, ETH, ADA, FLOKI (0 wins or consistent stop-losses across all timeframes tested)
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

**Server:** `ops/config.withparams.json` remains the single production config (set up manually on server).

## Common Commands

```bash
# freqtrade via conda (no .venv — use conda env)
conda run -n freqtrade freqtrade trade -c config.base.json -c config.secrets.json

# Backtesting (no secrets needed)
conda run -n freqtrade freqtrade backtesting -c config.base.json -c config.backtest.json -s MyStrategy --timerange 20240101-20241231 --cache none

# Download historical data
conda run -n freqtrade freqtrade download-data -c config.base.json -c config.backtest.json --timeframes 15m --timerange 20230101-20260303 --prepend

# Hyperopt (parameter optimization)
conda run -n freqtrade freqtrade hyperopt -c config.base.json -c config.backtest.json -s MyStrategy --spaces buy sell stoploss --hyperopt-loss OnlyProfitHyperOptLoss --epochs 500 -j -1

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

### Active strategy: `CombinedBinHAndCluc.py`
**15m reversal strategy** targeting structural support levels with higher trade frequency than 1h. Key design:

**Indicator scaling (hybrid approach):**
- **Signal oscillators** (original periods, reactive to 15m): RSI(14), MACD(12,26,9), StochRSI(14,3,3)
- **Trend/structure indicators** (×4 scaled for temporal equivalence): EMA8→EMA32(8h), EMA20→EMA80(20h), EMA50→EMA200(50h), ATR(56), ADX(56)
- **BB windows** (already scaled): BB80 (20h equiv), BB180 (45h equiv)
- **Rolling lookbacks** (×4): ll_8→32, ll_10→40, ll_20→80, hh_20→80, roc5→roc20

**8 entry conditions (A–H):**
- **A** `A_local_min`: loc_trough + ll_10 + bb_deep_zone(≤0.20) + RSI turning up + green candle + vol_spike + MACD>0
- **B** `B_bb_reentry`: 2+ consecutive candles below BB80 → crossing back above + RSI up + MACD not worsening
- **C** `C_stochrsi`: StochRSI(14,3,3) cross oversold (k>d, both <25) + MACD not worsening + EMA80 flat over 4h
- **D** `D_capitulation`: big drop + tail ≥ ATR(56) × 1.15 + green candle
- **E** `E_ema8_pullback`: cross above EMA32 + EMA32 rising + RSI strong
- **F** `F_rsi_extreme`: RSI < 25 + RSI up + MACD not worsening + vol_spike + bb_zone_ok
- **G** `G_hammer`: hammerish candle + bb_percent ≤ 0.42 + vol > 2.8x mean + RSI up + MACD + directional alcista
- **H** `H_panic_fear`: Fear&Greed < 30 (Extreme Fear) + loc_trough + RSI < 42 + RSI up + MACD + vol_spike + bb_zone (contrarian: añade entradas en pánico macro)

**Triple trend filter (ema50_ok) — uses hyperopt-tuned params:**
- EMA200(15m) not falling >1.4% in 48h (shift(192) × 0.986)
- EMA80(15m) not falling >5.2% in 24h (shift(96) × 0.948)
- close >= EMA200(15m) × **0.989**

**Custom exits:** crash guard, hard_tp (**50%** — deja correr memes), peak exits ≥2.7%, HH+EMA32 break ≥5.5%

**Hyperopt parameters v2** (500 epochs, OnlyProfitHyperOptLoss, 2024+2025 combined, saved in `CombinedBinHAndCluc.json`):
- `buy_c_stoch_max=36`, `buy_bb_zone_ok=0.68`, `buy_a_rsi_prev_max=38`, `buy_f_rsi_max=37`
- `buy_ema50_close_pct=0.989`, `buy_ema50_slope_48h=0.986`, `buy_ema20_slope_24h=0.948`
- `buy_g_bb_zone=0.42`, `buy_g_vol_mult=2.8`, `buy_fg_fear=30`
- `sell_peak_min_profit=0.027`, `sell_hh_ema_min=0.055`, `stoploss=-0.347`

**Fear & Greed Index integration:**
- Data source: `user_data/data/sentiment/fear_greed.csv` (Alternative.me API, daily, 2018+)
- Used ONLY as entry signal (H condition) — NOT as blocking filter (would hurt 2024 bull runs)
- H fires when F&G < 30 (Extreme Fear) + loc_trough → contrarian entries in max panic moments
- Effect: 2024/2025 unchanged, 2022 OOS +1 extra winner trade

**Backtest results (15m, ~200 USDC/trade, 8 pairs: BTC/SOL/LINK/PEPE/SHIB/BONK/WIF/TURBO) — v4 (Fear&Greed):**
- 2022 (OOS bear): **8 trades, 87.5% WR, +3.93% (+39.3 USDC)**, max drawdown 0.82% ✅
- 2023 (OOS recovery): **0 trades** — anti_chase blocks entries in relentless uptrend (by design)
- 2024 (in-sample): **20 trades, 85.0% WR, +234.36 USDC (+23.44%)**, max drawdown 5.04%
- 2025 (in-sample): **24 trades, 79.2% WR, +312.39 USDC (+31.24%)**, max drawdown 6.61%
- **CAGR 2024-2025 compuesto: ~27.3% anual** (1000 → 1234 → 1619 USDC, +62%)

**Pair selection analysis (why 8 pairs):**
- DOGE: 3 trades, 33.3% WR, -47.5 USDC in 2025 → BLACKLISTED
- ETH: 1 trade, 0% WR, -26.4 USDC in 2025, 0 trades 2024 → BLACKLISTED
- ADA: -8.4 USDC (2024) + -12.3 USDC (2025) = consistently losing → BLACKLISTED
- BONK/WIF/TURBO: meme coins, 100% WR, main profit drivers (BONK alone: +131.9 USDC in 2024)
- C_stochrsi is the star condition: 19 trades over 2y, +298 USDC (67% of total profit)

**Strategy comparison (final):**

| Strategy | 2022 | 2023 | 2024 | 2025 | Total |
|---|---|---|---|---|---|
| **MyStrategy v4 (F&G, DEPLOYED)** | **+3.93%** | 0% | **+23.44%** | **+31.24%** | **+62% compuesto** |
| MyStrategy v3 (8 pairs) | +2.47% | 0% | +23.44% | +31.24% | +62% compuesto |
| MyStrategy v2 (11 pairs) | +1.81% | 0% | +22.42% | +22.38% | +48.03% |
| MyStrategy v1 (old) | -3.18% | 0% | +8.02% | +9.62% | +14.46% |
| FreqAI Hybrid | N/A | N/A | 0 trades | +3.57% | failed |
| TrendFollowing15m | -17.5% | — | — | — | failed |

**Why no 2023 trades:** anti_chase filter correctly blocks buying in relentless uptrend (price above EMA80/BB_mid). Strategy is reversal-only → only enters on genuine dips. Missing 2023 rally is a design trade-off for safety.

**Stoploss -34.7% rationale:** Wide stop allows deep-dipping trades to recover (crypto dips 20-30% then recovers in bull runs). Quality entry filters mean few bad entries → few stoploss hits → real drawdown stays 1-7%. Validated: 2022 out-of-sample showed only 1.6% drawdown with -34.7% SL.

**Iteration history (15m):**
- v1 (Jan 2025): 37 trades, 57% WR, +176.47 USDC (2 years)
- v2 (Mar 2026): 52 trades, 75% WR avg, +448 USDC (2 years) — HARD_TP 25%→50%, G condition, expanded hyperopt ranges
- v3 (Mar 2026): **44 trades, 82% WR avg, +62% compuesto** — Blacklisted DOGE/ETH/ADA, 8-pair optimal list
- v4 (Mar 2026): **Same 2024+2025 + 2022 OOS +3.93% (was +2.47%)** — Fear&Greed Index integrado, condición H_panic_fear ← CURRENT

### Deployment & CI/CD
- **GitHub Actions** (`.github/workflows/deploy-freqtrade.yml`): pushes to `develop` trigger an `rsync` to the production server and restart the systemd service. `config.json` is **excluded** from sync to preserve live credentials.
- **Systemd service**: `freqtrade.service` runs the bot as a daemon; restart via `sudo systemctl restart freqtrade`.
- **`ops/trade.sh`**: production start script (uses `ops/config.withparams.json`, not root `config.json`).
- **`ops/train_and_deploy.sh`**: rolling hyperopt script — downloads data desde 20220101 (incluye 2022 bear OOS), corre 1200 epochs con `CalmarHyperOptLoss` (profit/drawdown), valida en OOS 2022 (aborta si WR < 40%), despliega params atómicamente y reinicia el servicio.

### Pairlist & filtering
The active pairlist uses `VolumePairList` (top 40 by quote volume ≥100K USDC, refreshed every 15 min). A fixed whitelist of 8 quality pairs seeds the list. `config.backtest.json` overrides to `StaticPairList` for reproducible backtests. The blacklist enforces `*/USDC` only, and explicitly excludes XRP, AVAX, LTC, DOGE, ETH, ADA (consistent losing pairs; the reversal strategy works best on high-volatility meme coins, not large-caps).

## Key Files

| File | Purpose |
|------|---------|
| `config.base.json` | Bot configuration (exchange, pairs, stake — no credentials) — committed |
| `config.secrets.json` | API keys, Telegram token, API server credentials — gitignored |
| `config.secrets.json.example` | Template for config.secrets.json — committed |
| `user_data/strategies/CombinedBinHAndCluc.py` | Active strategy (`MyStrategy`) — reversal 15m, 8 condiciones A-J |
| `user_data/strategies/FreqAIEnhanced15m.py` | Estrategia FreqAI (condición K) — clasificador LightGBM, standalone para comparativa |
| `config.backtest.json` | Backtest override (StaticPairList, 8 pairs: BTC/SOL/LINK/PEPE/SHIB/BONK/WIF/TURBO) |
| `config.freqai.json` | FreqAI overlay: LightGBMClassifier, train_period=90d, label=48 candles (12h), v3 |
| `config.backtest.freqai.json` | FreqAI backtest override (StaticPairList, mismos 8 pares) |
| `ops/analyze_news.py` | News intelligence: batch Claude API call → ai_score por coin → `news_themes.json` |
| `ops/fetch_sentiment.py` | Pipeline diario: F&G + CoinGecko trending + Binance spikes + RSS news |
| `ops/trade.sh` | Production start script |
| `ops/train_and_deploy.sh` | Hyperopt periódico + validación OOS 2022 + atomic deploy |
| `change.Strategy.sh` | Switch strategy + restart service |
| `freqtrade.service` | Systemd unit template |
| `.github/workflows/deploy-freqtrade.yml` | CI/CD deploy pipeline |

## Hyperopt — Plan Óptimo

**Loss function**: `CalmarHyperOptLoss` (ratio profit/max drawdown) — mejor que `OnlyProfitHyperOptLoss` porque penaliza drawdowns grandes. Alternativa: `ProfitDrawDownHyperOptLoss`.

**Timerange**: siempre incluir 2022 (bear extremo) para evitar overfit a bull markets.

**Comando manual** (desde el directorio del proyecto):
```bash
conda run -n freqtrade freqtrade hyperopt \
  -c config.base.json -c config.secrets.json \
  -s MyStrategy \
  --spaces buy sell stoploss \
  --hyperopt-loss CalmarHyperOptLoss \
  --timerange 20220101-20251231 \
  -e 1500 -j -1 \
  --random-state 42 \
  --min-trades 10 \
  --early-stop 300
```

**Validación OOS obligatoria** — tras hyperopt, correr backtest en 2022 aislado:
```bash
conda run -n freqtrade freqtrade backtesting \
  -c config.base.json -c config.backtest.json -s MyStrategy \
  --timerange 20220101-20221231 --cache none
```
- WR ≥ 55% en 2022 → aceptar params
- WR < 40% → descartar (overfitting al bull market)

**Nota crítica**: `--export-params` NO existe en freqtrade. Los params se exportan automáticamente a `user_data/strategies/CombinedBinHAndCluc.json`. El script `ops/train_and_deploy.sh` copia ese fichero a `ops/params.json` tras el hyperopt.

**FreqAI backtest** (requiere datos 2023 para primer entrenamiento):
```bash
conda run -n freqtrade freqtrade backtesting \
  -c config.base.json -c config.backtest.json \
  -c config.backtest.freqai.json -c config.freqai.json \
  -s FreqAIEnhanced15m --timerange 20240101-20241231 --cache none
```

## Important Notes

- **Never pass CLI flags that override strategy parameters** when running in production — strategy reads from JSON config (`ops/config.withparams.json`).
- `config.secrets.json` contains API credentials and is gitignored. Never commit it. Copy from `config.secrets.json.example` to set up a new machine.
- `config.base.json` is the versioned base config — safe to commit, no credentials.
- When modifying `CombinedBinHAndCluc.py`, all tunable constants are at the top of the file — prefer changing those constants over touching the logic.
- The `develop` branch is the main working branch (matches CI/CD trigger and freqtrade's own convention).
- Use `conda run -n freqtrade` to run freqtrade — there is no `.venv`, the environment is in anaconda.
- `config.backtest.json` is committed and used for reproducible backtests (StaticPairList override).
