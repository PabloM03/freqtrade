import freqtrade.vendor.qtpylib.indicators as qtpylib
import numpy as np
# --------------------------------
import talib.abstract as ta
from freqtrade.strategy.interface import IStrategy
from freqtrade.strategy import stoploss_from_open
from pandas import DataFrame
from datetime import datetime
from typing import Optional
from freqtrade.persistence import Trade

# ==========================
# 📌 PARÁMETROS GLOBALES AJUSTABLES
# ==========================
# --- Costes y ganancias mínimas ---
FEE_RATE = 0.001                # 💸 Comisión por operación. Se usa para calcular beneficios netos y evitar operar con ganancias insuficientes. Rango típico: 0.0005-0.002. Subirlo reduce operaciones pequeñas.
SLIPPAGE_BUFFER = 0.0006        # 🏃 Margen extra para cubrir deslizamiento en la ejecución de órdenes. Rango típico: 0.0002-0.001. Subirlo exige más beneficio antes de vender.
MIN_PROFIT_NET = 5 * FEE_RATE + SLIPPAGE_BUFFER  # 📈 Beneficio neto mínimo requerido para vender, considerando comisiones y deslizamiento. Rango típico: 0.002-0.004. Subirlo exige más beneficio antes de vender.
PEAK_MIN_PROFIT = 0.008         # 🏔️ Beneficio mínimo para permitir salida en pico óptimo (máximos locales). Rango típico: 0.004-0.01. Subirlo hace más exigente la venta en picos.
HH_EMA_MIN_PROFIT = 0.012       # 📊 Beneficio mínimo para salida por ruptura de EMA8 tras un máximo. Rango típico: 0.006-0.012. Subirlo hace más difícil vender tras máximos.
HARD_TP = 0.060                 # 🎯 Take profit fijo para asegurar ganancias si se alcanza. Rango típico: 0.01-0.03. Subirlo busca ganancias mayores pero puede perder retrocesos.

# --- Stoploss y trailing ---
STOPLOSS_ABS = -0.05            # 🛑 Stoploss absoluto para limitar pérdidas máximas por operación. Rango típico: -0.03 a -0.08. Subirlo (menos negativo) reduce pérdidas pero puede saltar antes.
TRAIL_ATR_MULT_LOW = 2.1        # 🐢 Multiplicador de ATR para trailing stop si beneficio bajo (stop más ajustado). Rango típico: 1.5-2.5. Subirlo aleja el trailing stop.
TRAIL_ATR_MULT_HIGH = 3.0       # 🦅 Multiplicador de ATR para trailing stop si beneficio alto (stop más holgado). Rango típico: 2.0-3.0. Subirlo aleja el trailing stop en beneficios altos.
TRAIL_DIST_MIN = 0.018          # 📏 Distancia mínima para trailing stop, evita stops demasiado ajustados. Rango típico: 0.01-0.02. Subirlo da más margen antes de saltar el stop.
TRAIL_DIST_MAX = 0.050          # 📏 Distancia máxima para trailing stop, evita stops demasiado lejanos. Rango típico: 0.025-0.04. Subirlo permite stops más lejanos.
TRAIL_VERTICAL_MIN = 0.024      # 🚀 Distancia mínima para trailing si hay rally vertical. Rango típico: 0.015-0.03. Subirlo da más margen en subidas rápidas.
ADX_STRONG_TREND = 25           # 💪 Valor mínimo de ADX para considerar tendencia fuerte (mayor protección trailing). Rango típico: 20-35. Subirlo exige tendencia más fuerte para trailing holgado.
ROC5_VERTICAL = 2.8             # 📈 ROC5 mínimo para considerar rally vertical. Rango típico: 2-5. Subirlo exige movimientos más bruscos para activar trailing vertical.
FALLBACK_TRAIL_DIST = 0.020     # 🛟 Distancia fallback si falla el cálculo de trailing dinámico. Rango típico: 0.012-0.025. Subirlo da más margen de seguridad.

