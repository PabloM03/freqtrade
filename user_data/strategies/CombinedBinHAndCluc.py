# --- Cambios en populate_buy_trend ---
def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    anti_cuchillo = (
        (dataframe['pct_1'] > -1.2) &
        (dataframe['pct_3'] > -2.4) &
        (~dataframe['cooldown'].astype(bool)) &
        (~((dataframe['bb_percent'] < 0) & dataframe['bb_expanding'])) &
        (dataframe['minus_di'] <= dataframe['plus_di']) &
        (dataframe['volume'] > 0)
    )

    # Endurecido: Evitar compras “arriba” (más restrictivo)
    no_buy_high = (
        (dataframe['close'] > dataframe['bb_middleband'] * 1.01) &  # antes 1.02
        (dataframe['close'] > dataframe['ema_fast']) &
        (dataframe['rsi'] > 52) &  # antes 57
        (dataframe['bb_percent'] > 0.55)  # nuevo: si está en la mitad superior de la BB, no comprar
    )

    # Zonas de valor (más estrictas)
    deep_bb    = (dataframe['bb_percent'] <= 0.13)  # antes 0.20
    bb_zone_ok = (dataframe['bb_percent'] <= 0.22)  # antes 0.35

    lower_wick = dataframe['lower_wick']
    body       = (dataframe['close'] - dataframe['open']).abs()
    hammerish  = lower_wick > 1.15 * body

    # A) Mínimo local + giro RSI + martillo/volumen (más estricto)
    A = (
        (dataframe['loc_trough']) &
        ((dataframe['low'] <= dataframe['ll_10'] * 1.002) | deep_bb) &  # antes 1.004
        (dataframe['rsi_prev'] < 43) & (dataframe['rsi'] > dataframe['rsi_prev']) &  # antes 45
        (dataframe['close'] >= dataframe['open']) &
        (hammerish | dataframe['vol_spike'])
    )

    # B) Re-entrada tras cerrar fuera de banda inferior y volver dentro (más estricto)
    B = (
        (dataframe['close'].shift(1) < dataframe['bb_lowerband'].shift(1)) &
        (dataframe['close'] > dataframe['bb_lowerband']) &
        (dataframe['rsi'] > dataframe['rsi_prev']) &
        (deep_bb)  # antes bb_zone_ok
    )

    # C) StochRSI cruce en sobreventa + MACD no empeora + en zona baja BB (más estricto)
    C = (
        (dataframe['stoch_k_prev'] < dataframe['stoch_d_prev']) &
        (dataframe['stoch_k'] > dataframe['stoch_d']) &
        (dataframe['stoch_k'] < 25) & (dataframe['stoch_d'] < 25) &  # antes 35
        (dataframe['macdhist'] >= dataframe['macdhist'].shift(1)) &
        (deep_bb)
    )

    # D) Capitulación: vela muy roja previa / colas largas + rebote verde (igual)
    D = (
        ((dataframe['pct_1'] <= -1.8) | (dataframe['pct_3'] <= -3.5)) &
        (dataframe['bb_percent'] <= 0.03) &  # antes 0.05
        (dataframe['tail'] >= dataframe['atr'] * 1.0) &
        (dataframe['close'] >= dataframe['open'])
    )

    # E) Pullback controlado a EMA8 ascendente en zona media-baja (más estricto)
    E = (
        (dataframe['close'] > dataframe['ema8']) &
        (dataframe['close'].shift(1) <= dataframe['ema8'].shift(1)) &
        (dataframe['ema8_slope_up']) &
        (dataframe['rsi'] >= 45) & (dataframe['rsi'] > dataframe['rsi_prev']) &
        ((dataframe['low'] <= dataframe['ll_10'] * 1.005) | (dataframe['close'] <= dataframe['bb_middleband'] * 1.005) | deep_bb) &
        (dataframe['vol_spike'] | hammerish)
    )

    # F) Doble toque / higher-low sutil en zona baja (más estricto)
    F = (
        (deep_bb) &
        (dataframe['low'] <= dataframe['ll_10'] * 1.003) &  # antes 1.005
        (dataframe['low'] >= dataframe['ll_10'].shift(1) * 0.995) &  # antes 0.992
        (dataframe['rsi'] > dataframe['rsi_prev']) &
        (dataframe['close'] >= dataframe['open'])
    )

    dataframe.loc[
        (((A | B | C | D | E | F) & anti_cuchillo & ~no_buy_high) | D),
        'buy'
    ] = 1
    return dataframe

# --- Cambios en populate_sell_trend ---
def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    # Más estricto: solo vender en picos claros
    reject_upper = (
        (dataframe['upper_wick'] >= dataframe['atr'] * 1.1) &  # antes 0.9
        (dataframe['upper_wick'] > (dataframe['close'] - dataframe['open']).abs() * 1.5) &  # antes 1.2
        ((dataframe['high'] >= dataframe['bb_upperband'] * 0.9995) | (dataframe['close'] >= dataframe['bb_upperband'] * 0.9995)) &  # más cerca de la banda
        (dataframe['rsi'] >= 73)  # antes 60
    )

    dataframe.loc[
        (
            # Pico óptimo: máximo local + muy cerca banda sup + RSI muy alto + giro claro
            (dataframe['loc_peak']) &
            (dataframe['close'] >= dataframe['bb_upperband'] * 0.9995) &
            (dataframe['rsi'] >= 75) &  # antes 70
            (
                (dataframe['macdhist'] < dataframe['macdhist'].shift(1)) |
                (dataframe['close'] < dataframe['ema8']) |
                (dataframe['close'] < dataframe['open'])
            )
        )
        |
        (
            # Máximo del rango + ruptura EMA8 posterior con MACD debilitando (más estricto)
            (dataframe['high'].shift(1) >= dataframe['hh_20'].shift(1)) &
            (dataframe['close'].shift(1) >= dataframe['ema8'].shift(1)) &
            (dataframe['close'] < dataframe['ema8']) &
            (dataframe['rsi'] >= 73) &  # antes 62
            (dataframe['macdhist'] < dataframe['macdhist'].shift(1))
        )
        |
        reject_upper,
        'sell'
    ] = 1
    return dataframe
