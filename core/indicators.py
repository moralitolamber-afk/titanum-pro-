"""
Cálculo de indicadores técnicos y análisis de estructura de mercado.
Funciones puras que reciben un DataFrame y devuelven resultados.

FASE 2: Incluye divergencias RSI y detección de estructura (HH/HL/LH/LL).
"""
import pandas as pd
import numpy as np
import pandas_ta as ta
import config


def calculate_all(df):
    """Calcular todos los indicadores técnicos sobre el DataFrame."""
    if df is None or len(df) < config.EMA_SLOW:
        return df

    h, l, c = df['high'], df['low'], df['close']

    # ── ADX + Directional ──
    adx_df = ta.adx(h, l, c, length=14)
    df['ADX']  = adx_df['ADX_14']
    df['DI+']  = adx_df['DMP_14']
    df['DI-']  = adx_df['DMN_14']

    # ── RSI ──
    df['RSI'] = ta.rsi(c, length=14)

    # ── EMAs (Ribbon) ──
    df['EMA_FAST'] = ta.ema(c, length=config.EMA_FAST)
    df['EMA_MID']  = ta.ema(c, length=config.EMA_MID)
    df['EMA_SLOW'] = ta.ema(c, length=config.EMA_SLOW)

    # ── MACD ──
    mf, ms, mg = config.MACD_FAST, config.MACD_SLOW, config.MACD_SIGNAL
    macd_df = ta.macd(c, fast=mf, slow=ms, signal=mg)
    df['MACD']        = macd_df[f'MACD_{mf}_{ms}_{mg}']
    df['MACD_signal'] = macd_df[f'MACDs_{mf}_{ms}_{mg}']
    df['MACD_hist']   = macd_df[f'MACDh_{mf}_{ms}_{mg}']

    # ── Bollinger Bands ──
    bl, bs = config.BB_LENGTH, config.BB_STD
    bb_df = ta.bbands(c, length=bl, std=bs)
    bb_cols = bb_df.columns.tolist()
    df['BB_upper'] = bb_df[[x for x in bb_cols if x.startswith('BBU_')][0]]
    df['BB_mid']   = bb_df[[x for x in bb_cols if x.startswith('BBM_')][0]]
    df['BB_lower'] = bb_df[[x for x in bb_cols if x.startswith('BBL_')][0]]
    bb_range = df['BB_upper'] - df['BB_lower']
    df['BB_pct'] = ((c - df['BB_lower']) / bb_range).where(bb_range > 0, 0.5)

    # ── ATR ──
    df['ATR'] = ta.atr(h, l, c, length=config.ATR_LENGTH)

    # ── ATR porcentual (para filtro de volatilidad) ──
    df['ATR_pct'] = (df['ATR'] / c * 100).fillna(0)

    # ── Volumen relativo ──
    df['vol_sma']   = df['volume'].rolling(20).mean()
    df['vol_ratio'] = (df['volume'] / df['vol_sma']).fillna(1.0)

    # ── Divergencias RSI ──
    df['rsi_divergence'] = detect_rsi_divergence(df)

    # ── Estructura de Mercado (HH/HL/LH/LL) ──
    df['market_structure'] = detect_market_structure(df)

    return df


def detect_rsi_divergence(df, lookback=10):
    """
    Detecta divergencias RSI:
    - Divergencia BEARISH: Precio hace Higher High, RSI hace Lower High → debilidad
    - Divergencia BULLISH: Precio hace Lower Low, RSI hace Higher Low → fortaleza oculta
    Returns: Series con valores 'BULL_DIV', 'BEAR_DIV', o 'NONE'
    """
    result = pd.Series('NONE', index=df.index)

    if len(df) < lookback + 5 or 'RSI' not in df.columns:
        return result

    price = df['close'].values
    rsi = df['RSI'].values

    for i in range(lookback, len(df)):
        p_window = price[i - lookback:i + 1]
        r_window = rsi[i - lookback:i + 1]

        if np.any(np.isnan(r_window)):
            continue

        # Divergencia Bearish: precio sube, RSI baja
        if p_window[-1] > np.max(p_window[:-1]) * 0.999:
            if r_window[-1] < np.max(r_window[:-1]) * 0.98:
                result.iloc[i] = 'BEAR_DIV'

        # Divergencia Bullish: precio baja, RSI sube
        if p_window[-1] < np.min(p_window[:-1]) * 1.001:
            if r_window[-1] > np.min(r_window[:-1]) * 1.02:
                result.iloc[i] = 'BULL_DIV'

    return result


