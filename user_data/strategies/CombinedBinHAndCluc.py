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
    - Compras: sobreventa + confirmación de giro (rebote desde mínimos).
    - Ventas: dejar correr la subida y salir si cae X% desde el pico reciente.
    - Trailing stop sensible como red de seguridad.
    """

    minimal_roi = {"0": 0.0}
    stoploss = -0.05
    timeframe = '5m'
    startup_candle_count = 50

    use_sell_signal = True
    sell_profit_only = True
    ignore_roi_if_buy_signal = False

    # Trailing como red, no como gatillo principal
    trailing_stop = True
    trailing_stop_positive = 0.02           # 2% por debajo del máximo
    trailing_stop_positive_offset = 0.05    # se activa a partir de +5%
    trailing_only_offset_is_reached = True

    # Parámetros de lógica “aguantar subida”
    MIN_HOLD_BARS = 4            # velas mínimas en posición
    PEAK_MODE_START = 0.045      # activar modo “pico” si profit >= 4.5%
    PEAK_GIVEBACK = 0.022        # cerrar si cae 2.2% desde el máximo alcanzado

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Memoria en runtime (se pierde al reiniciar, suficiente para dry-run en vivo)
        self._peak_by_trade = {}

    def _bars_elapsed(self, trade: Trade, current_time: datetime) -> int:
        tf_minutes = int(self.timeframe.rstrip('m'))
        seconds = (current_time - trade.open_date_utc).total_seconds()
        return int(max(0, seconds) // (tf_minutes * 60))

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # --- BinHV45 base ---
        mid, lower = bollinger_bands(dataframe['close'], window_size=40, num_of_std=2)
        dataframe['lower'] = lower
        dataframe['bbdelta'] = (mid - dataframe['lower']).abs()
        dataframe['closedelta'] = (dataframe['close'] - dataframe['close'].shift()).abs()
        dataframe['tail'] = (dataframe['close'] - dataframe['low']).abs()

        # --- Bollinger completo (Cluc) ---
        bb = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2)
        dataframe['bb_lowerband'] = bb['lower']
        dataframe['bb_middleband'] = bb['mid']
        dataframe['bb_upperband'] = bb['upper']

        # Medias / RSI / ATR
        dataframe['ema_slow'] = ta.EMA(dataframe, timeperiod=50)
        dataframe['ema_fast'] = ta.EMA(dataframe, timeperiod=20)
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['rsi_prev'] = dataframe['rsi'].shift(1)
        dataframe['atr'] = ta.ATR(dataframe, timeperiod=14)

        # Mínimo de las últimas N velas para confirmar rebote
        dataframe['ll20'] = dataframe['low'].rolling(20).min()

        return dataframe

    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Compra sólo cuando hay sobreventa + rebote confirmado:
        - Precio bajo (BB baja / bajo EMA50 / RSI<34)
        - Y rebota al menos +1% desde el mínimo de 20 velas con RSI girando al alza.
        """
        dataframe.loc[
            (
                # Zona de sobreventa
                (dataframe['close'] < dataframe['ema_slow']) &
                (dataframe['close'] <= dataframe['bb_lowerband'] * 1.01) &
                (dataframe['rsi'] < 34) &
                (dataframe['volume'] > 0)
            )
            &
            (
                # Confirmación de giro
                (dataframe['close'] >= dataframe['ll20'] * 1.01) &      # +1% desde el mínimo reciente
                (dataframe['rsi'] > dataframe['rsi_prev']) &            # RSI empieza a subir
                (dataframe['close'] > dataframe['close'].shift(1))      # vela verde respecto a la anterior
            ),
            'buy'
        ] = 1

        # Entrada “clásica” moderada (ligeramente más conservadora que antes)
        dataframe.loc[
            (
                dataframe['lower'].shift().gt(0) &
                dataframe['bbdelta'].gt(dataframe['close'] * 0.0035) &
                dataframe['closedelta'].gt(dataframe['close'] * 0.010) &
                dataframe['tail'].lt(dataframe['bbdelta'] * 0.35) &
                dataframe['close'].lt(dataframe['lower'].shift()) &
                dataframe['close'].le(dataframe['close'].shift())
            ) |
            (
                (dataframe['close'] < dataframe['ema_slow']) &
                (dataframe['close'] < 0.997 * dataframe['bb_lowerband']) &
                (dataframe['volume'] > 0) &
                (dataframe['volume'] < (dataframe['atr'] * 1e9))  # placeholder para no limitar demasiado por volumen
            ),
            'buy'
        ] = 1

        return dataframe

    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Señales técnicas “ligeras”. El cierre principal lo decide custom_exit con pico/drawdown.
        """
        dataframe.loc[
            (
                # Cruce sobre banda media con algo de fuerza
                (dataframe['close'] > dataframe['bb_middleband']) &
                (dataframe['close'].shift(1) <= dataframe['bb_middleband'].shift(1)) &
                (dataframe['rsi'] > 60)
            )
            |
            (
                # Sobrecompra que empieza a ceder
                (dataframe['rsi_prev'] >= 75) & (dataframe['rsi'] < 75)
            )
            |
            (
                # Pérdida de momentum vs EMA20
                (dataframe['close'] < dataframe['ema_fast']) &
                (dataframe['close'].shift(1) >= dataframe['ema_fast'].shift(1)) &
                (dataframe['rsi'] > 52)
            ),
            'sell'
        ] = 1
        return dataframe

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs
    ) -> Optional[str]:
        """
        - No vender por debajo del precio de compra (dejamos actuar al stoploss si toca).
        - Si el trade ya va bien (+4.5%), activa modo “pico”:
          memoriza el máximo y cierra si retrocede ~2.2% desde ese máximo
          (tras al menos MIN_HOLD_BARS velas).
        """
        # 1) No forzar ventas por debajo del open (evita “break-even” demasiado pronto)
        if current_rate < trade.open_rate:
            return None

        # 2) Espera mínima salvo que el trailing de sistema te saque
        if self._bars_elapsed(trade, current_time) < self.MIN_HOLD_BARS:
            return None

        # 3) Modo “pico” para subidas fuertes
        if current_profit is not None and current_profit >= self.PEAK_MODE_START:
            peak = self._peak_by_trade.get(trade.id, trade.open_rate)
            if current_rate > peak:
                peak = current_rate
            self._peak_by_trade[trade.id] = peak

            # Si cae X% desde el pico → cerrar
            if current_rate <= peak * (1.0 - self.PEAK_GIVEBACK):
                return "peak_drawdown_exit"

        # 4) Si no aplica nada, dejamos que actúe trailing/ROI/señales de sell
        return None