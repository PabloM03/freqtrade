"""
AltcoinPumpStrategy v3 — Detector de Pumps de Altcoins (15m)
=============================================================
Filosofía: MOMENTUM, no reversal. Entra en breakouts confirmados con
explosión de volumen + vela verde fuerte para capturar pumps de 15-50%.

v3 fixes:
  - Vela verde obligatoria: cuerpo >= 0.6×ATR, cierra en el top 65% del rango
    → elimina entradas en spikes de VENTA (el problema principal de v1/v2)
  - Sin MACD fresco (desincronizado con el spike de volumen)
  - Vol default 5.0×, breakout lookback 24 velas (6h)
  - Solo exits con 92-100% WR histórico: rejection_candle + rsi_overbought + trailing

Señales de entrada (TODAS deben cumplirse):
  1. Vol explosion: volume > 5× media 20 velas (acumulación masiva)
  2. Vela verde fuerte: cuerpo > 0.6×ATR + cierra en top 35% del rango
  3. Breakout: cierre supera el máximo de las últimas 24 velas (6h resistencia)
  4. RSI sweet spot: 50-70 (momentum real, no sobrecomprado)
  5. EMA alineada: EMA20 > EMA50 (tendencia corto plazo alcista)
  6. No crash: precio no cayó >5% en las últimas 2h

Exits:
  - Trailing stop: 6% desde pico al llegar a +15% profit
  - RSI > 80: sobrecompra (100% WR histórico)
  - Rejection candle: mecha superior + RSI alto (92% WR histórico)
  - Hard stop: -8%
  - Timeout: >8h y profit < -3% → pump no arrancó, cortar pérdida

Pares recomendados: BONK, WIF, PEPE, TURBO, FLOKI, DOGE, SHIB, SOL, LINK
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import talib.abstract as ta
from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter
from freqtrade.persistence import Trade
from pandas import DataFrame
from typing import Optional


ROOT     = Path(__file__).parent.parent
DATA_DIR = ROOT / "data" / "sentiment"

COINGECKO_IDS = {
    "bitcoin": "BTC", "solana": "SOL", "chainlink": "LINK",
    "pepe": "PEPE", "shiba-inu": "SHIB", "bonk": "BONK",
    "dogwifcoin": "WIF", "turbo": "TURBO", "floki": "FLOKI", "dogecoin": "DOGE",
}


class AltcoinPumpStrategy(IStrategy):
    """
    Captura pumps detectando: volumen masivo + vela verde fuerte + breakout.
    Exits solo con WR histórico 92-100%: rejection_candle, rsi_overbought, trailing.
    """

    INTERFACE_VERSION = 3
    timeframe         = "15m"
    startup_candle_count = 200

    stoploss = -0.08

    trailing_stop                    = True
    trailing_stop_positive           = 0.06
    trailing_stop_positive_offset    = 0.15
    trailing_only_offset_is_reached  = True

    minimal_roi = {"0": 10.0}

    use_exit_signal            = True
    exit_profit_only           = False
    ignore_roi_if_entry_signal = True

    # ── Parámetros de entrada ──────────────────────────────────────────────────
    buy_vol_mult         = DecimalParameter(3.5, 9.0, default=5.0, decimals=1, space="buy", optimize=True)
    buy_vol_ma_period    = IntParameter(10, 30, default=20, space="buy", optimize=True)
    buy_rsi_min          = IntParameter(45, 62, default=50, space="buy", optimize=True)
    buy_rsi_max          = IntParameter(60, 78, default=70, space="buy", optimize=True)
    buy_breakout_bars    = IntParameter(12, 48, default=24, space="buy", optimize=True)
    # Vela verde: cuerpo mínimo en múltiplos del ATR
    buy_candle_body_atr  = DecimalParameter(0.3, 1.5, default=0.6, decimals=1, space="buy", optimize=True)
    # Vela verde: qué tan cerca del máximo debe cerrar (0.65 = top 35% del rango)
    buy_close_rank       = DecimalParameter(0.50, 0.85, default=0.65, decimals=2, space="buy", optimize=True)
    # Trending boost: vol mínimo si coin está en CoinGecko trending
    buy_trending_vol     = DecimalParameter(2.0, 4.5, default=3.0, decimals=1, space="buy", optimize=True)

    # ── Parámetros de salida ───────────────────────────────────────────────────
    sell_rsi_overbought   = IntParameter(72, 88, default=80, space="sell", optimize=True)
    sell_reject_wick_mult = DecimalParameter(1.0, 2.5, default=1.5, decimals=1, space="sell", optimize=True)
    sell_reject_rsi_min   = IntParameter(62, 78, default=68, space="sell", optimize=True)

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self._trending_coins: set = set()
        self._ai_scores: dict     = {}   # {coin: float} desde news_themes.json
        self._load_external_signals()

    def _load_external_signals(self):
        """Carga señales externas: CoinGecko trending + análisis AI de noticias."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # ── CoinGecko trending ──────────────────────────────────────────────────
        tf = DATA_DIR / "trending_coins.json"
        if tf.exists():
            try:
                history = json.loads(tf.read_text())
                entry = next((e for e in reversed(history) if e.get("date") == today), None)
                if entry:
                    for coin in entry.get("coins", []):
                        self._trending_coins.add(coin.get("symbol", "").upper())
                        mapped = COINGECKO_IDS.get(coin.get("coin_id", ""))
                        if mapped:
                            self._trending_coins.add(mapped)
            except Exception:
                pass

        # ── AI news themes (ops/analyze_news.py) ───────────────────────────────
        nf = DATA_DIR / "news_themes.json"
        if nf.exists():
            try:
                history = json.loads(nf.read_text())
                entry = next((e for e in reversed(history) if e.get("date") == today), None)
                if entry:
                    for sig in entry.get("coin_signals", []):
                        self._ai_scores[sig["coin"]] = float(sig.get("ai_score", 0))
            except Exception:
                pass

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        coin = metadata["pair"].split("/")[0]

        # ── Volumen ────────────────────────────────────────────────────────────
        vol_p = self.buy_vol_ma_period.value
        # Usar media de velas PREVIAS (sin incluir la actual) para medir spike real
        dataframe["vol_ma"]    = dataframe["volume"].rolling(vol_p).mean().shift(1)
        dataframe["vol_ratio"] = dataframe["volume"] / dataframe["vol_ma"].replace(0, 1)

        # Acumulación progresiva: vol_ma de corto plazo > vol_ma largo = volumen subiendo
        dataframe["vol_ma_8"]   = dataframe["volume"].rolling(8).mean().shift(1)
        dataframe["vol_ma_32"]  = dataframe["volume"].rolling(32).mean().shift(1)
        # True si el volumen lleva horas subiendo (no solo un spike puntual)
        dataframe["vol_building"] = dataframe["vol_ma_8"] > dataframe["vol_ma_32"] * 1.2

        # ── Momentum ───────────────────────────────────────────────────────────
        dataframe["rsi"]      = ta.RSI(dataframe, timeperiod=14)
        dataframe["rsi_prev"] = dataframe["rsi"].shift(1)

        # ── Tendencia ──────────────────────────────────────────────────────────
        dataframe["ema20"]  = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema50"]  = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)

        # ── Breakout: máximo reciente (sin la vela actual) ─────────────────────
        for n in [12, 16, 24, 32, 48]:
            dataframe[f"highest_{n}"] = dataframe["high"].rolling(n).max().shift(1)

        # ── Candle analysis ────────────────────────────────────────────────────
        dataframe["atr"]        = ta.ATR(dataframe, timeperiod=14)
        dataframe["body"]       = abs(dataframe["close"] - dataframe["open"])
        dataframe["upper_wick"] = dataframe["high"] - dataframe[["close", "open"]].max(axis=1)
        candle_range            = (dataframe["high"] - dataframe["low"]).clip(lower=1e-9)

        # Vela verde fuerte: cuerpo grande + cierra cerca del máximo del rango
        dataframe["bullish_strong"] = (
            (dataframe["close"] > dataframe["open"]) &
            (dataframe["body"] >= dataframe["atr"] * self.buy_candle_body_atr.value) &
            ((dataframe["close"] - dataframe["low"]) / candle_range >= self.buy_close_rank.value)
        )

        # Vela de rechazo (para exits)
        dataframe["rejection"] = (
            (dataframe["upper_wick"] > dataframe["body"] * self.sell_reject_wick_mult.value) &
            (dataframe["rsi"] >= self.sell_reject_rsi_min.value)
        )

        # ── Anti-crash ─────────────────────────────────────────────────────────
        dataframe["drop_8"] = dataframe["close"] / dataframe["close"].shift(8) - 1

        # ── Señales externas ───────────────────────────────────────────────────
        dataframe["trending_today"] = int(coin in self._trending_coins)
        # ai_score: -1 (bearish noticias) a +1 (bullish noticias) — de analyze_news.py
        dataframe["ai_score"]       = self._ai_scores.get(coin, 0.0)
        # ai_bullish: señal AI fuerte positiva hoy (reduce umbral de volumen)
        dataframe["ai_news_bullish"] = dataframe["ai_score"] >= 0.3
        # ai_bearish: señal AI negativa → bloquear entradas (ej: hack o ban del coin)
        dataframe["ai_news_bearish"] = dataframe["ai_score"] <= -0.4

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        vol_mult = self.buy_vol_mult.value
        rsi_min  = self.buy_rsi_min.value
        rsi_max  = self.buy_rsi_max.value
        br_bars  = self.buy_breakout_bars.value

        # Columna de breakout según parámetro optimizable
        for threshold in [12, 16, 24, 32, 48]:
            if br_bars <= threshold:
                breakout_col = f"highest_{threshold}"
                break

        # ── Condiciones de entrada ─────────────────────────────────────────────
        vol_surge       = dataframe["vol_ratio"] >= vol_mult
        bullish_strong  = dataframe["bullish_strong"]
        breakout        = dataframe["close"] > dataframe[breakout_col]
        rsi_ok          = (dataframe["rsi"] >= rsi_min) & (dataframe["rsi"] <= rsi_max)
        rsi_rising      = dataframe["rsi"] > dataframe["rsi_prev"]
        ema_ok          = dataframe["ema20"] > dataframe["ema50"]
        not_crash       = dataframe["drop_8"] > -0.05
        not_overextend  = dataframe["close"] < dataframe["ema200"] * 1.60
        not_ai_bearish  = ~dataframe["ai_news_bearish"]  # bloquear si hay noticias muy negativas del coin

        # Señal principal: pump breakout + acumulación previa + sin noticias negativas
        pump_signal = (
            vol_surge &
            dataframe["vol_building"] &
            bullish_strong &
            breakout &
            rsi_ok &
            rsi_rising &
            ema_ok &
            not_crash &
            not_overextend &
            not_ai_bearish
        )

        # Trending boost: CoinGecko trending → umbral de volumen reducido
        trending_signal = (
            (dataframe["trending_today"] == 1) &
            (dataframe["vol_ratio"] >= self.buy_trending_vol.value) &
            bullish_strong &
            breakout &
            rsi_ok &
            not_crash &
            not_ai_bearish
        )

        # AI news boost: noticia temática bullish confirmada + breakout técnico
        # (ej: "IA avanza" → LINK/SOL + breakout = alta probabilidad)
        ai_signal = (
            dataframe["ai_news_bullish"] &
            (dataframe["vol_ratio"] >= self.buy_trending_vol.value) &
            bullish_strong &
            breakout &
            rsi_ok &
            not_crash &
            not_overextend
        )

        dataframe.loc[pump_signal,                                              "enter_long"] = 1
        dataframe.loc[pump_signal,                                              "enter_tag"]  = "pump_breakout"
        dataframe.loc[trending_signal & ~pump_signal,                           "enter_long"] = 1
        dataframe.loc[trending_signal & ~pump_signal,                           "enter_tag"]  = "trending_boost"
        dataframe.loc[ai_signal & ~pump_signal & ~trending_signal,              "enter_long"] = 1
        dataframe.loc[ai_signal & ~pump_signal & ~trending_signal,              "enter_tag"]  = "ai_news_boost"

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        overbought = dataframe["rsi"] >= self.sell_rsi_overbought.value
        rejection  = dataframe["rejection"]

        dataframe.loc[overbought,              "exit_long"] = 1
        dataframe.loc[overbought,              "exit_tag"]  = "rsi_overbought"
        dataframe.loc[rejection & ~overbought, "exit_long"] = 1
        dataframe.loc[rejection & ~overbought, "exit_tag"]  = "rejection_candle"

        return dataframe

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> Optional[str]:
        hours_open = (current_time - trade.open_date_utc).total_seconds() / 3600

        # Pump que no arrancó en 8h y está en pérdida → cortar
        if hours_open > 8 and current_profit < -0.03:
            return "timeout_no_pump"

        # Trade estancado >36h sin profit → liberar capital
        if hours_open > 36 and current_profit < 0.02:
            return "timeout_stagnant"

        return None