def detect_market_structure(df, swing_lookback=5):
    """
    Detecta estructura Higher Highs / Higher Lows / Lower Highs / Lower Lows.
    Returns: Series con 'BULLISH_STRUCT', 'BEARISH_STRUCT', o 'RANGING'
    """
    result = pd.Series('RANGING', index=df.index)

    if len(df) < swing_lookback * 4:
        return result

    highs = df['high'].values
    lows = df['low'].values

    for i in range(swing_lookback * 3, len(df)):
        recent_highs = []
        recent_lows = []

        # Encontrar los últimos 2 swing highs y swing lows
        for j in range(i - swing_lookback * 3, i + 1, swing_lookback):
            window_end = min(j + swing_lookback, len(df))
            h_window = highs[j:window_end]
            l_window = lows[j:window_end]
            if len(h_window) > 0:
                recent_highs.append(np.max(h_window))
                recent_lows.append(np.min(l_window))

        if len(recent_highs) >= 2 and len(recent_lows) >= 2:
            hh = recent_highs[-1] > recent_highs[-2]  # Higher High
            hl = recent_lows[-1] > recent_lows[-2]     # Higher Low
            lh = recent_highs[-1] < recent_highs[-2]   # Lower High
            ll = recent_lows[-1] < recent_lows[-2]     # Lower Low

            if hh and hl:
                result.iloc[i] = 'BULLISH_STRUCT'
            elif lh and ll:
                result.iloc[i] = 'BEARISH_STRUCT'

    return result


def get_trend_direction(df):
    """Determinar dirección de tendencia desde EMA ribbon.
    Returns: (direction: str, strength: float 0-1)
    """
    if df is None or len(df) < config.EMA_SLOW:
        return 'NEUTRAL', 0.0

    last = df.iloc[-1]
    price = last['close']
    efast = last.get('EMA_FAST', price)
    emid  = last.get('EMA_MID', price)
    eslow = last.get('EMA_SLOW', price)

    if pd.isna(efast) or pd.isna(emid) or pd.isna(eslow):
        return 'NEUTRAL', 0.0

    # Alcista completo: precio > FAST > MID > SLOW
    if price > efast > emid > eslow:
        return 'BULLISH', 1.0
    if price > emid > eslow:
        return 'BULLISH', 0.7
    if price > eslow:
        return 'BULLISH', 0.4

    # Bajista completo: precio < FAST < MID < SLOW
    if price < efast < emid < eslow:
        return 'BEARISH', 1.0
    if price < emid < eslow:
        return 'BEARISH', 0.7
    if price < eslow:
        return 'BEARISH', 0.4

    return 'NEUTRAL', 0.0

def get_macro_trend_direction(df):
    """Detecta tendencia Macro usando cruce de precio estructurado (ej: EMA50 y EMA200)."""
    if df is None or len(df) < config.EMA_SLOW:
        return 'RANGING'
        
    last = df.iloc[-1]
    price = last['close']
    
    # Se usa MID (50) y SLOW (200) para macro tendencia tal como el módulo standalone
    emid = last.get('EMA_MID', price)
    eslow = last.get('EMA_SLOW', price)
    
    if pd.isna(emid) or pd.isna(eslow):
        return 'RANGING'
        
    if price > emid > eslow:
        return 'MACRO_ALCISTA'
    elif price < emid < eslow:
        return 'MACRO_BAJISTA'
    
    return 'RANGING'
