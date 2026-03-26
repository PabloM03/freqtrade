import freqtrade.vendor.qtpylib.indicators as qtpylib
import json
import numpy as np
import os
import pandas as pd
import time
from pathlib import Path
# --------------------------------
import talib.abstract as ta
from freqtrade.strategy.interface import IStrategy
from freqtrade.strategy import stoploss_from_open, IntParameter, DecimalParameter
from pandas import DataFrame
from datetime import datetime
from typing import Optional
from freqtrade.persistence import Trade



# ==========================
# ✅ PARÁMETROS GLOBALES AJUSTABLES (v3 - MUCHÍSIMA más calidad)
# Objetivo: pocas entradas, pero con ventaja clara (value + reversal + confirmación)
# ==========================

# --- Costes y ganancias mínimas ---
FEE_RATE = 0.001
SLIPPAGE_BUFFER = 0.0007
MIN_PROFIT_NET = 7 * FEE_RATE + SLIPPAGE_BUFFER      # exige beneficio real antes de permitir salidas
PEAK_MIN_PROFIT = 0.020                               # vender en picos bien formados (15m swing)
HH_EMA_MIN_PROFIT = 0.025                             # salida HH + ruptura EMA8 (15m swing)
HARD_TP = 0.50                                        # TP 50% — deja correr a BONK/WIF/memes en bull runs

# --- Stoploss y trailing (menos margen: candles de 15m tienen menos ruido) ---
STOPLOSS_ABS = -0.02                                  # SL -2% + trailing 1% desde pico (JSON lo sobreescribe igual)
TRAIL_ATR_MULT_LOW = 2.6                               # menos sensible (no te saca por ruido)
TRAIL_ATR_MULT_HIGH = 3.6                              # deja correr tendencia fuerte
TRAIL_DIST_MIN = 0.040
TRAIL_DIST_MAX = 0.120
TRAIL_VERTICAL_MIN = 0.060
ADX_STRONG_TREND = 27                                  # tendencia fuerte de verdad
ROC5_VERTICAL = 1.5                                    # vertical-rally en 15m: 5×15m=1.25h, 1.5% es claro
FALLBACK_TRAIL_DIST = 0.028

# --- Anti-cuchillo (ajustado para 15m: candles más pequeñas) ---
PCT1_MIN = -2.0                                        # 15m: caídas de hasta -2% son normales en un candle
PCT3_MIN = -5.0                                        # 15m: -5% en 3 candles (45min) = drop muy severo
COOLDOWN_BARS = 8                                      # 2h de cooldown (8 × 15m = 2h, igual que antes)

# --- Filtro de compras altas (más estricto: no comprar arriba) ---
NO_BUY_BB_MULT = 1.003                                 # si está por encima del mid BB -> sospechoso
NO_BUY_EMA20_MULT = 1.003                              # si está por encima de EMA20 -> sospechoso
NO_BUY_RSI_MIN = 58                                     # si RSI ya alto, no compras

# --- Zonas de valor para comprar (más profundas = mejor R/R) ---
DEEP_BB = 0.18                                          # “deep value” real
BB_ZONE_OK = 0.55                                       # 1h: zona media-baja (señales más contextuales)
LOWER_WICK_BODY_RATIO = 1.22                            # vela de giro (mecha inferior clara)

# --- Reglas de compra específicas (más confirmación) ---
# A) Mínimo local
A_LL10_MULT = 1.004                                     # valle más “real”
A_RSI_PREV_MAX = 52                                     # 1h: RSI<52 antes del giro es válido

# C) StochRSI en sobreventa
C_STOCH_MAX = 25                                        # 15m: oversold selectivo (StochRSI<25 = sobreventa real en 3.5h, equivale a <40 en 1h)

# D) Capitulación (solo si es capitulación “de verdad” en 15m)
D_PCT1_MAX = -2.5
D_PCT3_MAX = -5.0
D_BB_PERCENT_MAX = 0.055                                # pegado a banda inferior
D_TAIL_ATR_MULT = 1.15                                  # mecha larga clara (rebote probable)

# E) Pullback a EMA8 (más exigente)
E_RSI_MIN = 55                                          # pullback solo con fuerza real
E_LL10_MULT = 1.008
E_BB_MID_MULT = 0.996

# F) RSI muy sobrevendido + rebote (en 1h tiene más contexto = más válido)
F_RSI_MAX = 30                                          # RSI < 30 en 1h = sobreventa significativa

# G) Hammer en zona baja con volumen (alta frecuencia)
G_BB_ZONE = 0.45                                        # en zona baja BB
G_VOL_MULT = 1.5                                        # volumen mínimo para hammer válido

# --- Ventas (más “premium”: vender en rechazo fuerte / giro real) ---
REJECT_UPPER_ATR_MULT = 1.05
REJECT_WICK_BODY_RATIO = 1.30
SELL_RSI_PEAK = 74
SELL_RSI_REJECT = 68
SELL_RSI_HH_EMA = 68
SELL_RSI_WICK = 68

# --- Crash-guard (más protector: evita quedarte atrapado) ---
CRASH_FAST_DROP_EMA8 = 0.990
CRASH_FAST_DROP_PCT1 = -1.5
CRASH_ATR_BREAK_MULT = 1.55
CRASH_ADX_MIN = 26
CRASH_RSI_MAX = 50

# --- Timeframe y arranque ---
TIMEFRAME = '15m'
TF_MULT = 4                                            # multiplicador vs 1h: todos los períodos de indicadores ×4
STARTUP_CANDLES = 500                                  # 500 velas: EMA200_ht(200) + MACD_slow(104) + shift(192) warmup

# --- Bollinger config (ventanas escaladas ×4 para equivalencia temporal con 1h) ---
# BB20@1h = 20h; BB80@15m = 80×15m = 20h (misma suavidad temporal)
# BB45@1h = 45h; BB180@15m = 180×15m = 45h (misma suavidad temporal)
BB40_WINDOW = 180
BB40_STDS = 2.25
BB20_WINDOW = 80
BB20_STDS = 2.25

# --- Anti-chase (ajustado para 15m: candles más volátiles que 1h) ---
MAX_PCT_UP_1 = 2.0                                     # 15m: hasta 2% en un candle es normal en altcoins
MAX_PCT_UP_3 = 5.0                                     # 15m: no comprar si +5% en 45min (3 candles)
MAX_GREEN_STREAK = 3                                    # no más de 3 velas verdes seguidas
BUY_BELOW_EMA20_MULT = 0.998                            # exige estar por debajo de EMA20
BUY_BELOW_BB_MID_MULT = 0.998                           # exige estar por debajo de BB mid
BB_EXPANDING_HIGH = 0.42                                # si expansión arriba, no compras
PUMP_VOL_MULT = 1.9                                     # bloquea pumps "temprano"
NEAR_HH_DISTANCE = 0.028                                # no comprar cerca del máximo reciente (20 barras)
REQUIRE_RED_PULLBACK = False                            # no exigir vela roja previa (demasiado restrictivo)


