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
# � PARÁMETROS GLOBALES AJUSTABLES
# ==========================
# --- Costes y ganancias mínimas ---
FEE_RATE = 0.001                # � Comisión por operación.
SLIPPAGE_BUFFER = 0.0006        # � Margen extra para cubrir deslizamiento.
MIN_PROFIT_NET = 3 * FEE_RATE + SLIPPAGE_BUFFER  # � Reducido de 6x a 3x para no ignorar rebotes rápidos.
PEAK_MIN_PROFIT = 0.008         # �️ Bajado de 0.010 a 0.008 para capturar picos en mercados menos volátiles.
HH_EMA_MIN_PROFIT = 0.010       # � Bajado de 0.013 para asegurar beneficios tras máximos.
HARD_TP = 0.040                 # � Take profit fijo subido ligeramente para dejar correr rallies fuertes.

# --- Stoploss y trailing ---
STOPLOSS_ABS = -0.050           # � Stoploss ajustado a -5% (más estándar para 5m).
TRAIL_ATR_MULT_LOW = 2.0        # � Más ajustado para proteger ganancias iniciales.
TRAIL_ATR_MULT_HIGH = 3.0       # � Holgado para tendencias maduras.
TRAIL_DIST_MIN = 0.015          # � Reducido de 0.02 para capturar beneficios en giros rápidos.
TRAIL_DIST_MAX = 0.050          # � Distancia máxima ajustada.
TRAIL_VERTICAL_MIN = 0.020      # � Ajustado para rallies verticales.
ADX_STRONG_TREND = 25           # � Bajado de 27 para detectar tendencias un poco antes.
ROC5_VERTICAL = 3.0             # � Sensibilidad de rally vertical aumentada.
FALLBACK_TRAIL_DIST = 0.020     # � Reducido para mayor seguridad.

# --- Anti-cuchillo ---
PCT1_MIN = -3.5                 # � Bajado de -2.5 para permitir comprar tras un "flash drop" si hay rebote.
PCT3_MIN = -7.0                 # � Bajado de -5.5 para no quedar fuera en días de alta volatilidad.
COOLDOWN_BARS = 2               # � Reducido de 3 a 2 velas para reaccionar antes al rebote tras vela roja.

# --- Filtro de compras altas ---
NO_BUY_BB_MULT = 1.005          # � Permite comprar ligeramente por encima de la media si hay fuerza.
NO_BUY_EMA20_MULT = 1.005       # � Permite un margen del 0.5% sobre la EMA20.
NO_BUY_RSI_MIN = 62             # � Subido de 55 a 62; 55 era demasiado restrictivo para mercados alcistas.

# --- Zonas de valor para comprar ---
DEEP_BB = 0.20                  # � Subido de 0.16 para capturar más valles.
BB_ZONE_OK = 0.38               # � Subido de 0.33 para ampliar la zona de compra aceptable.
LOWER_WICK_BODY_RATIO = 1.20    #  candle_martillo: bajado de 1.30 para ser menos exigente con la mecha.

# --- Reglas de compra específicas ---
A_LL10_MULT = 1.008             # � Más flexible para detectar mínimos locales.
A_RSI_PREV_MAX = 50             # � Subido de 46 para permitir compras en recuperaciones tras consolidación.
C_STOCH_MAX = 35                # � Subido de 25; 25 era sobreventa extrema, 35 es más común.
D_PCT1_MAX = -2.0               # � Ajustado para detectar capitulación con más facilidad.
D_PCT3_MAX = -4.5               # � Capitulación en 3 velas ajustada.
D_BB_PERCENT_MAX = 0.08         # � Subido de 0.04; permite capitulaciones cerca (pero no solo fuera) de la banda.
D_TAIL_ATR_MULT = 1.00          # � Bajado de 1.25 para detectar colas de martillo más frecuentes.
E_RSI_MIN = 40                  # � Pullback EMA8: bajado de 44 para permitir rebotes desde más abajo.
E_LL10_MULT = 1.010             # � Más margen para detectar el apoyo en el pullback.
E_BB_MID_MULT = 1.002           # � Permite estar justo en la banda media en el pullback.
F_BB_PERCENT_MAX = 0.35         # �️ Doble toque: subido de 0.28 para ver más formaciones de suelo.
F_LL10_UPPER = 1.010            # �️ Mayor tolerancia para el segundo toque del doble suelo.
F_LL10_LOWER = 0.990            # �️ Mayor tolerancia para el segundo toque.