# --- Anti-cuchillo ---
PCT1_MIN = -1.0                 # 🔪 Caída máxima en 1 vela para permitir compra (evita comprar en caídas bruscas). Rango típico: -1.0 a -2.0. Bajarlo permite compras en caídas más fuertes.
PCT3_MIN = -2.2                 # 🔪 Caída máxima en 3 velas para permitir compra (protege de tendencias bajistas fuertes). Rango típico: -2.0 a -4.0. Bajarlo permite compras en tendencias más bajistas.
COOLDOWN_BARS = 4               # 🧊 Número de velas de enfriamiento tras una vela roja grande. Rango típico: 2-6. Subirlo aumenta el tiempo sin comprar tras caídas fuertes.

# --- Filtro de compras altas ---
NO_BUY_BB_MULT = 1.010          # 🚫 Multiplicador de la banda media BB para evitar compras "arriba". Rango típico: 1.01-1.15. Subirlo permite comprar más alto.
NO_BUY_EMA20_MULT = 1.002       # 🚫 Multiplicador de EMA20 para evitar compras "arriba". Rango típico: 1.0-1.05. Subirlo permite comprar más alto.
NO_BUY_RSI_MIN = 60             # 🚫 RSI mínimo para evitar compras en sobrecompra. Rango típico: 55-65. Subirlo evita compras en zonas más sobrecompradas.

# --- Zonas de valor para comprar ---
DEEP_BB = 0.20                  # 🏦 Profundidad máxima de BB% para considerar compra en zona muy baja. Rango típico: 0.15-0.25. Subirlo permite compras menos profundas.
BB_ZONE_OK = 0.38               # 🏦 BB% máximo para considerar zona de compra aceptable. Rango típico: 0.3-0.45. Subirlo permite compras en zonas menos bajas.
LOWER_WICK_BODY_RATIO = 1.12    # 🕯️ Relación mecha inferior/cuerpo para identificar velas tipo martillo. Rango típico: 1.1-1.3. Subirlo exige mechas más largas para considerar giro.

# --- Reglas de compra específicas ---
# A) Mínimo local
A_LL10_MULT = 1.0045            # 📉 Multiplicador para comparar el mínimo local con el mínimo de las últimas 10 velas. Rango típico: 1.002-1.01. Subirlo exige mínimos más bajos para detectar valle.
A_RSI_PREV_MAX = 47             # 📉 RSI máximo previo para permitir compra en giro alcista tras sobreventa. Rango típico: 40-50. Subirlo permite compras con menos sobreventa previa.
# B) Re-entrada tras BB baja -> usa BB_ZONE_OK
# C) StochRSI en sobreventa
C_STOCH_MAX = 34                # 📉 Valor máximo de StochRSI para considerar sobreventa y posible rebote. Rango típico: 30-40. Subirlo permite compras con menos sobreventa.
# D) Capitulación
D_PCT1_MAX = -1.8               # 💥 Caída máxima en 1 vela para detectar capitulación. Rango típico: -1.5 a -2.5. Bajarlo detecta capitulaciones más bruscas.
D_PCT3_MAX = -3.4               # 💥 Caída máxima en 3 velas para detectar capitulación. Rango típico: -3.0 a -5.0. Bajarlo detecta caídas más fuertes.
D_BB_PERCENT_MAX = 0.06         # 💥 BB% máximo para capitulación (muy cerca de la banda inferior). Rango típico: 0.03-0.08. Subirlo permite capitulación menos extrema.
D_TAIL_ATR_MULT = 1.10          # 💥 Multiplicador de ATR para la cola de la vela (mecha larga indica rebote). Rango típico: 0.8-1.5. Subirlo exige mechas más largas.
# E) Pullback a EMA8
E_RSI_MIN = 46                  # 🔄 RSI mínimo para permitir pullback alcista. Rango típico: 40-50. Subirlo exige más fuerza en el rebote.
E_LL10_MULT = 1.008             # 🔄 Multiplicador para comparar el mínimo con el mínimo de 10 velas. Rango típico: 1.005-1.02. Subirlo exige mínimos más bajos.
E_BB_MID_MULT = 1.005           # 🔄 Multiplicador para comparar el precio con la banda media BB. Rango típico: 1.005-1.02. Subirlo exige precios más bajos respecto a la banda media.
# F) Doble toque en valle
F_BB_PERCENT_MAX = 0.32         # 🏞️ BB% máximo para doble toque en valle. Rango típico: 0.25-0.35. Subirlo permite doble toque en zonas menos bajas.
F_LL10_UPPER = 1.006            # 🏞️ Multiplicador superior para doble toque. Rango típico: 1.002-1.01. Subirlo permite más diferencia entre toques.
F_LL10_LOWER = 0.992            # 🏞️ Multiplicador inferior para doble toque. Rango típico: 0.98-0.995. Bajarlo permite más diferencia entre toques.