def bollinger_bands(stock_price, window_size, num_of_std):
    rolling_mean = stock_price.rolling(window=window_size).mean()
    rolling_std = stock_price.rolling(window=window_size).std()
    lower_band = rolling_mean - (rolling_std * num_of_std)
    return np.nan_to_num(rolling_mean), np.nan_to_num(lower_band)


class MyStrategy(IStrategy):
    """
    - Compras: en bajadas óptimas (mínimo local claro + capitulación/giro), no en mitad de subida.
    - Ventas: en picos óptimos (máximo local claro + rechazo/giro).
    - Crash-guard y trailing moderado.
    """

    # Mapea parámetros globales a atributos de clase para mantener self.*
    FEE_RATE = FEE_RATE
    SLIPPAGE_BUFFER = SLIPPAGE_BUFFER
    MIN_PROFIT_NET = MIN_PROFIT_NET
    PEAK_MIN_PROFIT = PEAK_MIN_PROFIT
    HH_EMA_MIN_PROFIT = HH_EMA_MIN_PROFIT
    HARD_TP = HARD_TP

    stoploss = STOPLOSS_ABS
    timeframe = TIMEFRAME
    startup_candle_count = STARTUP_CANDLES

    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = True
    trailing_stop = True
    trailing_stop_positive = 0.010          # trail 1% desde el pico
    trailing_stop_positive_offset = 0.025   # se activa cuando profit >= 2.5%
    trailing_only_offset_is_reached = True
    use_custom_stoploss = False
    minimal_roi = {"0": 10.0}
    MIN_HOLD_BARS = 3

    # Anti-cuchillo / filtros
    PCT1_MIN = PCT1_MIN
    PCT3_MIN = PCT3_MIN
    COOLDOWN_BARS = COOLDOWN_BARS

    NO_BUY_BB_MULT = NO_BUY_BB_MULT
    NO_BUY_EMA20_MULT = NO_BUY_EMA20_MULT
    NO_BUY_RSI_MIN = NO_BUY_RSI_MIN

    DEEP_BB = DEEP_BB
    BB_ZONE_OK = BB_ZONE_OK
    LOWER_WICK_BODY_RATIO = LOWER_WICK_BODY_RATIO

    # Reglas compra
    A_LL10_MULT = A_LL10_MULT
    A_RSI_PREV_MAX = A_RSI_PREV_MAX
    C_STOCH_MAX = C_STOCH_MAX
    D_PCT1_MAX = D_PCT1_MAX
    D_PCT3_MAX = D_PCT3_MAX
    D_BB_PERCENT_MAX = D_BB_PERCENT_MAX
    D_TAIL_ATR_MULT = D_TAIL_ATR_MULT
    E_RSI_MIN = E_RSI_MIN
    E_LL10_MULT = E_LL10_MULT
    E_BB_MID_MULT = E_BB_MID_MULT
    F_RSI_MAX = F_RSI_MAX
    G_BB_ZONE = G_BB_ZONE
    G_VOL_MULT = G_VOL_MULT

    # Ventas
    REJECT_UPPER_ATR_MULT = REJECT_UPPER_ATR_MULT
    REJECT_WICK_BODY_RATIO = REJECT_WICK_BODY_RATIO
    SELL_RSI_PEAK = SELL_RSI_PEAK
    SELL_RSI_REJECT = SELL_RSI_REJECT
    SELL_RSI_HH_EMA = SELL_RSI_HH_EMA
    SELL_RSI_WICK = SELL_RSI_WICK

    # Crash
    CRASH_FAST_DROP_EMA8 = CRASH_FAST_DROP_EMA8
    CRASH_FAST_DROP_PCT1 = CRASH_FAST_DROP_PCT1
    CRASH_ATR_BREAK_MULT = CRASH_ATR_BREAK_MULT
    CRASH_ADX_MIN = CRASH_ADX_MIN
    CRASH_RSI_MAX = CRASH_RSI_MAX

    # Trailing
    TRAIL_ATR_MULT_LOW = TRAIL_ATR_MULT_LOW
    TRAIL_ATR_MULT_HIGH = TRAIL_ATR_MULT_HIGH
    TRAIL_DIST_MIN = TRAIL_DIST_MIN
    TRAIL_DIST_MAX = TRAIL_DIST_MAX
    TRAIL_VERTICAL_MIN = TRAIL_VERTICAL_MIN
    ADX_STRONG_TREND = ADX_STRONG_TREND
    ROC5_VERTICAL = ROC5_VERTICAL
    FALLBACK_TRAIL_DIST = FALLBACK_TRAIL_DIST

    # BB config
    BB40_WINDOW = BB40_WINDOW
    BB40_STDS = BB40_STDS
    BB20_WINDOW = BB20_WINDOW
    BB20_STDS = BB20_STDS

    # ---------------------- HYPEROPT PARAMETERS ----------------------
    # Espacio de búsqueda para optimización automática de parámetros
    # Umbrales de señal de entrada
    buy_c_stoch_max      = IntParameter(12, 40, default=25,    space='buy', optimize=True)
    buy_bb_zone_ok       = DecimalParameter(0.38, 0.85, default=0.55, decimals=2, space='buy', optimize=True)
    buy_a_rsi_prev_max   = IntParameter(38, 65, default=52,    space='buy', optimize=True)
    buy_f_rsi_max        = IntParameter(20, 38, default=30,    space='buy', optimize=True)
    # Filtro de tendencia triple (ema50_ok) — rangos ampliados para cubrir recuperación
    buy_ema50_close_pct  = DecimalParameter(0.860, 0.998, default=0.978, decimals=3, space='buy', optimize=True)
    buy_ema50_slope_48h  = DecimalParameter(0.940, 0.998, default=0.985, decimals=3, space='buy', optimize=True)
    buy_ema20_slope_24h  = DecimalParameter(0.945, 0.998, default=0.990, decimals=3, space='buy', optimize=True)
    # G) Hammer en zona baja
    buy_g_bb_zone        = DecimalParameter(0.18, 0.42, default=0.30, decimals=2, space='buy', optimize=True)
    buy_g_vol_mult       = DecimalParameter(1.4, 2.8, default=1.8, decimals=1, space='buy', optimize=True)
    # Sentimiento — Fear & Greed Index (contrarian: añadir entradas en pánico extremo)
    # H) Panic Entry: F&G < buy_fg_fear → mercado en pánico máximo = mejor momento reversal
    buy_fg_fear          = IntParameter(15, 40, default=30, space='buy', optimize=True)
    # I) RSI crash ultra-extremo: bypass anti_chase cuando RSI < buy_i_rsi_crash
    buy_i_rsi_crash      = IntParameter(14, 22, default=18, space='buy', optimize=True)
    # Salidas
    sell_peak_min_profit = DecimalParameter(0.008, 0.045, default=0.020, decimals=3, space='sell', optimize=True)
    sell_hh_ema_min      = DecimalParameter(0.008, 0.055, default=0.025, decimals=3, space='sell', optimize=True)

    # ---------------------- INDICADORES ----------------------
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        m = TF_MULT  # multiplicador de períodos para equivalencia temporal vs 1h

        # BinHV45 (BB40) — ya escalado via BB40_WINDOW=180 (45h equiv)
        mid, lower = bollinger_bands(
            dataframe['close'], window_size=self.BB40_WINDOW, num_of_std=self.BB40_STDS
        )
        dataframe['lower'] = lower
        dataframe['bbdelta'] = (mid - dataframe['lower']).abs()
        dataframe['closedelta'] = (dataframe['close'] - dataframe['close'].shift()).abs()
        dataframe['tail'] = (dataframe['close'] - dataframe['low']).abs()

        # Bollinger 20 — ya escalado via BB20_WINDOW=80 (20h equiv)
        tp = qtpylib.typical_price(dataframe)
        bb = qtpylib.bollinger_bands(tp, window=self.BB20_WINDOW, stds=self.BB20_STDS)
        dataframe['bb_lowerband']  = bb['lower']
        dataframe['bb_middleband'] = bb['mid']
        dataframe['bb_upperband']  = bb['upper']
        dataframe['bb_width'] = (dataframe['bb_upperband'] - dataframe['bb_lowerband']) / dataframe['bb_middleband']
        denom = (dataframe['bb_upperband'] - dataframe['bb_lowerband']).replace(0, np.nan)
        dataframe['bb_percent'] = (dataframe['close'] - dataframe['bb_lowerband']) / denom
        dataframe['bb_expanding'] = (dataframe['bb_width'] > dataframe['bb_width'].shift(1))

        # EMAs / fuerza — períodos ×m para equivalencia temporal
        dataframe['ema8']     = ta.EMA(dataframe, timeperiod=8 * m)    # 32 períodos = 8h equiv
        dataframe['ema_fast'] = ta.EMA(dataframe, timeperiod=20 * m)   # 80 períodos = 20h equiv
        dataframe['ema_slow'] = ta.EMA(dataframe, timeperiod=50 * m)   # 200 períodos = 50h equiv
        # ema50_ht y ema20_ht coinciden con ema_slow y ema_fast ya escalados
        dataframe['ema50_ht'] = dataframe['ema_slow']
        dataframe['ema20_ht'] = dataframe['ema_fast']
        dataframe['volume_mean_slow'] = dataframe['volume'].rolling(window=30 * m).mean()  # 120 períodos = 30h
        dataframe['ema8_slope_up'] = dataframe['ema8'] > dataframe['ema8'].shift(1)

        # RSI — período original (14) para mayor reactividad a 15m: detecta giros en 3.5h como RSI14@1h en 14h
        # ADX/DI — escalado ×m: mide fuerza de tendencia sobre ventana temporal equivalente (14h)
        dataframe['rsi']      = ta.RSI(dataframe, timeperiod=14)
        dataframe['rsi_prev'] = dataframe['rsi'].shift(1)
        dataframe['rsi_rising_2bars'] = (
            (dataframe['rsi'] > dataframe['rsi_prev']) &
            (dataframe['rsi_prev'] > dataframe['rsi'].shift(2))
        )
        dataframe['adx']      = ta.ADX(dataframe, timeperiod=14 * m)
        dataframe['plus_di']  = ta.PLUS_DI(dataframe, timeperiod=14 * m)
        dataframe['minus_di'] = ta.MINUS_DI(dataframe, timeperiod=14 * m)

        # StochRSI — período original para mayor reactividad: cruces de sobreventa más frecuentes
        stoch = ta.STOCHRSI(dataframe, timeperiod=14, fastk_period=3, fastd_period=3)
        dataframe['stoch_k'] = stoch['fastk']
        dataframe['stoch_d'] = stoch['fastd']
        dataframe['stoch_k_prev'] = dataframe['stoch_k'].shift(1)
        dataframe['stoch_d_prev'] = dataframe['stoch_d'].shift(1)

        # MACD — período original (12/26/9) para reactividad: capta giros de momentum en 3-6h
        macd = ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)
        dataframe['macd']      = macd['macd']
        dataframe['macdsignal']= macd['macdsignal']
        dataframe['macdhist']  = macd['macdhist']

        # Momentum/extremos — ventanas ×m
        dataframe['roc5'] = ta.ROC(dataframe, timeperiod=5 * m)         # ROC20 = 5h equiv
        dataframe['ll_8']  = dataframe['low'].rolling(8 * m).min()      # 32 períodos = 8h
        dataframe['ll_10'] = dataframe['low'].rolling(10 * m).min()     # 40 períodos = 10h
        dataframe['ll_20'] = dataframe['low'].rolling(20 * m).min()     # 80 períodos = 20h
        dataframe['hh_20'] = dataframe['high'].rolling(20 * m).max()    # 80 períodos = 20h

        # ATR y variaciones — período ×m
        dataframe['atr']  = ta.ATR(dataframe, timeperiod=14 * m)        # 56 períodos = 14h equiv
        dataframe['pct_1']= dataframe['close'].pct_change(1) * 100.0   # 1 candle (15min)
        dataframe['pct_3']= dataframe['close'].pct_change(3) * 100.0   # 3 candles (45min)

        # Estructura / cooldown — COOLDOWN_BARS ya está en unidades de candles
        body = (dataframe['close'] - dataframe['open']).abs()
        dataframe['big_red']  = (dataframe['close'] < dataframe['open']) & (body > 1.2 * dataframe['atr'])
        dataframe['cooldown'] = dataframe['big_red'].rolling(self.COOLDOWN_BARS).max()

        # Mechas
        dataframe['upper_wick'] = (dataframe['high'] - np.maximum(dataframe['open'], dataframe['close'])).abs()
        dataframe['lower_wick'] = (np.minimum(dataframe['open'], dataframe['close']) - dataframe['low']).abs()

        # Volumen relativo
        dataframe['vol_spike'] = dataframe['volume'] > (dataframe['volume_mean_slow'] * 1.15)

        # Máximo/mínimo local reciente — ventanas ×m para equivalencia temporal
        dataframe['loc_peak'] = (
            (dataframe['high'] >= dataframe['high'].rolling(6 * m).max()) &
            (dataframe['high'] >= dataframe['high'].shift(1)) &
            (dataframe['high'] >= dataframe['high'].shift(2))
        )
        dataframe['loc_trough'] = (
            (dataframe['low'] <= dataframe['low'].rolling(6 * m).min()) &
            (dataframe['low'] <= dataframe['low'].shift(1)) &
            (dataframe['low'] <= dataframe['low'].shift(2))
        )

        # Anti-chase helpers
        dataframe['green'] = dataframe['close'] > dataframe['open']
        # green_streak: NO se escala × m. La ventana son los últimos 3 candles (misma lógica que a 1h)
        dataframe['green_streak'] = (
            dataframe['green']
            .rolling(window=MAX_GREEN_STREAK, min_periods=1)
            .sum()
        )
        dataframe['vol_mean_fast'] = dataframe['volume'].rolling(window=10 * m).mean()  # 40 períodos = 10h
        dataframe['pump_vol'] = dataframe['volume'] > (dataframe['vol_mean_fast'] * PUMP_VOL_MULT)
        dataframe['near_hh'] = dataframe['close'] >= (dataframe['hh_20'] * (1.0 - NEAR_HH_DISTANCE))

        # --- Fear & Greed Index (sentimiento macro diario, contrarian) ---
        # Datos descargados en user_data/data/sentiment/fear_greed.csv
        # Fuente: alternative.me/fng — actualizado cada 24h
        # Valor 0-100: 0=Extreme Fear (máximo contrarian buy), 100=Extreme Greed (no comprar)
        if not hasattr(self, '_fg_lookup'):
            fg_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                '..', 'data', 'sentiment', 'fear_greed.csv'
            )
            if os.path.exists(fg_path):
                fg_df = pd.read_csv(fg_path)
                fg_series = pd.to_datetime(fg_df['date']).dt.date
                self._fg_lookup = dict(zip(fg_series, fg_df['fear_greed'].astype(int)))
                self._fg_last = int(fg_df['fear_greed'].iloc[0])  # último valor conocido
            else:
                self._fg_lookup = {}
                self._fg_last = 50  # neutro si no hay datos

        # Asignar valor diario a cada vela 15m (forward-fill con último valor si falta)
        candle_dates = dataframe['date'].dt.tz_convert(None).dt.date
        dataframe['fear_greed'] = candle_dates.map(self._fg_lookup).fillna(self._fg_last).astype(int)

        # --- AI News Score (análisis temático de noticias con Claude) ---
        # Fuente: ops/analyze_news.py → user_data/data/sentiment/news_themes.json
        # ai_score: -1 (noticias muy negativas del coin) a +1 (noticias muy positivas)
        # Ejemplos: "avance de IA" → LINK/SOL sube | "hack de protocolo" → bearish
        # Solo disponible en live trading — en backtest = 0 (no afecta resultados históricos)
        if not hasattr(self, '_ai_scores'):
            self._ai_scores = {}
            news_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                '..', 'data', 'sentiment', 'news_themes.json'
            )
            if os.path.exists(news_path):
                try:
                    from datetime import date as date_type
                    today_str = str(date_type.today())
                    history = json.loads(open(news_path).read())
                    entry = next((e for e in reversed(history) if e.get('date') == today_str), None)
                    if entry:
                        for sig in entry.get('coin_signals', []):
                            self._ai_scores[sig['coin']] = float(sig.get('ai_score', 0))
                except Exception:
                    pass

        coin = metadata['pair'].split('/')[0]
        dataframe['ai_score'] = self._ai_scores.get(coin, 0.0)

        return dataframe

    # ---------------------- ENTRADAS (alta frecuencia, filtros relajados) ----------------------
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Anti-cuchillo: no comprar si caída en curso, bearish direccional, o volumen cero
        anti_cuchillo = (
            (dataframe['pct_1'] > self.PCT1_MIN) &
            (dataframe['pct_3'] > self.PCT3_MIN) &
            (~dataframe['cooldown'].astype(bool)) &
            (~((dataframe['bb_percent'] < 0) & dataframe['bb_expanding'])) &
            (dataframe['minus_di'] <= dataframe['plus_di']) &
            (dataframe['volume'] > 0)
        )

        # Evitar compras “arriba” (requiere las 3 a la vez — muy permisivo)
        no_buy_high = (
            (dataframe['close'] > dataframe['bb_middleband'] * self.NO_BUY_BB_MULT) &
            (dataframe['close'] > dataframe['ema_fast'] * self.NO_BUY_EMA20_MULT) &
            (dataframe['rsi'] > self.NO_BUY_RSI_MIN)        # RSI > 68
        )

        # Zonas de valor — usa parámetro hyperopt si está disponible
        bb_zone_ok = (dataframe['bb_percent'] <= self.buy_bb_zone_ok.value)

        lower_wick = dataframe['lower_wick']
        body       = (dataframe['close'] - dataframe['open']).abs()
        hammerish  = lower_wick > self.LOWER_WICK_BODY_RATIO * body

        # Anti-chase: NO perseguir pumps ni comprar arriba
        anti_chase = (
            (dataframe['pct_1'] < MAX_PCT_UP_1) &
            (dataframe['pct_3'] < MAX_PCT_UP_3) &
            (dataframe['green_streak'] < MAX_GREEN_STREAK) &
            (~((dataframe['bb_percent'] >= BB_EXPANDING_HIGH) & (dataframe['bb_expanding']))) &
            (~(dataframe['pump_vol'] & (dataframe['pct_1'] > 0.6))) &
            (dataframe['close'] <= dataframe['ema_fast'] * BUY_BELOW_EMA20_MULT) &
            (dataframe['close'] <= dataframe['bb_middleband'] * BUY_BELOW_BB_MID_MULT) &
            (~dataframe['near_hh'])
        )

        base_filter = anti_cuchillo & ~no_buy_high & anti_chase

        # A) Mínimo local + giro RSI + volumen + MACD (zona baja BB, 1h más contexto)
        bb_low_zone = (dataframe['bb_percent'] <= 0.38)
        bb_deep_zone = (dataframe['bb_percent'] <= 0.20)  # zona muy oversold para A
        A = (
            (dataframe['loc_trough']) &
            (dataframe['low'] <= dataframe['ll_10'] * self.A_LL10_MULT) &
            bb_deep_zone &
            (dataframe['rsi_prev'] < self.buy_a_rsi_prev_max.value) &
            (dataframe['rsi'] > dataframe['rsi_prev']) &
            (dataframe['close'] >= dataframe['open']) &
            dataframe['vol_spike'] &
            (dataframe['macdhist'] >= dataframe['macdhist'].shift(1)) &  # MACD girando
            (dataframe['macdhist'] > 0)                                  # MACD positivo (momentum alcista real)
        )

        # B) Re-entrada tras cerrar fuera de banda inferior y volver dentro
        # Refuerzo vs 1h: requerir 2+ candles consecutivos bajo BB80 antes del cruce
        # (a 1h, 1 candle bajo BB = 1h entero; a 15m, 1 candle = 15min, no es suficiente)
        B = (
            (dataframe['close'].shift(2) < dataframe['bb_lowerband'].shift(2)) &  # 2+ candles bajo BB80
            (dataframe['close'].shift(1) < dataframe['bb_lowerband'].shift(1)) &
            (dataframe['close'] > dataframe['bb_lowerband']) &
            (dataframe['rsi'] > dataframe['rsi_prev']) &
            (dataframe['macdhist'] >= dataframe['macdhist'].shift(1)) &  # MACD no empeora
            (bb_zone_ok)
        )

        # C) StochRSI cruce en sobreventa + RSI confirmando 2 barras + MACD + EMA20 no bajando
        # rsi_rising_2bars: RSI subiendo 2 velas consecutivas antes de entrar → precio ya recuperando
        # Reduce false entries con SL -2%: si el precio sigue cayendo tras el cruce, RSI también cae → no dispara
        C = (
            (dataframe['stoch_k_prev'] < dataframe['stoch_d_prev']) &
            (dataframe['stoch_k'] > dataframe['stoch_d']) &
            (dataframe['stoch_k'] < self.buy_c_stoch_max.value) &
            (dataframe['stoch_d'] < self.buy_c_stoch_max.value) &
            dataframe['rsi_rising_2bars'] &                              # confirmación: RSI subiendo 2 barras
            (dataframe['macdhist'] >= dataframe['macdhist'].shift(1)) &  # MACD no empeora
            (dataframe['ema_fast'] >= dataframe['ema_fast'].shift(16)) & # EMA20 plana (16×15m = 4h equivalente)
            (bb_zone_ok)
        )

        # D) Capitulación: caída fuerte + cola larga + rebote verde
        D = (
            ((dataframe['pct_1'] <= self.D_PCT1_MAX) | (dataframe['pct_3'] <= self.D_PCT3_MAX)) &
            (dataframe['bb_percent'] <= self.D_BB_PERCENT_MAX) &
            (dataframe['tail'] >= dataframe['atr'] * self.D_TAIL_ATR_MULT) &
            (dataframe['close'] >= dataframe['open'])
        )

        # E) Pullback controlado a EMA8 ascendente en zona media-baja
        E = (
            (dataframe['close'] > dataframe['ema8']) &
            (dataframe['close'].shift(1) <= dataframe['ema8'].shift(1)) &
            (dataframe['ema8_slope_up']) &
            (dataframe['rsi'] >= self.E_RSI_MIN) & (dataframe['rsi'] > dataframe['rsi_prev']) &
            ((dataframe['low'] <= dataframe['ll_10'] * self.E_LL10_MULT) |
             (dataframe['close'] <= dataframe['bb_middleband'] * self.E_BB_MID_MULT) |
             bb_zone_ok) &
            (dataframe['vol_spike'] | hammerish)
        )

        # F) RSI extremo (<25) + rebote + MACD girando (señal de capitulación selectiva)
        # Gate de noticias: no entrar en F si noticias del día son claramente negativas para esta coin
        # (en backtest ai_score=0 siempre → gate siempre True → sin efecto histórico)
        news_not_bearish = (dataframe['ai_score'] > -0.25)
        F = (
            (dataframe['rsi'] < self.buy_f_rsi_max.value) &
            (dataframe['rsi'] > dataframe['rsi_prev']) &        # RSI subiendo
            (dataframe['macdhist'] >= dataframe['macdhist'].shift(1)) &  # MACD no empeora
            dataframe['vol_spike'] &                            # volumen confirmado
            (bb_zone_ok) &
            news_not_bearish                                    # noticias no bajistas
        )

        # G) Hammer en zona baja con fuerte confirmación (selectivo — solo hammers de calidad)
        G = (
            hammerish &                                          # mecha inferior > 1.22× cuerpo
            (dataframe['bb_percent'] <= self.buy_g_bb_zone.value) &  # zona baja BB
            (dataframe['volume'] > dataframe['vol_mean_fast'] * self.buy_g_vol_mult.value) &
            (dataframe['rsi'] > dataframe['rsi_prev']) &        # RSI girando
            (dataframe['macdhist'] >= dataframe['macdhist'].shift(1)) &  # MACD no empeora
            (dataframe['close'] >= dataframe['open']) &          # vela verde
            (dataframe['adx'] < 30) &                           # no en tendencia fuerte bajista
            (dataframe['minus_di'] <= dataframe['plus_di'])      # direccional alcista
        )

        # Filtro de tendencia triple (usa EMAs de alta temporalidad para consistencia con 1h):
        # ema50_ht (EMA200@15m = 50h) no bajando >1.4% en 48h (192×15m)
        # ema20_ht (EMA80@15m = 20h) no bajando >5.2% en 24h (96×15m)
        # Precio no más del 1.1% por debajo de EMA200@15m
        ema50_ok = (
            (dataframe['ema50_ht'] >= dataframe['ema50_ht'].shift(192) * self.buy_ema50_slope_48h.value) &
            (dataframe['ema20_ht'] >= dataframe['ema20_ht'].shift(96)  * self.buy_ema20_slope_24h.value) &
            (dataframe['close']    >= dataframe['ema50_ht']            * self.buy_ema50_close_pct.value) &
            (dataframe['close']    >= dataframe['close'].shift(192)    * 0.80)  # no caída >20% en 48h (bloquea CETUS-type)
        )

        # H) Panic Entry — Fear & Greed en Extreme Fear (contrarian máximo)
        # Lógica inversa: cuando el mercado está en pánico (F&G bajo), relajar requisitos de entrada
        # No bloqueamos entradas en greed (ema50_ok ya gestiona el macro trend)
        # Requiere mínimo local real (loc_trough) para evitar cuchillo cayendo en bear sostenido
        H = (
            (dataframe['fear_greed'] < self.buy_fg_fear.value) &  # mercado en pánico extremo
            dataframe['loc_trough'] &                              # mínimo local real (no caída libre)
            (dataframe['rsi'] < 42) &                              # moderadamente sobrevendido
            dataframe['rsi_rising_2bars'] &                        # RSI girando al alza 2 barras consecutivas
            (dataframe['macdhist'] >= dataframe['macdhist'].shift(1)) &  # MACD no empeora
            dataframe['vol_spike'] &                               # volumen confirmando
            (bb_zone_ok)                                           # zona baja BB
        )

        # I) RSI Ultra-Extremo — bypass de anti_chase cuando crash es de capitulación real
        # Cuando RSI < 20 el activo ha caído tanto que la regla "close < EMA20" es redundante
        # Protección extra: loc_trough + MACD + vol para evitar cuchillo
        # No requiere anti_chase (el RSI < 20 implica caída severa ya ocurrida)
        I_rsi_crash = (
            (dataframe['rsi'] < self.buy_i_rsi_crash.value) &     # RSI ultra-extremo
            dataframe['loc_trough'] &                              # mínimo local (rebote probable)
            (dataframe['rsi'] > dataframe['rsi_prev']) &           # RSI girando al alza
            (dataframe['macdhist'] >= dataframe['macdhist'].shift(1)) &  # MACD no empeora
            dataframe['vol_spike'] &                               # volumen confirmando
            (dataframe['bb_percent'] <= 0.35) &                    # zona baja BB (precio deprimido)
            (~dataframe['cooldown'].astype(bool))                  # no en cooldown
        )

        # Estabilización de precio: el mínimo de las últimas 4 velas (1h) NO es inferior
        # al mínimo de las 4 velas anteriores → la caída ha parado, precio consolidando
        # Previene entrar en caídas verticales tipo CETUS pump-then-dump
        # El usuario lo describe bien: "esperar al menos un camino horizontal tendiendo a subir"
        price_stabilized = (
            dataframe['low'].rolling(4).min() >= dataframe['low'].rolling(4).min().shift(4)
        )

        # D necesita filtro propio (capitulación = caída fuerte, conflicto con PCT1_MIN)
        anti_cuchillo_D = (
            (~dataframe['cooldown'].astype(bool)) &
            (dataframe['volume'] > 0)
        )
        base_filter_D = anti_cuchillo_D & ~no_buy_high & ema50_ok & price_stabilized

        # base_filter con tendencia para A, B, C, F, G
        base_filter_trend = base_filter & ema50_ok

        # base_filter especial para E — permite entradas SOBRE EMA20 en tendencia alcista confirmada.
        # Problema: en uptrend, EMA8 > EMA20; el precio rebota en EMA8 POR ENCIMA de EMA20.
        # El anti_chase estándar exige close <= EMA20*0.998, bloqueando estos pullbacks legítimos.
        # Solución: reemplazar los filtros EMA20/BB_mid/near_hh por confirmación de tendencia alcista.
        uptrend_confirmed = (
            dataframe['ema8_slope_up'] &                          # EMA8 ascendente
            (dataframe['adx'] > 20) &                             # tendencia confirmada (ADX > 20)
            (dataframe['plus_di'] > dataframe['minus_di'])        # dirección alcista
        )
        anti_chase_uptrend = (
            (dataframe['pct_1'] < MAX_PCT_UP_1) &
            (dataframe['pct_3'] < MAX_PCT_UP_3) &
            (dataframe['green_streak'] < MAX_GREEN_STREAK) &
            (~(dataframe['pump_vol'] & (dataframe['pct_1'] > 0.6))) &
            (~((dataframe['bb_percent'] >= BB_EXPANDING_HIGH) & dataframe['bb_expanding']))
            # Sin near_hh, sin EMA20, sin BB_mid — en uptrend el rebote en EMA8 es válido sobre EMA20
        )
        base_filter_E = anti_cuchillo & ~no_buy_high & anti_chase_uptrend & uptrend_confirmed & ema50_ok

        # Calcular máscaras una sola vez para evitar el bug de re-evaluación
        mask_A = A & base_filter_trend
        mask_B = B & base_filter_trend & ~mask_A
        mask_C = C & base_filter_trend & ~mask_A & ~mask_B
        mask_D = D & base_filter_D & ~mask_A & ~mask_B & ~mask_C
        mask_E = E & base_filter_E & ~mask_A & ~mask_B & ~mask_C & ~mask_D
        mask_F = F & base_filter_trend & ~mask_A & ~mask_B & ~mask_C & ~mask_D & ~mask_E
        mask_G = G & base_filter_trend & ~mask_A & ~mask_B & ~mask_C & ~mask_D & ~mask_E & ~mask_F
        # H: Panic Entry — solo en Extreme Fear (F&G < buy_fg_fear), no se solapa con A-G
        mask_H = H & base_filter_trend & ~mask_A & ~mask_B & ~mask_C & ~mask_D & ~mask_E & ~mask_F & ~mask_G
        # I: RSI crash ultra-extremo — usa base_filter_D (sin anti_chase, como capitulación D)
        # Pero SÍ requiere ema50_ok (estructura macro sana) y price_stabilized (no caída libre)
        base_filter_I = anti_cuchillo_D & ema50_ok & price_stabilized
        mask_I = I_rsi_crash & base_filter_I & ~mask_A & ~mask_B & ~mask_C & ~mask_D & ~mask_E & ~mask_F & ~mask_G & ~mask_H

        # J) AI News Entry — solo disponible en live trading cuando ops/analyze_news.py corre
        # Concepto: noticia temática bullish fuerte (ai_score > 0.3) + coin técnicamente sobrevendida
        # Ejemplos: "avance de IA" → LINK/SOL | "meme season viral" → BONK/WIF/PEPE
        # En backtest: ai_score = 0 siempre → mask_J = False → no afecta resultados históricos
        J_ai_news = (
            (dataframe['ai_score'] >= 0.30) &        # señal AI positiva fuerte para este coin hoy
            dataframe['loc_trough'] &                 # mínimo local (no comprar en caída libre)
            (dataframe['rsi'] < 50) &                 # coin sobrevendida o neutral-baja
            (dataframe['rsi'] > dataframe['rsi_prev']) &  # RSI girando al alza
            (dataframe['macdhist'] >= dataframe['macdhist'].shift(1)) &  # MACD no empeora
            dataframe['vol_spike'] &                  # volumen confirmando el giro
            (bb_zone_ok)                              # zona baja BB
        )
        mask_J = J_ai_news & base_filter_trend & ~mask_A & ~mask_B & ~mask_C & ~mask_D & ~mask_E & ~mask_F & ~mask_G & ~mask_H & ~mask_I

        dataframe.loc[mask_A, 'enter_long'] = 1
        dataframe.loc[mask_A, 'enter_tag'] = 'A_local_min'

        dataframe.loc[mask_B, 'enter_long'] = 1
        dataframe.loc[mask_B, 'enter_tag'] = 'B_bb_reentry'

        dataframe.loc[mask_C, 'enter_long'] = 1
        dataframe.loc[mask_C, 'enter_tag'] = 'C_stochrsi'

        dataframe.loc[mask_D, 'enter_long'] = 1
        dataframe.loc[mask_D, 'enter_tag'] = 'D_capitulation'

        dataframe.loc[mask_E, 'enter_long'] = 1
        dataframe.loc[mask_E, 'enter_tag'] = 'E_ema8_pullback'

        dataframe.loc[mask_F, 'enter_long'] = 1
        dataframe.loc[mask_F, 'enter_tag'] = 'F_rsi_extreme'

        dataframe.loc[mask_G, 'enter_long'] = 1
        dataframe.loc[mask_G, 'enter_tag'] = 'G_hammer'

        dataframe.loc[mask_H, 'enter_long'] = 1
        dataframe.loc[mask_H, 'enter_tag'] = 'H_panic_fear'

        dataframe.loc[mask_I, 'enter_long'] = 1
        dataframe.loc[mask_I, 'enter_tag'] = 'I_rsi_crash'

        dataframe.loc[mask_J, 'enter_long'] = 1
        dataframe.loc[mask_J, 'enter_tag'] = 'J_ai_news'

        return dataframe

    # ---------------------- SALIDAS (señal de venta como respaldo) ----------------------
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Rechazo fuerte cerca de banda superior (mecha y RSI alto)
        reject_upper = (
            (dataframe['upper_wick'] >= dataframe['atr'] * self.REJECT_UPPER_ATR_MULT) &
            (dataframe['upper_wick'] > (dataframe['close'] - dataframe['open']).abs() * self.REJECT_WICK_BODY_RATIO) &
            ((dataframe['high'] >= dataframe['bb_upperband'] * 0.999) | (dataframe['close'] >= dataframe['bb_upperband'])) &
            (dataframe['rsi'] >= self.SELL_RSI_REJECT)
        )

        dataframe.loc[
            (
                (
                    (dataframe['loc_peak']) &
                    (dataframe['close'] >= dataframe['bb_upperband'] * 0.999) &
                    (dataframe['rsi'] >= self.SELL_RSI_PEAK) &
                    (
                        (dataframe['macdhist'] < dataframe['macdhist'].shift(1)) |
                        (dataframe['close'] < dataframe['ema8']) |
                        (dataframe['close'] < dataframe['open'])
                    )
                )
                |
                (
                    (dataframe['high'].shift(1) >= dataframe['hh_20'].shift(1)) &
                    (dataframe['close'].shift(1) >= dataframe['ema8'].shift(1)) &
                    (dataframe['close'] < dataframe['ema8']) &
                    (dataframe['rsi'] >= self.SELL_RSI_HH_EMA) &
                    (dataframe['macdhist'] < dataframe['macdhist'].shift(1))
                )
                |
                reject_upper
            ),
            'exit_long'
        ] = 1
        return dataframe

    # ---------------------- UTILIDADES ----------------------
    def _bars_elapsed(self, trade: Trade, current_time: datetime) -> int:
        tf = self.timeframe
        if tf.endswith('h'):
            tf_minutes = int(tf[:-1]) * 60
        elif tf.endswith('m'):
            tf_minutes = int(tf[:-1])
        else:
            tf_minutes = int(tf)
        seconds = (current_time - trade.open_date_utc).total_seconds()
        return int(max(0, seconds) // (tf_minutes * 60))

    def _strong_bearish_reversal(self, pair: str) -> bool:
        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last = df.iloc[-1]
            return (last['minus_di'] > last['plus_di']) and (last['adx'] > 23) and (last['rsi'] < 55)
        except Exception:
            return False

    def _crash_incoming(self, pair: str) -> bool:
        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last = df.iloc[-1]
            prev = df.iloc[-2]
            fast_drop = (last['close'] <= last['ema8'] * self.CRASH_FAST_DROP_EMA8) and (last['pct_1'] <= self.CRASH_FAST_DROP_PCT1)
            atr_break = (last['low'] < last['ema_fast'] - self.CRASH_ATR_BREAK_MULT * last['atr'])
            bb_flush = (last['bb_percent'] < 0) and bool(last['bb_expanding']) and (last['macdhist'] < prev['macdhist'])
            di_shift = (last['adx'] > self.CRASH_ADX_MIN) and (last['minus_di'] > last['plus_di']) and (last['rsi'] < self.CRASH_RSI_MAX)
            return sum([fast_drop, atr_break, bb_flush or di_shift]) >= 2
        except Exception:
            return False

    # ---------------------- POSITION SIZING (news-aware) ----------------------
    def custom_stake_amount(
        self,
        pair: str,
        current_time,
        current_rate,
        proposed_stake: float,
        min_stake: Optional[float],
        max_stake: float,
        leverage,
        entry_tag,
        side,
    ) -> float:
        """
        Ajusta el tamaño de la posición según el ai_score de noticias del día.

        Lógica:
          ai_score >= +0.25 (noticias positivas claras) → stake × 1.5
          ai_score <= -0.25 (noticias negativas claras) → stake × 0.6
          entre -0.25 y +0.25 (neutral/sin datos)       → stake × 1.0

        Restricciones:
          - Nunca supera max_stake (capital disponible)
          - Nunca baja de min_stake (mínimo del exchange)
          - En backtest siempre ai_score = 0 → sin efecto sobre resultados históricos
        """
        try:
            coin = pair.split('/')[0]
            score = self._ai_scores.get(coin, 0.0) if hasattr(self, '_ai_scores') else 0.0

            if score >= 0.25:
                multiplier = 1.5   # noticias positivas → apostar más
            elif score <= -0.25:
                multiplier = 0.6   # noticias negativas → apostar menos
            else:
                multiplier = 1.0   # neutral

            adjusted = proposed_stake * multiplier
            if min_stake is not None:
                adjusted = max(adjusted, min_stake)
            return min(adjusted, max_stake)
        except Exception:
            return proposed_stake

    # ---------------------- EXITS (alineadas con picos/vales óptimos) ----------------------
    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs
    ) -> Optional[str]:
        # Crash guard
        if self._crash_incoming(pair):
            if (current_profit is None) or (current_profit > self.MIN_PROFIT_NET):
                return "crash_guard"

        bars = self._bars_elapsed(trade, current_time)
        if bars < self.MIN_HOLD_BARS:
            if not self._strong_bearish_reversal(pair):
                return None

        # TP duro
        if current_profit is not None and current_profit >= self.HARD_TP:
            return "hard_tp"

        # Requiere beneficio neto
        if current_profit is None or current_profit < self.MIN_PROFIT_NET:
            return None

        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last  = df.iloc[-1]
            prev  = df.iloc[-2]

            near_upper = (last['close'] >= last['bb_upperband'] * 0.999) or (last['high'] >= last['bb_upperband'])
            loc_peak   = bool(last['high'] >= df['high'].rolling(6).max().iloc[-1])
            rsi_high   = (last['rsi'] >= self.SELL_RSI_PEAK)
            bear_candle= (last['close'] < last['open'])
            macd_fade  = (last['macdhist'] < prev['macdhist'])
            ema_break  = (last['close'] < last['ema8'])

            # Rally activo: si el precio está subiendo fuerte, no interferir con custom_exit.
            # Dejar que el trailing stop gestione la salida (es su función en subidas verticales).
            # Se detecta rally por ROC5 alto (1.5%+ en 1h15m) O por momentum alcista claro.
            in_rally = (
                (float(last['roc5']) >= ROC5_VERTICAL) or
                (float(last['rsi']) > 60 and
                 float(last['rsi']) > float(prev['rsi']) and
                 not macd_fade)
            )

            # Pico óptimo: banda sup + máximo local + giro claro
            # (se evalúa incluso en rally — si RSI>74 y hay vela bajista, es pico real)
            if current_profit >= self.sell_peak_min_profit.value and near_upper and loc_peak and rsi_high and (
                bear_candle or macd_fade or ema_break
            ):
                return "peak_exit_top_optimal"

            # HH + ruptura EMA8 + MACD debilitando (clásico)
            if current_profit >= self.sell_hh_ema_min.value and (prev['high'] >= df['high'].rolling(20).max().iloc[-2]) and ema_break and macd_fade and (last['rsi'] >= self.SELL_RSI_HH_EMA):
                return "hh_ema8_break_exit"

            # Rechazo de mecha grande en zona alta
            upper_wick = float(last['high'] - max(last['open'], last['close']))
            body = float(abs(last['close'] - last['open']))
            if current_profit >= self.MIN_PROFIT_NET and near_upper and (upper_wick >= last['atr'] * self.REJECT_UPPER_ATR_MULT) and (upper_wick > self.REJECT_WICK_BODY_RATIO * body) and (last['rsi'] >= self.SELL_RSI_WICK):
                return "upper_wick_reject_exit"

            # Señal de Claude como inclinación suave (peso menor que noticias — son interpretación)
            # Solo se consulta si hay beneficio real para no gastar API en trades perdedores
            claude_signal = self._get_claude_chart_signal(pair, current_profit, df) if current_profit >= 0.01 else 0

            # Salida rápida si en 12h el trade no ha progresado:
            # Claude EXIT adelanta el umbral a 6h; sin señal espera 12h completas
            stagnant_bars = 24 if claude_signal <= -1 else 48
            if bars >= stagnant_bars and self.MIN_PROFIT_NET <= current_profit <= 0.04:
                not_rising = not (float(last['rsi']) > 55 and float(last['rsi']) > float(prev['rsi']) and not macd_fade)
                if not_rising:
                    return "stagnant_exit"

            # Durante un rally activo o si Claude dice HOLD, no salir por momentum fade:
            # el trailing stop se encargará cuando el precio realmente gire
            if in_rally or claude_signal >= 1:
                return None

            # Pérdida de momentum — dos niveles:
            # 1) Ganancias moderadas (<7%): no requiere EMA8 break si RSI ya claramente bajista (<42)
            #    Captura trades tipo ALGO que van a 3-5% y no alcanzan el BB upper ni RSI 74
            # 2) Ganancias mayores: comportamiento original (EMA8 break obligatorio)
            if current_profit >= (self.MIN_PROFIT_NET + 0.002) and bars >= 4:
                if (last['rsi'] < last['rsi_prev']) and macd_fade:
                    if ema_break or (current_profit < 0.07 and last['rsi'] < 42):
                        return "momentum_fade_exit"

            # Exit por tiempo + momentum agotado: lleva >32h en ganancia moderada sin seguir subiendo
            # Captura ALGO-type: +4% después de 2 días que no sube más pero tampoco cae a RSI<42
            # No afecta BONK/memes: si siguen subiendo fuerte, MACD no está fading 2 barras seguidas
            macd_fade_2bars = macd_fade and (prev['macdhist'] < df.iloc[-3]['macdhist'])
            if bars >= 128 and 0.03 <= current_profit <= 0.15 and macd_fade_2bars and last['rsi'] < last['rsi_prev'] and last['rsi'] < 58:
                return "long_hold_fade_exit"

        except Exception:
            pass

        return None

    # ---------------------- CLAUDE CHART SIGNAL ----------------------
    def _get_claude_chart_signal(self, pair: str, current_profit: float, df) -> int:
        """
        Consulta a Claude sobre el estado del trade basándose en indicadores actuales.
        Retorna: 1 (mantener/HOLD), 0 (neutral), -1 (salir/EXIT)
        Cacheado 1h por par para no saturar la API.
        Es una INCLINACIÓN, no una decisión definitiva — peso menor que las noticias.
        """
        if not hasattr(self, '_claude_chart_cache'):
            self._claude_chart_cache: dict = {}
        now = time.time()
        cached = self._claude_chart_cache.get(pair)
        if cached and (now - cached[0]) < 3600:
            return cached[1]
        try:
            env_file = Path(__file__).parent.parent.parent / 'ops' / '.env'
            api_key = ''
            if env_file.exists():
                for line in env_file.read_text().splitlines():
                    if line.startswith('ANTHROPIC_API_KEY='):
                        api_key = line.split('=', 1)[1].strip()
            if not api_key:
                return 0
            import anthropic
            last = df.iloc[-1]
            prev = df.iloc[-2]
            macd_dir = "subiendo" if float(last['macdhist']) > float(prev['macdhist']) else "bajando"
            roc5 = float(last.get('roc5', 0))
            vol_ratio = float(last['volume']) / max(float(last['vol_mean_fast']), 1)
            prompt = (
                f"Trade crypto abierto. Indica si mantener o salir.\n"
                f"Par: {pair} | Beneficio: {current_profit*100:.1f}%\n"
                f"RSI: {float(last['rsi']):.0f} (anterior {float(prev['rsi']):.0f})\n"
                f"MACD histograma: {macd_dir}\n"
                f"Posición BB: {float(last['bb_percent'])*100:.0f}% (0=fondo, 100=techo)\n"
                f"ROC 5h: {roc5:.1f}% | Volumen vs media: {vol_ratio:.1f}x\n"
                f"Responde solo: HOLD, EXIT o NEUTRAL"
            )
            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=10,
                messages=[{"role": "user", "content": prompt}]
            )
            word = response.content[0].text.strip().upper()
            signal = 1 if 'HOLD' in word else (-1 if 'EXIT' in word else 0)
            self._claude_chart_cache[pair] = (now, signal)
            return signal
        except Exception:
            return 0

    # ---------------------- TRAILING ----------------------
    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs
    ) -> float:
        if current_profit is None or current_profit < 0.03:
            # stoploss_from_open fija el stop en open-5% independientemente del precio actual
            # Evita que el stop suba mientras el trade está en pérdidas o beneficio mínimo
            return stoploss_from_open(current_profit if current_profit else 0.0, abs(self.stoploss))

        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last = df.iloc[-1]
            atr = float(last['atr'])
            adx = float(last['adx'])
            roc5 = float(last['roc5'])
        except Exception:
            return stoploss_from_open(current_profit, self.FALLBACK_TRAIL_DIST)

        strong_trend = (adx >= self.ADX_STRONG_TREND and roc5 > 0)
        vertical_rally = (roc5 >= self.ROC5_VERTICAL)

        k = self.TRAIL_ATR_MULT_HIGH if current_profit > 0.06 else self.TRAIL_ATR_MULT_LOW
        dist = (k * atr) / max(current_rate, 1e-9)
        dist = min(self.TRAIL_DIST_MAX, max(self.TRAIL_DIST_MIN, dist))

        if vertical_rally:
            dist = max(dist, self.TRAIL_VERTICAL_MIN)
        elif not strong_trend:
            dist = min(dist, 0.02)

        if 0.03 <= current_profit < 0.06:
            return stoploss_from_open(current_profit, max(0.018, dist))

        return stoploss_from_open(current_profit, dist)