# --- Ventas ---
REJECT_UPPER_ATR_MULT = 0.90    # � Bajado de 1.0 para detectar rechazos de techo más rápido.
REJECT_WICK_BODY_RATIO = 1.20   # � Menos exigente con la proporción de mecha para vender.
SELL_RSI_PEAK = 70              # � Bajado de 72; 70 es el estándar de sobrecompra.
SELL_RSI_REJECT = 62            # � Bajado de 66 para salir de zonas de duda antes.
SELL_RSI_HH_EMA = 62            # � Bajado de 65 para asegurar ganancias.
SELL_RSI_WICK = 62              # � Bajado de 66 para ser más sensible a mechas de rechazo.

# --- Crash-guard ---
CRASH_FAST_DROP_EMA8 = 0.985    # ⚡ Umbral de caída bajo EMA8.
CRASH_FAST_DROP_PCT1 = -1.5     # ⚡ Requiere una caída más real (-1.5%) para activar pánico.
CRASH_ATR_BREAK_MULT = 1.8      # ⚡ Ruptura de ATR para crash.
CRASH_ADX_MIN = 22              # ⚡ Bajado de 26 para detectar giros bajistas antes.
CRASH_RSI_MAX = 52              # ⚡ RSI máximo para crash.

# --- Bollinger config ---
BB40_WINDOW = 40                
BB40_STDS = 2.0                 # � Bajado de 2.2 para que las bandas sean más reactivas al precio.
BB20_WINDOW = 20                
BB20_STDS = 2.0                 # � Bajado de 2.2; el estándar es 2.0.

# --- Anti-chase (evitar compras en subidas/picos) ---
MAX_PCT_UP_1 = 1.2              # % Subido de 0.6; 0.6 bloqueaba casi cualquier vela verde de inicio.
MAX_PCT_UP_3 = 3.0              # % Subido de 1.8; permite entrar en tendencias que acaban de arrancar.
MAX_GREEN_STREAK = 3            # Subido de 2 a 3; 2 velas verdes son muy comunes en un rebote sano.
BUY_BELOW_EMA20_MULT = 1.002    # Subido de 0.996; permite comprar "en" la EMA20, no solo "muy por debajo".
BUY_BELOW_BB_MID_MULT = 1.002   # Permite comprar en la zona media, vital para no perder el tren.
BB_EXPANDING_HIGH = 0.65        # Subido de 0.50; 0.50 bloqueaba compras en cuanto el precio superaba la mitad.
PUMP_VOL_MULT = 2.5             # Subido de 2.2 para no confundir volumen sano con un pump parabólico.
NEAR_HH_DISTANCE = 0.008        # Reducido de 0.015; permite comprar más cerca del máximo previo.
REQUIRE_RED_PULLBACK = True     # Mantenido: exige una pequeña pausa para no comprar el pico del minuto.

# --- Parámetros nuevos para líneas que estaban "a pelo" ---
VOL_SPIKE_MULT = 1.10           # Multiplicador para 'vol_spike' (era 1.15)
ADX_BEARISH_REVERSAL = 22       # ADX para la utilidad _strong_bearish_reversal (era 23)
RSI_BEARISH_REVERSAL = 58       # RSI para la utilidad _strong_bearish_reversal (era 55)
MIN_PROFIT_MOMENTUM = 0.005     # Beneficio extra para momentum_fade_exit (era 0.002)
NEAR_UPPER_THRESHOLD = 0.998    # Cercanía a banda superior para ventas (era 0.999)



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
        dataframe['vol_spike'] = dataframe['volume'] > (dataframe['volume_mean_slow'] * VOL_SPIKE_MULT)

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
            (~(dataframe['pump_vol'] & (dataframe['pct_1'] > (MAX_PCT_UP_1 * 0.8)))) &
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
            return (last['minus_di'] > last['plus_di']) and (last['adx'] > ADX_BEARISH_REVERSAL) and (last['rsi'] < RSI_BEARISH_REVERSAL)
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
            if current_profit >= (self.MIN_PROFIT_NET + MIN_PROFIT_MOMENTUM) and bars >= 6:
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