# --- Ventas ---
REJECT_UPPER_ATR_MULT = 1.05    # 🚩 Multiplicador de ATR para detectar mecha superior grande. Rango típico: 0.8-1.2. Subirlo exige mechas más largas para vender.
REJECT_WICK_BODY_RATIO = 1.25   # 🚩 Relación mecha/cuerpo para identificar rechazo fuerte. Rango típico: 1.1-1.4. Subirlo exige mechas más largas respecto al cuerpo.
SELL_RSI_PEAK = 66              # 🚩 RSI mínimo para vender en pico. Rango típico: 65-75. Subirlo exige sobrecompra más fuerte.
SELL_RSI_REJECT = 60            # 🚩 RSI mínimo para vender por rechazo en zona alta. Rango típico: 55-65. Subirlo exige más sobrecompra para vender por rechazo.
SELL_RSI_HH_EMA = 60            # 🚩 RSI mínimo para vender tras ruptura de EMA8 en máximos. Rango típico: 58-65. Subirlo exige más sobrecompra.
SELL_RSI_WICK = 60              # 🚩 RSI mínimo para vender por mecha superior grande. Rango típico: 58-65. Subirlo exige más sobrecompra.

# --- Crash-guard ---
CRASH_FAST_DROP_EMA8 = 0.987    # ⚡ Multiplicador para detectar caída rápida bajo EMA8. Rango típico: 0.99-0.995. Bajarlo detecta caídas más leves.
CRASH_FAST_DROP_PCT1 = -0.8     # ⚡ Caída máxima en 1 vela para crash-guard. Rango típico: -0.5 a -1.0. Bajarlo detecta caídas más leves.
CRASH_ATR_BREAK_MULT = 1.6      # ⚡ Multiplicador de ATR para detectar ruptura fuerte bajo EMA. Rango típico: 1.3-2.0. Subirlo exige rupturas más grandes.
CRASH_ADX_MIN = 23              # ⚡ ADX mínimo para considerar crash. Rango típico: 18-28. Subirlo exige tendencia bajista más fuerte.
CRASH_RSI_MAX = 50              # ⚡ RSI máximo para crash. Rango típico: 45-52. Subirlo permite crash-guard con menos sobreventa.

# --- Timeframe y arranque ---
TIMEFRAME = '5m'                # ⏰ Timeframe de operación. Rango típico: '1m', '5m', '15m'. Cambiarlo afecta la frecuencia y sensibilidad de señales.
STARTUP_CANDLES = 125           # ⏰ Número de velas iniciales requeridas para calcular indicadores. Rango típico: 50-150. Subirlo mejora precisión de indicadores largos.

# --- Bollinger config ---
BB40_WINDOW = 40                # 📊 Ventana de velas para Bollinger Bands largas. Rango típico: 30-60. Subirlo suaviza las bandas.
BB40_STDS = 2.1                 # 📊 Desviaciones estándar para BB40. Rango típico: 1.8-2.5. Subirlo amplía las bandas.
BB20_WINDOW = 20                # 📊 Ventana de velas para Bollinger Bands cortas. Rango típico: 15-30. Subirlo suaviza las bandas.
BB20_STDS = 2.1                 # 📊 Desviaciones estándar para BB20. Rango típico: 1.8-2.5. Subirlo amplía las bandas.

