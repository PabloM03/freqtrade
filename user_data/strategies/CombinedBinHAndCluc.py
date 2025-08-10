# --- Do not remove these libs ---
import freqtrade.vendor.qtpylib.indicators as qtpylib
import numpy as np
# --------------------------------
import talib.abstract as ta
from freqtrade.strategy.interface import IStrategy
from pandas import DataFrame
from datetime import datetime
from typing import Optional
from freqtrade.persistence import Trade


def bollinger_bands(stock_price, window_size, num_of_std):
    rolling_mean = stock_price.rolling(window=window_size).mean()
    rolling_std = stock_price.rolling(window=window_size).std()
    lower_band = rolling_mean - (rolling_std * num_of_std)
    return np.nan_to_num(rolling_mean), np.nan_to_num(lower_band)


class CombinedBinHAndCluc(IStrategy):
    """
    Estrategia combinada con:
    - Compras por BinHV45, Cluc y RSI sobreventa.
    - Ventas más agresivas en picos claros.
    - Trailing Stop sensible para capturar ganancias.
    """

    minimal_roi = {"0": 0.0}
    stoploss = -0.05
    timeframe = '5m'
    startup_candle_count = 50

    use_sell_signal = True
    sell_profit_only = True
    ignore_roi_if_buy_signal = False

    # Trailing Stop más sensible
    trailing_stop = True
    trailing_stop_positive = 0.018          # 1.8% por debajo del máximo
    trailing_stop_positive_offset = 0.04    # se activa a partir de +4% de beneficio
    trailing_only_offset_is_reached = True

    # Retención mínima de velas
    MIN_HOLD_BARS = 4

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # --- BinHV45 ---
        mid, lower = bollinger_bands(dataframe['close'], window_size=40, num_of_std=2)
        dataframe['lower'] = lower
        dataframe['bbdelta'] = (mid - dataframe['lower']).abs()
        dataframe['closedelta'] = (dataframe['close'] - dataframe['close'].shift()).abs()
        dataframe['tail'] = (dataframe['close'] - dataframe['low']).abs()

        # --- Cluc ---
        bollinger = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2)
        dataframe['bb_lowerband'] = bollinger['lower']
        dataframe['bb_middleband'] = bollinger['mid']
        dataframe['bb_upperband'] = bollinger['upper']

        # Medias, RSI y fuerza direccional
        dataframe['ema_slow'] = ta.EMA(dataframe, timeperiod=50)
        dataframe['ema_fast'] = ta.EMA(dataframe, timeperiod=20)
        dataframe['volume_mean_slow'] = dataframe['volume'].rolling(window=30).mean()
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['rsi_prev'] = dataframe['rsi'].shift(1)
        dataframe['adx'] = ta.ADX(dataframe, timeperiod=14)
        dataframe['plus_di'] = ta.PLUS_DI(dataframe, timeperiod=14)
        dataframe['minus_di'] = ta.MINUS_DI(dataframe, timeperiod=14)

        return dataframe

    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                # BinHV45
                dataframe['lower'].shift().gt(0) &
                dataframe['bbdelta'].gt(dataframe['close'] * 0.0033) &
                dataframe['closedelta'].gt(dataframe['close'] * 0.009) &
                dataframe['tail'].lt(dataframe['bbdelta'] * 0.36) &
                dataframe['close'].lt(dataframe['lower'].shift()) &
                dataframe['close'].le(dataframe['close'].shift())
            )
            |
            (
                # Cluc
                (dataframe['close'] < dataframe['ema_slow']) &
                (dataframe['close'] < 0.9985 * dataframe['bb_lowerband']) &
                (dataframe['volume'] > 0) &
                (dataframe['volume'] < (dataframe['volume_mean_slow'].shift(1) * 5.5))
            )
            |
            (
                # RSI sobreventa
                (dataframe['rsi'] < 34) &
                (dataframe['close'] < dataframe['ema_slow']) &
                (dataframe['close'] < 1.012 * dataframe['bb_lowerband']) &
                (dataframe['volume'] > 0)
            ),
            'buy'
        ] = 1
        return dataframe

    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                # Cruce sobre la banda media con fuerza
                (dataframe['close'] > dataframe['bb_middleband']) &
                (dataframe['close'].shift(1) <= dataframe['bb_middleband'].shift(1)) &
                (dataframe['rsi'] > 58) &
                (dataframe['volume'] > dataframe['volume_mean_slow'])
            )
            |
            (
                # Sobrecompra fuerte y giro
                (dataframe['rsi_prev'] >= 75) & (dataframe['rsi'] < 75)
            )
            |
            (
                # Pérdida de momentum (EMA20)
                (dataframe['close'] < dataframe['ema_fast']) &
                (dataframe['close'].shift(1) >= dataframe['ema_fast'].shift(1)) &
                (dataframe['rsi'] > 52)
            ),
            'sell'
        ] = 1
        return dataframe

    def _bars_elapsed(self, trade: Trade, current_time: datetime) -> int:
        tf_minutes = int(self.timeframe.rstrip('m'))
        seconds = (current_time - trade.open_date_utc).total_seconds()
        return int(max(0, seconds) // (tf_minutes * 60))

    def _strong_bearish_reversal(self, pair: str) -> bool:
        try:
            df = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
            last = df.iloc[-1]
            return (last['minus_di'] > last['plus_di']) and (last['adx'] > 20) and (last['rsi'] < 55)
        except Exception:
            return False

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs
    ) -> Optional[str]:
        if current_rate < trade.open_rate:
            return None

        # Retención mínima salvo giro fuerte
        if self._bars_elapsed(trade, current_time) < self.MIN_HOLD_BARS:
            if not self._strong_bearish_reversal(pair):
                return None

        # TP discreto moderado
        if current_profit is not None and current_profit >= 0.012:
            return "tp_1_2_percent"

        return None

    # ---------- PROTECCIONES (añadido) ----------
    def protections(self):
        """
        Activa protecciones sin tocar el config.json:
        - Cooldown: pausa tras una operación en el par (evita 'ametralladoras').
        - StoplossGuard: si encadenas SL en un par, pausa temporalmente ese par.
        - PumpDumpProtection: evita operar durante pumps/dumps bruscos.
        Los tiempos están en velas (5m en tu caso).
        """
        return [
            {
                "method": "CooldownPeriod",
                "stop_duration_candles": 6          # 30 min en 5m
            },
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 24,      # últimas 2h
                "trade_limit": 1,                   # 1 SL en ventana
                "stop_duration_candles": 12,        # pausa 1h
                "only_per_pair": True
            },
            {
                "method": "PumpDumpProtection",
                "lookback_period_candles": 24,      # 2h
                "max_change_percent": 20,           # ±20% en ventana
                "trade_limit": 1,
                "stop_duration_candles": 12         # pausa 1h
            }
        ]