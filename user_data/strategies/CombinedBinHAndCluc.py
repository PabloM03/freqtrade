# filename: CombinedBinHAndCluc.py
# -*- coding: utf-8 -*-

# Estrategia Freqtrade lista para Hyperopt (TPE) sin reescribir tu lógica.
# - Convierte “constantes” a parámetros optimizables mediante un shim de @property.
# - Lanza hyperopt con: freqtrade hyperopt --spaces buy sell stoploss trailing protection ...


from datetime import datetime
from typing import Optional

import numpy as np
import talib.abstract as ta
from pandas import DataFrame

import freqtrade.vendor.qtpylib.indicators as qtpylib
from freqtrade.persistence import Trade
from freqtrade.strategy import (
    IStrategy,
    stoploss_from_open,
    IntParameter,
    DecimalParameter,
    BooleanParameter,
    CategoricalParameter,  # (no usado ahora, disponible si lo añades)
)

# ==========================
# 📌 PARÁMETROS GLOBALES (no optimizables por Hyperopt)
# ==========================
# Costes mínimos (solo para calcular MIN_PROFIT_NET en exits)
FEE_RATE = 0.001
SLIPPAGE_BUFFER = 0.0004
MIN_PROFIT_NET = 3 * FEE_RATE + SLIPPAGE_BUFFER   # ~0.0034 (0.34% neto mínimo)

def bollinger_bands(series, window_size: int, num_of_std: float):

    mean = series.rolling(window=window_size).mean()
    std = series.rolling(window=window_size).std()
    lower = mean - (std * num_of_std)
    return np.nan_to_num(mean), np.nan_to_num(lower)