# --- Anti-chase (evitar compras en subidas/picos) ---
MAX_PCT_UP_1 = 1.2              # % máx. subida en 1 vela para permitir compra (usa misma escala que PCT1_MIN: en %)
MAX_PCT_UP_3 = 3.2              # % máx. subida en 3 velas para permitir compra
MAX_GREEN_STREAK = 4            # nº máx. de velas verdes recientes; si hay racha >= N, no comprar
BUY_BELOW_EMA20_MULT = 0.999    # exigir que el precio esté por DEBAJO de EMA20 (0.998 = -0.2%)
BUY_BELOW_BB_MID_MULT = 0.999   # exigir que el precio esté por DEBAJO de la banda media BB
BB_EXPANDING_HIGH = 0.60        # si bb_percent >= 0.55 y bb_expanding, no comprar (expansión arriba)
PUMP_VOL_MULT = 1.6             # volumen de la vela > 1.7x media rápida => posible pump (bloquear)
NEAR_HH_DISTANCE = 0.0060       # no comprar si el precio está a <0.3% del máximo 20 velas
REQUIRE_RED_PULLBACK = False    # exigir una “pausa” (pullback leve) antes de permitir compra tras subidón



def bollinger_bands(stock_price, window_size, num_of_std):
    rolling_mean = stock_price.rolling(window=window_size).mean()
    rolling_std = stock_price.rolling(window=window_size).std()
    lower_band = rolling_mean - (rolling_std * num_of_std)
    return np.nan_to_num(rolling_mean), np.nan_to_num(lower_band)


