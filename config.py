"""
⚡ TITANIUM v8.0 — Configuración Central
Todos los parámetros del bot en un solo lugar.
"""

# ── MODO ──────────────────────────────────────────────────
DEMO_MODE = True         # True = datos simulados (sin exchange)

# ── EXCHANGE ──────────────────────────────────────────────
SYMBOL = 'BTC/USDT'
USE_SPOT = True          # True = Binance Spot, False = Futures

# ── TIMEFRAMES (Multi-Timeframe Analysis) ─────────────────
TF_ENTRY   = '5m'    # Entrada
TF_CONFIRM = '15m'   # Confirmación
TF_TREND   = '1h'    # Tendencia macro
CANDLE_LIMIT = 100

# ── ORDER BOOK ────────────────────────────────────────────
ORDERBOOK_DEPTH = 20
OBI_SMOOTHING   = 5
OBI_THRESHOLD   = 0.20

# ── INDICADORES ───────────────────────────────────────────
ADX_THRESHOLD  = 20
ADX_STRONG     = 30
RSI_OVERBOUGHT = 70
RSI_OVERSOLD   = 30
EMA_FAST  = 20
EMA_MID   = 50
EMA_SLOW  = 200
BB_LENGTH = 20
BB_STD    = 2.0
MACD_FAST   = 12
MACD_SLOW   = 26
MACD_SIGNAL = 9
ATR_LENGTH  = 14

# ── CONFLUENCIA (pesos suman 100) ─────────────────────────
SCORE_MIN_ENTRY = 65
SCORE_STRONG    = 80
WEIGHTS = {
    'obi':           15,
    'adx_trend':     15,
    'rsi':           10,
    'ema_alignment': 15,
    'mtf_trend':     20,
    'macd':          10,
    'bb_position':   10,
    'volume':         5,
}

# ── RIESGO ────────────────────────────────────────────────
ATR_SL_MULTIPLIER = 1.5
ATR_TP_MULTIPLIER = 2.5

# ── CIRCUIT BREAKER ──────────────────────────────────────
MAX_DAILY_DRAWDOWN_PCT  = 5.0    # Máximo drawdown diario (%)
MAX_TOTAL_DRAWDOWN_PCT  = 15.0   # Máximo drawdown total (%)
MAX_CONSECUTIVE_LOSSES  = 5      # Pérdidas consecutivas antes de pausa
COOLDOWN_AFTER_LOSSES   = 60     # Minutos de pausa
EMERGENCY_STOP_PNL_PCT  = -20.0  # Parada de emergencia permanente (%)

# ── POSITION SIZER (Kelly Criterion) ────────────────────
KELLY_FRACTION      = 0.5    # Half-Kelly (conservador)
MAX_POSITION_PCT    = 0.25   # Nunca arriesgar más del 25%
MIN_POSITION_PCT    = 0.01   # Mínimo 1%
KELLY_LOOKBACK      = 50     # Trades históricos para Kelly

# ── TRAILING STOP DINÁMICO ──────────────────────────────
TRAILING_ATR_MULT       = 2.0    # Distancia inicial del trailing
TRAILING_TIGHTEN_RR     = 1.0    # Apretar trailing después de 1R
TRAILING_TIGHTEN_MULT   = 1.2    # Multiplicador apretado
TRAILING_BREAKEVEN_RR   = 0.5    # Breakeven después de 0.5R

# ── SEÑALES ───────────────────────────────────────────────
SIGNAL_COOLDOWN_SEC = 300
SIGNAL_EXPIRY_SEC   = 900

# ── SESIONES (horas UTC) ─────────────────────────────────
SESSIONS = {
    'asia':     {'start': 0,  'end': 8,  'emoji': '🏯', 'name': 'ASIA'},
    'london':   {'start': 7,  'end': 16, 'emoji': '🏰', 'name': 'LONDON'},
    'new_york': {'start': 13, 'end': 22, 'emoji': '🗽', 'name': 'NEW YORK'},
}

# ── DISPLAY ───────────────────────────────────────────────
UPDATE_INTERVAL = 2
MY_TIMEZONE     = 'America/Bogota'

# ── LOGGING ───────────────────────────────────────────────
LOG_SIGNALS = True
LOG_DIR     = 'logs'

# ── SECRETS (From Environment Variables) ──────────────────
import os
from dotenv import load_dotenv

# Cargar variables de entorno del archivo .env local si existe
load_dotenv()

GROQ_API_KEY    = os.getenv("GROQ_API_KEY")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET  = os.getenv("BINANCE_SECRET")

# Passkey por defecto en caso de no estar definida en el ambiente
ADMIN_PASSKEY   = os.getenv("ADMIN_PASSKEY", "protrading")