class CombinedBinHAndCluc(IStrategy):
    """
    Compras: bajadas/pullbacks óptimos (vales locales + capitulación/giro)
    Ventas : picos locales con rechazo/giro (mechas, ruptura EMA8, MACD debilitando)
    Protección: crash-guard y trailing por ATR moderado.
    """

    # ==========================
    # Ajustes fijos de la estrategia
    # ==========================
    timeframe = '5m'
    startup_candle_count = 125
    process_only_new_candles = True

    # (Usa los nombres nuevos para evitar warnings deprecados)
    use_exit_signal = False
    exit_profit_only = True
    ignore_roi_if_entry_signal = False


    trailing_stop = False
    minimal_roi = {"0": 0.0}
    MIN_HOLD_BARS = 1  # no vender instantáneamente tras entrar

    # Habilitar custom_stoploss (por defecto es False si no lo marcas)
    use_custom_stoploss = True

    # Parámetros fijos auxiliares (puedes moverlos a Hyperopt si quieres)
    ADX_STRONG_TREND = 24
    ROC5_VERTICAL = 2.8

    # ==========================
    # ---------- PARÁMETROS OPTIMIZABLES (Hyperopt/TPE) ----------
    # ==========================

    # Beneficio / TP
    h_peak_min_profit    = DecimalParameter(0.004, 0.020, decimals=4, default=0.010, space='sell')
    h_hh_ema_min_profit  = DecimalParameter(0.006, 0.020, decimals=4, default=0.0095, space='sell')
    h_hard_tp            = DecimalParameter(0.010, 0.070, decimals=3, default=0.025, space='sell')

    # Stop / Trailing
    h_stoploss_abs       = DecimalParameter(-0.08, -0.02, decimals=3, default=-0.058, space='stoploss')
    h_trail_atr_low      = DecimalParameter(1.5, 3.0,  decimals=2, default=1.90, space='trailing')
    h_trail_atr_high     = DecimalParameter(2.0, 4.0,  decimals=2, default=2.60, space='trailing')
    h_trail_dist_min     = DecimalParameter(0.010, 0.030, decimals=3, default=0.015, space='trailing')
    h_trail_dist_max     = DecimalParameter(0.035, 0.080, decimals=3, default=0.045, space='trailing')
    h_trail_vertical_min = DecimalParameter(0.015, 0.040, decimals=3, default=0.022, space='trailing')
    h_fallback_trail     = DecimalParameter(0.012, 0.030, decimals=3, default=0.018, space='trailing')

    # Anti-cuchillo / filtros macro
    h_pct1_min           = DecimalParameter(-2.5, -0.5, decimals=2, default=-1.20, space='buy')  # %
    h_pct3_min           = DecimalParameter(-6.0, -1.5, decimals=2, default=-3.50, space='buy')  # %
    h_cooldown_bars      = IntParameter(2, 6, default=3, space='buy')

    # Filtro “compras arriba”
    h_no_buy_bb_mult     = DecimalParameter(0.990, 1.020, decimals=3, default=1.010, space='buy')
    h_no_buy_ema20_mult  = DecimalParameter(0.990, 1.020, decimals=3, default=1.003, space='buy')
    h_no_buy_rsi_min     = IntParameter(50, 70, default=62, space='buy')

    # Zonas BB y martillos
    h_deep_bb            = DecimalParameter(0.12, 0.25, decimals=3, default=0.22, space='buy')
    h_bb_zone_ok         = DecimalParameter(0.25, 0.50, decimals=3, default=0.40, space='buy')
    h_lower_wick_body    = DecimalParameter(1.05, 1.35, decimals=2, default=1.15, space='buy')

    # Reglas compra A–F
    h_a_ll10_mult        = DecimalParameter(1.002, 1.010, decimals=4, default=1.0055, space='buy')
    h_a_rsi_prev_max     = IntParameter(35, 55, default=48, space='buy')
    h_c_stoch_max        = IntParameter(20, 45, default=35, space='buy')
    h_d_pct1_max         = DecimalParameter(-2.5, -1.5, decimals=1, default=-1.8, space='buy')
    h_d_pct3_max         = DecimalParameter(-6.0, -3.0, decimals=1, default=-3.2, space='buy')
    h_d_bb_percent_max   = DecimalParameter(0.03, 0.10, decimals=3, default=0.080, space='buy')
    h_d_tail_atr_mult    = DecimalParameter(0.8, 1.5, decimals=2, default=0.95, space='buy')
    h_e_rsi_min          = IntParameter(40, 55, default=46, space='buy')
    h_e_ll10_mult        = DecimalParameter(1.004, 1.020, decimals=3, default=1.008, space='buy')
    h_e_bb_mid_mult      = DecimalParameter(0.990, 1.020, decimals=3, default=1.015, space='buy')
    h_f_bb_percent_max   = DecimalParameter(0.20, 0.45, decimals=2, default=0.38, space='buy')
    h_f_ll10_upper       = DecimalParameter(1.002, 1.012, decimals=3, default=1.006, space='buy')
    h_f_ll10_lower       = DecimalParameter(0.980, 0.996, decimals=3, default=0.985, space='buy')

    # Ventas por RSI y mechas
    h_reject_upper_atr   = DecimalParameter(0.8, 1.2, decimals=2, default=0.90, space='sell')
    h_reject_wick_ratio  = DecimalParameter(1.05, 1.40, decimals=2, default=1.10, space='sell')
    h_sell_rsi_peak      = IntParameter(60, 80, default=67, space='sell')
    h_sell_rsi_reject    = IntParameter(55, 70, default=60, space='sell')
    h_sell_rsi_hh_ema    = IntParameter(58, 70, default=60, space='sell')
    h_sell_rsi_wick      = IntParameter(58, 70, default=60, space='sell')

    # Crash-guard
    h_crash_fast_ema8    = DecimalParameter(0.985, 0.997, decimals=3, default=0.992, space='protection')
    h_crash_fast_pct1    = DecimalParameter(-1.5, -0.3, decimals=2, default=-0.6, space='protection')
    h_crash_atr_break    = DecimalParameter(1.2, 2.0, decimals=1, default=1.4, space='protection')
    h_crash_adx_min      = IntParameter(18, 32, default=20, space='protection')
    h_crash_rsi_max      = IntParameter(45, 58, default=55, space='protection')

    # Anti-chase (no perseguir picos)
    h_max_up_1           = DecimalParameter(0.3, 1.8, decimals=2, default=1.20, space='buy')
    h_max_up_3           = DecimalParameter(1.0, 5.0, decimals=2, default=3.50, space='buy')
    h_max_green_streak   = IntParameter(2, 6, default=4, space='buy')
    h_buy_below_ema20    = DecimalParameter(0.990, 1.010, decimals=3, default=1.000, space='buy')
    h_buy_below_bbmid    = DecimalParameter(0.990, 1.010, decimals=3, default=1.000, space='buy')
    h_bb_expanding_high  = DecimalParameter(0.45, 0.85, decimals=2, default=0.65, space='buy')
    h_pump_vol_mult      = DecimalParameter(1.4, 3.0, decimals=1, default=2.0, space='buy')
    h_near_hh_distance   = DecimalParameter(0.002, 0.020, decimals=4, default=0.0045, space='buy')
    h_require_red_pb     = BooleanParameter(default=False, space='buy')

    # ---------- SHIM de propiedades (tu lógica usa self.* como siempre) ----------
    # Backing para stoploss normalizado por StrategyResolver
    _stoploss_cache: Optional[float] = None


    # Take-profits
    @property
    def PEAK_MIN_PROFIT(self):    return float(self.h_peak_min_profit.value)
    @property
    def HH_EMA_MIN_PROFIT(self):  return float(self.h_hh_ema_min_profit.value)
    @property
    def HARD_TP(self):            return float(self.h_hard_tp.value)

    # Stop/Trailing
    @property
    def stoploss(self) -> float:
        # 1) Si existe el parámetro optimizable, úsalo
        try:
            return float(self.h_stoploss_abs.value)
        except Exception:
            pass
        # 2) Si StrategyResolver asignó algo (normalize_attributes), úsalo
        if self._stoploss_cache is not None:
            return float(self._stoploss_cache)
        # 3) Fallback razonable
        return -0.045

    @stoploss.setter
    def stoploss(self, value: float) -> None:
        # Freqtrade hace: strategy.stoploss = float(strategy.stoploss)
        try:
            self._stoploss_cache = float(value)
        except Exception:
            self._stoploss_cache = None


    @property
    def TRAIL_ATR_MULT_LOW(self):     return float(self.h_trail_atr_low.value)
    @property
    def TRAIL_ATR_MULT_HIGH(self):    return float(self.h_trail_atr_high.value)
    @property
    def TRAIL_DIST_MIN(self):         return float(self.h_trail_dist_min.value)
    @property
    def TRAIL_DIST_MAX(self):         return float(self.h_trail_dist_max.value)
    @property
    def TRAIL_VERTICAL_MIN(self):     return float(self.h_trail_vertical_min.value)
    @property
    def FALLBACK_TRAIL_DIST(self):    return float(self.h_fallback_trail.value)

    # Anti-cuchillo / filtros macro
    @property
    def PCT1_MIN(self):           return float(self.h_pct1_min.value)
    @property
    def PCT3_MIN(self):           return float(self.h_pct3_min.value)
    @property
    def COOLDOWN_BARS(self):      return int(self.h_cooldown_bars.value)

    # Filtro “arriba”
    @property
    def NO_BUY_BB_MULT(self):     return float(self.h_no_buy_bb_mult.value)
    @property
    def NO_BUY_EMA20_MULT(self):  return float(self.h_no_buy_ema20_mult.value)
    @property
    def NO_BUY_RSI_MIN(self):     return int(self.h_no_buy_rsi_min.value)

    # Zonas BB / martillos
    @property
    def DEEP_BB(self):                 return float(self.h_deep_bb.value)
    @property
    def BB_ZONE_OK(self):              return float(self.h_bb_zone_ok.value)
    @property
    def LOWER_WICK_BODY_RATIO(self):   return float(self.h_lower_wick_body.value)

    # Reglas A–F
    @property
    def A_LL10_MULT(self):        return float(self.h_a_ll10_mult.value)
    @property
    def A_RSI_PREV_MAX(self):     return int(self.h_a_rsi_prev_max.value)
    @property
    def C_STOCH_MAX(self):        return int(self.h_c_stoch_max.value)
    @property
    def D_PCT1_MAX(self):         return float(self.h_d_pct1_max.value)
    @property
    def D_PCT3_MAX(self):         return float(self.h_d_pct3_max.value)
    @property
    def D_BB_PERCENT_MAX(self):   return float(self.h_d_bb_percent_max.value)
    @property
    def D_TAIL_ATR_MULT(self):    return float(self.h_d_tail_atr_mult.value)
    @property
    def E_RSI_MIN(self):          return int(self.h_e_rsi_min.value)
    @property
    def E_LL10_MULT(self):        return float(self.h_e_ll10_mult.value)
    @property
    def E_BB_MID_MULT(self):      return float(self.h_e_bb_mid_mult.value)
    @property
    def F_BB_PERCENT_MAX(self):   return float(self.h_f_bb_percent_max.value)
    @property
    def F_LL10_UPPER(self):       return float(self.h_f_ll10_upper.value)
    @property
    def F_LL10_LOWER(self):       return float(self.h_f_ll10_lower.value)

    # Ventas (RSI/mechas)
    @property
    def REJECT_UPPER_ATR_MULT(self):   return float(self.h_reject_upper_atr.value)
    @property
    def REJECT_WICK_BODY_RATIO(self):  return float(self.h_reject_wick_ratio.value)
    @property
    def SELL_RSI_PEAK(self):           return int(self.h_sell_rsi_peak.value)
    @property
    def SELL_RSI_REJECT(self):         return int(self.h_sell_rsi_reject.value)
    @property
    def SELL_RSI_HH_EMA(self):         return int(self.h_sell_rsi_hh_ema.value)
    @property
    def SELL_RSI_WICK(self):           return int(self.h_sell_rsi_wick.value)

    # Crash-guard
    @property
    def CRASH_FAST_DROP_EMA8(self):    return float(self.h_crash_fast_ema8.value)
    @property
    def CRASH_FAST_DROP_PCT1(self):    return float(self.h_crash_fast_pct1.value)
    @property
    def CRASH_ATR_BREAK_MULT(self):    return float(self.h_crash_atr_break.value)
    @property
    def CRASH_ADX_MIN(self):           return int(self.h_crash_adx_min.value)
    @property
    def CRASH_RSI_MAX(self):           return int(self.h_crash_rsi_max.value)

    # Anti-chase
    @property
    def MAX_PCT_UP_1(self):            return float(self.h_max_up_1.value)
    @property
    def MAX_PCT_UP_3(self):            return float(self.h_max_up_3.value)
    @property
    def MAX_GREEN_STREAK(self):        return int(self.h_max_green_streak.value)
    @property
    def BUY_BELOW_EMA20_MULT(self):    return float(self.h_buy_below_ema20.value)
    @property
    def BUY_BELOW_BB_MID_MULT(self):   return float(self.h_buy_below_bbmid.value)
    @property
    def BB_EXPANDING_HIGH(self):       return float(self.h_bb_expanding_high.value)
    @property
    def PUMP_VOL_MULT(self):           return float(self.h_pump_vol_mult.value)
    @property
    def NEAR_HH_DISTANCE(self):        return float(self.h_near_hh_distance.value)
    @property
    def REQUIRE_RED_PULLBACK(self):    return bool(self.h_require_red_pb.value)

    # ==========================
    # -------- INDICADORES -------
    # ==========================
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # BinHV45 (BB40)
        mid, lower = bollinger_bands(
            dataframe['close'], window_size=40, num_of_std=2.2
        )
        dataframe['lower'] = lower
        dataframe['bbdelta'] = (mid - dataframe['lower']).abs()
        dataframe['closedelta'] = (dataframe['close'] - dataframe['close'].shift()).abs()
        dataframe['tail'] = (dataframe['close'] - dataframe['low']).abs()

        # Bollinger 20
        tp = qtpylib.typical_price(dataframe)
        bb = qtpylib.bollinger_bands(tp, window=20, stds=2.2)
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
        dataframe['ema8_slope_up'] = dataframe['ema8'] > dataframe['ema8'].shift(1)

        # Volumen
        dataframe['volume_mean_slow'] = dataframe['volume'].rolling(window=30).mean()
        dataframe['vol_mean_fast'] = dataframe['volume'].rolling(window=10).mean()

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
        dataframe['macd']       = macd['macd']
        dataframe['macdsignal'] = macd['macdsignal']
        dataframe['macdhist']   = macd['macdhist']

        # Momentum/extremos
        dataframe['roc5']  = ta.ROC(dataframe, timeperiod=5)
        dataframe['ll_8']  = dataframe['low'].rolling(8).min()
        dataframe['ll_10'] = dataframe['low'].rolling(10).min()
        dataframe['ll_20'] = dataframe['low'].rolling(20).min()
        dataframe['hh_20'] = dataframe['high'].rolling(20).max()

        # ATR y variaciones
        dataframe['atr']   = ta.ATR(dataframe, timeperiod=14)
        dataframe['pct_1'] = dataframe['close'].pct_change(1) * 100.0
        dataframe['pct_3'] = dataframe['close'].pct_change(3) * 100.0

        # Estructura / cooldown
        body = (dataframe['close'] - dataframe['open']).abs()
        dataframe['big_red']  = (dataframe['close'] < dataframe['open']) & (body > 1.2 * dataframe['atr'])
        dataframe['cooldown'] = dataframe['big_red'].rolling(self.COOLDOWN_BARS).max()

        # Mechas
        dataframe['upper_wick'] = (dataframe['high'] - np.maximum(dataframe['open'], dataframe['close'])).abs()
        dataframe['lower_wick'] = (np.minimum(dataframe['open'], dataframe['close']) - dataframe['low']).abs()

        # Volumen relativo / pump
        dataframe['vol_spike'] = dataframe['volume'] > (dataframe['volume_mean_slow'] * 1.15)
        dataframe['pump_vol']  = dataframe['volume'] > (dataframe['vol_mean_fast'] * self.PUMP_VOL_MULT)

        # Máximo/mínimo local recientes
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
            dataframe['green'].rolling(window=self.MAX_GREEN_STREAK, min_periods=1).sum()
        )
        dataframe['near_hh'] = dataframe['close'] >= (dataframe['hh_20'] * (1.0 - self.NEAR_HH_DISTANCE))

        return dataframe

    # ==========================
    # -------- COMPRAS ----------
    # ==========================
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

        # Anti-chase (evitar perseguir subidas)
        anti_chase = (
            (dataframe['pct_1'] < self.MAX_PCT_UP_1) &
            (dataframe['pct_3'] < self.MAX_PCT_UP_3) &
            (dataframe['green_streak'] < self.MAX_GREEN_STREAK) &
            (~((dataframe['bb_percent'] >= self.BB_EXPANDING_HIGH) & (dataframe['bb_expanding']))) &
            (~(dataframe['pump_vol'] & (dataframe['pct_1'] > 0.6))) &
            (dataframe['close'] <= dataframe['ema_fast'] * self.BUY_BELOW_EMA20_MULT) &
            (dataframe['close'] <= dataframe['bb_middleband'] * self.BUY_BELOW_BB_MID_MULT) &
            (~dataframe['near_hh'])
        )

        if self.REQUIRE_RED_PULLBACK:
            anti_chase = anti_chase & (
                (dataframe['close'] <= dataframe['open']) |
                (dataframe['low'] < dataframe['close'].shift(1))
            )

        # A) Mínimo local + giro RSI + martillo/volumen
        A = (
            (dataframe['loc_trough']) &
            ((dataframe['low'] <= dataframe['ll_10'] * self.A_LL10_MULT) | deep_bb) &
            (dataframe['rsi_prev'] < self.A_RSI_PREV_MAX) & (dataframe['rsi'] > dataframe['rsi_prev']) &
            (dataframe['close'] >= dataframe['open']) &
            (hammerish | dataframe['vol_spike'])
        )

        # B) Re-entrada tras cerrar fuera de banda inferior y volver dentro
        B = (
            (dataframe['close'].shift(1) < dataframe['bb_lowerband'].shift(1)) &
            (dataframe['close'] > dataframe['bb_lowerband']) &
            (dataframe['rsi'] > dataframe['rsi_prev']) &
            (bb_zone_ok)
        )

        # C) StochRSI cruce en sobreventa + MACD no empeora + zona baja BB
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

        # F) Doble toque / higher-low sutil en zona baja
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

    # ==========================
    # -------- VENTAS ----------
    # ==========================
    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
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

    # ==========================
    # -------- UTILIDADES -------
    # ==========================
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

    # ==========================
    # -------- EXITS ------------
    # ==========================
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
            if (current_profit is None) or (current_profit > MIN_PROFIT_NET):
                return "crash_guard"

        bars = self._bars_elapsed(trade, current_time)
        if bars < self.MIN_HOLD_BARS:
            if not self._strong_bearish_reversal(pair):
                return None

        # TP duro
        if current_profit is not None and current_profit >= self.HARD_TP:
            return "hard_tp"

        # Requiere beneficio neto
        if current_profit is None or current_profit < MIN_PROFIT_NET:
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
            if current_profit >= MIN_PROFIT_NET and near_upper and (upper_wick >= last['atr'] * self.REJECT_UPPER_ATR_MULT) and (upper_wick > self.REJECT_WICK_BODY_RATIO * body) and (last['rsi'] >= self.SELL_RSI_WICK):
                return "upper_wick_reject_exit"

            # Pérdida de momentum tras varias velas en verde
            if current_profit >= (MIN_PROFIT_NET + 0.002) and bars >= 6:
                if (last['rsi'] < last['rsi_prev']) and macd_fade and ema_break:
                    return "momentum_fade_exit"

        except Exception:
            pass

        return None

    # ==========================
    # -------- TRAILING ---------
    # ==========================
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