class CombinedBinHAndCluc(IStrategy):
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

    use_sell_signal = False
    sell_profit_only = True
    ignore_roi_if_buy_signal = False
    trailing_stop = False
    minimal_roi = {"0": 0.0}
    MIN_HOLD_BARS = 1

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
    F_BB_PERCENT_MAX = F_BB_PERCENT_MAX
    F_LL10_UPPER = F_LL10_UPPER
    F_LL10_LOWER = F_LL10_LOWER

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

    # ---------------------- INDICADORES ----------------------
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # BinHV45 (BB40)
        mid, lower = bollinger_bands(
            dataframe['close'], window_size=self.BB40_WINDOW, num_of_std=self.BB40_STDS
        )
        dataframe['lower'] = lower
        dataframe['bbdelta'] = (mid - dataframe['lower']).abs()
        dataframe['closedelta'] = (dataframe['close'] - dataframe['close'].shift()).abs()
        dataframe['tail'] = (dataframe['close'] - dataframe['low']).abs()

        # Bollinger 20
        tp = qtpylib.typical_price(dataframe)
        bb = qtpylib.bollinger_bands(tp, window=self.BB20_WINDOW, stds=self.BB20_STDS)
        dataframe['bb_lowerband']  = bb['lower']
        dataframe['bb_middleband'] = bb['mid']
        dataframe['bb_upperband']  = bb['upper']
        dataframe['bb_width'] = (dataframe['bb_upperband'] - dataframe['bb_lowerband']) / dataframe['bb_middleband']
        denom = (dataframe['bb_upperband'] - dataframe['bb_lowerband']).replace(0, np.nan)
        dataframe['bb_percent'] = (dataframe['close'] - dataframe['bb_lowerband']) / denom
        dataframe['bb_expanding'] = (dataframe['bb_width'] > dataframe['bb_width'].shift(1))

        # EMAs / fuerza
        dataframe['ema8']     = ta.EMA(dataframe, timeperiod=8)
        dataframe['ema_fast'] = ta.EMA(dataframe, timeperiod=20)
        dataframe['ema_slow'] = ta.EMA(dataframe, timeperiod=50)
        dataframe['volume_mean_slow'] = dataframe['volume'].rolling(window=30).mean()
        dataframe['ema8_slope_up'] = dataframe['ema8'] > dataframe['ema8'].shift(1)

        # RSI / ADX / DI
        dataframe['rsi']      = ta.RSI(dataframe, timeperiod=14)
        dataframe['rsi_prev'] = dataframe['rsi'].shift(1)
        dataframe['adx']      = ta.ADX(dataframe, timeperiod=14)
        dataframe['plus_di']  = ta.PLUS_DI(dataframe, timeperiod=14)
        dataframe['minus_di'] = ta.MINUS_DI(dataframe, timeperiod=14)

        # StochRSI
        stoch = ta.STOCHRSI(dataframe, timeperiod=14, fastk_period=3, fastd_period=3)
        dataframe['stoch_k'] = stoch['fastk']
        dataframe['stoch_d'] = stoch['fastd']
        dataframe['stoch_k_prev'] = dataframe['stoch_k'].shift(1)
        dataframe['stoch_d_prev'] = dataframe['stoch_d'].shift(1)

        # MACD
        macd = ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)
        dataframe['macd']      = macd['macd']
        dataframe['macdsignal']= macd['macdsignal']
        dataframe['macdhist']  = macd['macdhist']

        # Momentum/extremos
        dataframe['roc5'] = ta.ROC(dataframe, timeperiod=5)
        dataframe['ll_8']  = dataframe['low'].rolling(8).min()
        dataframe['ll_10'] = dataframe['low'].rolling(10).min()
        dataframe['ll_20'] = dataframe['low'].rolling(20).min()
        dataframe['hh_20'] = dataframe['high'].rolling(20).max()

        # ATR y variaciones
        dataframe['atr']  = ta.ATR(dataframe, timeperiod=14)
        dataframe['pct_1']= dataframe['close'].pct_change(1) * 100.0
        dataframe['pct_3']= dataframe['close'].pct_change(3) * 100.0

        # Estructura / cooldown
        body = (dataframe['close'] - dataframe['open']).abs()
        dataframe['big_red']  = (dataframe['close'] < dataframe['open']) & (body > 1.2 * dataframe['atr'])
        dataframe['cooldown'] = dataframe['big_red'].rolling(self.COOLDOWN_BARS).max()

        # Mechas
        dataframe['upper_wick'] = (dataframe['high'] - np.maximum(dataframe['open'], dataframe['close'])).abs()
        dataframe['lower_wick'] = (np.minimum(dataframe['open'], dataframe['close']) - dataframe['low']).abs()

        # Volumen relativo
        dataframe['vol_spike'] = dataframe['volume'] > (dataframe['volume_mean_slow'] * 1.15)

        # Máximo/mínimo local reciente (ventanas cortas) para “picos/vales óptimos”
        dataframe['loc_peak'] = (
            (dataframe['high'] >= dataframe['high'].rolling(6).max()) &
            (dataframe['high'] >= dataframe['high'].shift(1)) &
            (dataframe['high'] >= dataframe['high'].shift(2))
        )
        dataframe['loc_trough'] = (
            (dataframe['low'] <= dataframe['low'].rolling(6).min()) &
            (dataframe['low'] <= dataframe['low'].shift(1)) &
            (dataframe['low'] <= dataframe['low'].shift(2))
        )

        # Anti-chase helpers
        dataframe['green'] = dataframe['close'] > dataframe['open']
        dataframe['green_streak'] = (
            dataframe['green']
            .rolling(window=MAX_GREEN_STREAK, min_periods=1)
            .sum()
        )
        dataframe['vol_mean_fast'] = dataframe['volume'].rolling(window=10).mean()
        dataframe['pump_vol'] = dataframe['volume'] > (dataframe['vol_mean_fast'] * PUMP_VOL_MULT)
        dataframe['near_hh'] = dataframe['close'] >= (dataframe['hh_20'] * (1.0 - NEAR_HH_DISTANCE))


        return dataframe

    # ---------------------- COMPRAS (bajadas más óptimas) ----------------------
    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        anti_cuchillo = (
            (dataframe['pct_1'] > self.PCT1_MIN) &
            (dataframe['pct_3'] > self.PCT3_MIN) &
            (~dataframe['cooldown'].astype(bool)) &
            (~((dataframe['bb_percent'] < 0) & dataframe['bb_expanding'])) &
            (dataframe['minus_di'] <= dataframe['plus_di']) &
            (dataframe['volume'] > 0)
        )

        # Evitar compras “arriba” (requiere las 3 a la vez)
        no_buy_high = (
            (dataframe['close'] > dataframe['bb_middleband'] * self.NO_BUY_BB_MULT) &
            (dataframe['close'] > dataframe['ema_fast'] * self.NO_BUY_EMA20_MULT) &
            (dataframe['rsi'] > self.NO_BUY_RSI_MIN)
        )

        # Zonas de valor
        deep_bb    = (dataframe['bb_percent'] <= self.DEEP_BB)
        bb_zone_ok = (dataframe['bb_percent'] <= self.BB_ZONE_OK)

        lower_wick = dataframe['lower_wick']
        body       = (dataframe['close'] - dataframe['open']).abs()
        hammerish  = lower_wick > self.LOWER_WICK_BODY_RATIO * body

        
        # Bloqueo de compras en subidas/picos (anti-chase)
        anti_chase = (
            # No perseguir velas verdes muy fuertes (1 y 3 velas)
            (dataframe['pct_1'] < MAX_PCT_UP_1) &
            (dataframe['pct_3'] < MAX_PCT_UP_3) &
            # Evitar rachas de verdes consecutivas
            (dataframe['green_streak'] < MAX_GREEN_STREAK) &
            # Evitar compras arriba con bandas expandiéndose
            (~((dataframe['bb_percent'] >= BB_EXPANDING_HIGH) & (dataframe['bb_expanding']))) &
            # Evitar compras en pumps de volumen + vela verde fuerte
            (~(dataframe['pump_vol'] & (dataframe['pct_1'] > 0.6))) &
            # Exigir estar por debajo de referencias medias
            (dataframe['close'] <= dataframe['ema_fast'] * BUY_BELOW_EMA20_MULT) &
            (dataframe['close'] <= dataframe['bb_middleband'] * BUY_BELOW_BB_MID_MULT) &
            # Evitar compras pegadas a los máximos recientes
            (~dataframe['near_hh'])
        )

        if REQUIRE_RED_PULLBACK:
            anti_chase = anti_chase & (
                # pequeña pausa: vela roja o al menos barrido de mínimos vs cierre previo
                (dataframe['close'] <= dataframe['open']) |
                (dataframe['low'] < dataframe['close'].shift(1))
            )


        # A) Mínimo local + giro RSI + martillo/volumen (bajada óptima)
        A = (
            (dataframe['loc_trough']) &
            ((dataframe['low'] <= dataframe['ll_10'] * self.A_LL10_MULT) | deep_bb) &
            (dataframe['rsi_prev'] < self.A_RSI_PREV_MAX) & (dataframe['rsi'] > dataframe['rsi_prev']) &
            (dataframe['close'] >= dataframe['open']) &
            (hammerish | dataframe['vol_spike'])
        )

        # B) Re-entrada tras cerrar fuera de banda inferior y volver dentro (clásico y muy abajo)
        B = (
            (dataframe['close'].shift(1) < dataframe['bb_lowerband'].shift(1)) &
            (dataframe['close'] > dataframe['bb_lowerband']) &
            (dataframe['rsi'] > dataframe['rsi_prev']) &
            (bb_zone_ok)
        )

        # C) StochRSI cruce en sobreventa + MACD no empeora + en zona baja BB
        C = (
            (dataframe['stoch_k_prev'] < dataframe['stoch_d_prev']) &
            (dataframe['stoch_k'] > dataframe['stoch_d']) &
            (dataframe['stoch_k'] < self.C_STOCH_MAX) & (dataframe['stoch_d'] < self.C_STOCH_MAX) &
            (dataframe['macdhist'] >= dataframe['macdhist'].shift(1)) &
            (bb_zone_ok)
        )

        # D) Capitulación: vela muy roja previa / colas largas + rebote verde
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

        # F) Doble toque / higher-low sutil en zona baja (confirmación de valle)
        F = (
            (dataframe['bb_percent'] <= self.F_BB_PERCENT_MAX) &
            (dataframe['low'] <= dataframe['ll_10'] * self.F_LL10_UPPER) &
            (dataframe['low'] >= dataframe['ll_10'].shift(1) * self.F_LL10_LOWER) &
            (dataframe['rsi'] > dataframe['rsi_prev']) &
            (dataframe['close'] >= dataframe['open'])
        )

        dataframe.loc[
            (((A | B | C | D | E | F) & anti_cuchillo & ~no_buy_high & anti_chase) | D),
            'buy'
        ] = 1
        return dataframe

    # ---------------------- VENTAS (picos más óptimos) ----------------------
    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Rechazo fuerte cerca de banda superior (mecha y RSI alto)
        reject_upper = (
            (dataframe['upper_wick'] >= dataframe['atr'] * self.REJECT_UPPER_ATR_MULT) &
            (dataframe['upper_wick'] > (dataframe['close'] - dataframe['open']).abs() * self.REJECT_WICK_BODY_RATIO) &
            ((dataframe['high'] >= dataframe['bb_upperband'] * 0.999) | (dataframe['close'] >= dataframe['bb_upperband'])) &
            (dataframe['rsi'] >= self.SELL_RSI_REJECT)
        )

        dataframe.loc[
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
                # Máximo del rango + ruptura EMA8 posterior con MACD debilitando
                (dataframe['high'].shift(1) >= dataframe['hh_20'].shift(1)) &
                (dataframe['close'].shift(1) >= dataframe['ema8'].shift(1)) &
                (dataframe['close'] < dataframe['ema8']) &
                (dataframe['rsi'] >= self.SELL_RSI_HH_EMA) &
                (dataframe['macdhist'] < dataframe['macdhist'].shift(1))
            )
            |
            reject_upper,
            'sell'
        ] = 1
        return dataframe

    # ---------------------- UTILIDADES ----------------------
    def _bars_elapsed(self, trade: Trade, current_time: datetime) -> int:
        tf_minutes = int(self.timeframe.rstrip('m'))
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

            # Pico óptimo: banda sup + máximo local + giro claro
            if current_profit >= self.PEAK_MIN_PROFIT and near_upper and loc_peak and rsi_high and (
                bear_candle or macd_fade or ema_break
            ):
                return "peak_exit_top_optimal"

            # HH + ruptura EMA8 + MACD debilitando (clásico)
            if current_profit >= self.HH_EMA_MIN_PROFIT and (prev['high'] >= df['high'].rolling(20).max().iloc[-2]) and ema_break and macd_fade and (last['rsi'] >= self.SELL_RSI_HH_EMA):
                return "hh_ema8_break_exit"

            # Rechazo de mecha grande en zona alta
            upper_wick = float(last['high'] - max(last['open'], last['close']))
            body = float(abs(last['close'] - last['open']))
            if current_profit >= self.MIN_PROFIT_NET and near_upper and (upper_wick >= last['atr'] * self.REJECT_UPPER_ATR_MULT) and (upper_wick > self.REJECT_WICK_BODY_RATIO * body) and (last['rsi'] >= self.SELL_RSI_WICK):
                return "upper_wick_reject_exit"

            # Pérdida de momentum tras varias velas en verde
            if current_profit >= (self.MIN_PROFIT_NET + 0.002) and bars >= 6:
                if (last['rsi'] < last['rsi_prev']) and macd_fade and ema_break:
                    return "momentum_fade_exit"

        except Exception:
            pass

        return None

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
            return self.stoploss

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
