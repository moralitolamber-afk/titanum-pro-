"""
⚡ TITANIUM v8.0 PRO — API Backend (FastAPI)
Desacopla el backend del frontend. Endpoints REST para:
- Datos de mercado en tiempo real
- Estado de señales activas
- Confluencia y scores
- Risk management status
- Historial de operaciones

Ejecutar: uvicorn api_server:app --host 0.0.0.0 --port 8000 --reload
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import asyncio
import time
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import config
from core.exchange import ExchangeManager
from core.indicators import calculate_all, get_trend_direction
from core.strategy import StrategyEngine
from core.ai_brain import AIBrain
from risk.circuit_breaker import CircuitBreaker
from risk.position_sizer import KellyPositionSizer
from utils.logger import log_signal


# ══════════════════════════════════════════════════════════
# PYDANTIC MODELS (contratos de la API)
# ══════════════════════════════════════════════════════════

class MarketData(BaseModel):
    price: float
    obi: float
    raw_obi: float
    bid_vol: float
    ask_vol: float
    spread: float
    bid_pct: float

class IndicatorData(BaseModel):
    adx: float
    rsi: float
    atr: float
    atr_pct: float
    macd_hist: float
    bb_pct: float
    vol_ratio: float
    trend_direction: str
    trend_strength: float
    rsi_divergence: str
    market_structure: str

class ConfluenceBreakdown(BaseModel):
    factor: str
    score: float
    max_score: float
    status: str  # 'pass', 'warn', 'fail'

class ConfluenceData(BaseModel):
    long_score: int
    short_score: int
    dominant: str  # 'LONG', 'SHORT', 'NEUTRAL'
    breakdown: List[ConfluenceBreakdown]

class SignalData(BaseModel):
    signal_id: str
    direction: str
    score: int
    entry: float
    stop_loss: float
    take_profit: float
    sl_distance: float
    tp_distance: float
    risk_reward: float
    atr: float
    trailing_phase: str
    age_seconds: float
    is_strong: bool
    status: str
    timestamp: str

class RiskStatus(BaseModel):
    can_trade: bool
    daily_pnl_pct: float
    total_pnl_pct: float
    consecutive_losses: int
    max_consecutive_losses: int
    total_trades: int
    win_rate: float
    kelly_pct: float
    pause_reason: Optional[str]

class AIStatus(BaseModel):
    panic_mode: bool
    reason: str
    score: int

class SessionInfo(BaseModel):
    active_sessions: List[str]
    session_boost: float
    timestamp: str
    timezone: str

class FullDashboard(BaseModel):
    market: MarketData
    indicators: IndicatorData
    confluence: ConfluenceData
    active_signal: Optional[SignalData]
    risk: RiskStatus
    ai: AIStatus
    session: SessionInfo
    history: List[SignalData]


# ══════════════════════════════════════════════════════════
# GLOBAL STATE (singleton engine)
# ══════════════════════════════════════════════════════════

class TitaniumEngine:
    def __init__(self):
        self.exchange = ExchangeManager()
        self.strategy = StrategyEngine()
        self.ai_brain = AIBrain()
        self.breaker = CircuitBreaker()
        self.sizer = KellyPositionSizer()
        self.active_signal = None
        self.tf_data = {}
        self.ob_data = {}
        self.last_update = 0
        self._initialized = False
        self._lock = asyncio.Lock()

    async def initialize(self):
        if not self._initialized:
            await self.exchange.connect()
            self._initialized = True

    async def update(self):
        """Fetch y analizar datos del mercado."""
        async with self._lock:
            now = time.time()
            if now - self.last_update < 1.5:  # Throttle
                return

            await self.initialize()

            self.tf_data = await self.exchange.fetch_all_timeframes()
            self.ob_data = await self.exchange.fetch_obi()

            for tf in self.tf_data:
                self.tf_data[tf] = calculate_all(self.tf_data[tf])

            self.last_update = now

    async def analyze(self):
        """Ejecutar análisis de confluencia."""
        await self.update()
        entry_df = self.tf_data.get(config.TF_ENTRY)
        if entry_df is None or len(entry_df) < config.EMA_SLOW:
            return 0, {}, 0, {}, None

        result = self.strategy.analyze(self.tf_data, self.ob_data)
        long_s, long_bd, short_s, short_bd, new_sig = result

        # Handle new signal
        ai = self.ai_brain.sentiment_state
        if new_sig and self.breaker.can_trade() and not ai.get('panic_mode', False):
            self.active_signal = new_sig

        # Check active signal
        if self.active_signal and entry_df is not None and len(entry_df) > 0:
            price = entry_df.iloc[-1]['close']
            closed = self.strategy.check_signal_status(self.active_signal, price)
            if closed:
                pnl = closed.calculate_pnl(price)
                self.breaker.record_trade(pnl)
                self.sizer.add_trade(pnl)
                from utils.logger import log_signal, log_portfolio_snapshot
                log_signal(closed)
                
                # Snapshot de riesgo tras el trade
                cb = self.breaker.get_status()
                ks = self.sizer.get_status()
                snap = {
                    'daily_pnl_pct': cb.get('daily_pnl_pct', 0),
                    'total_pnl_pct': cb.get('total_pnl_pct', 0),
                    'win_rate': cb.get('win_rate', 0),
                    'total_trades': cb.get('total_trades', 0),
                    'consecutive_losses': cb.get('consecutive_losses', 0),
                    'kelly_pct': ks.get('kelly_pct', 0)
                }
                log_portfolio_snapshot(snap)
                
                self.active_signal = None

        return long_s, long_bd, short_s, short_bd, new_sig


engine = TitaniumEngine()


# ══════════════════════════════════════════════════════════
# FASTAPI APP
# ══════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    await engine.initialize()
    yield
    await engine.exchange.close()

app = FastAPI(
    title="TITANIUM v8.0 PRO API",
    description="API REST para el bot de trading Titanium. "
                "Provee datos de mercado, señales, confluencia y risk management.",
    version="8.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8501",   # Streamlit dashboard
        "http://localhost:3000",   # React dev
        "http://127.0.0.1:8501",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["GET"],        # Solo lectura, no escritura
    allow_headers=["*"],
)


# ══════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════

def safe_val(row, col, default=0):
    import pandas as pd
    v = row.get(col, default)
    return default if pd.isna(v) else float(v)

def build_market(last, ob) -> MarketData:
    total = ob['bid_vol'] + ob['ask_vol']
    return MarketData(
        price=float(last['close']),
        obi=ob['obi'],
        raw_obi=ob['raw_obi'],
        bid_vol=ob['bid_vol'],
        ask_vol=ob['ask_vol'],
        spread=ob['spread'],
        bid_pct=ob['bid_vol'] / total * 100 if total > 0 else 50,
    )

def build_indicators(last, entry_df) -> IndicatorData:
    d, s = get_trend_direction(entry_df)
    return IndicatorData(
        adx=safe_val(last, 'ADX'),
        rsi=safe_val(last, 'RSI', 50),
        atr=safe_val(last, 'ATR'),
        atr_pct=safe_val(last, 'ATR_pct', 0),
        macd_hist=safe_val(last, 'MACD_hist'),
        bb_pct=safe_val(last, 'BB_pct', 0.5),
        vol_ratio=safe_val(last, 'vol_ratio', 1.0),
        trend_direction=d,
        trend_strength=s,
        rsi_divergence=str(last.get('rsi_divergence', 'NONE')),
        market_structure=str(last.get('market_structure', 'RANGING')),
    )

def build_confluence(long_s, long_bd, short_s, short_bd) -> ConfluenceData:
    bd = long_bd if long_s >= short_s else short_bd
    breakdown = []
    for k, (sc, mx) in (bd or {}).items():
        status = 'pass' if sc >= mx * 0.6 else ('warn' if sc > 0 else 'fail')
        breakdown.append(ConfluenceBreakdown(
            factor=k, score=sc, max_score=mx, status=status
        ))
    dominant = 'NEUTRAL'
    if long_s >= config.SCORE_MIN_ENTRY and long_s > short_s:
        dominant = 'LONG'
    elif short_s >= config.SCORE_MIN_ENTRY:
        dominant = 'SHORT'
    return ConfluenceData(
        long_score=long_s, short_score=short_s,
        dominant=dominant, breakdown=breakdown,
    )

def build_signal(sig) -> Optional[SignalData]:
    if sig is None:
        return None
    import pytz
    tz = pytz.timezone(config.MY_TIMEZONE)
    return SignalData(
        signal_id=sig.signal_id,
        direction=sig.direction,
        score=sig.score,
        entry=sig.entry,
        stop_loss=sig.stop_loss,
        take_profit=sig.take_profit,
        sl_distance=sig.sl_distance,
        tp_distance=sig.tp_distance,
        risk_reward=sig.risk_reward,
        atr=sig.atr,
        trailing_phase=getattr(sig, 'trailing_phase', 'INITIAL'),
        age_seconds=sig.age_seconds,
        is_strong=sig.is_strong,
        status=sig.status,
        timestamp=sig.timestamp.astimezone(tz).isoformat(),
    )

def build_risk() -> RiskStatus:
    cb = engine.breaker.get_status()
    ks = engine.sizer.get_status()
    return RiskStatus(
        can_trade=cb['can_trade'],
        daily_pnl_pct=cb['daily_pnl_pct'],
        total_pnl_pct=cb['total_pnl_pct'],
        consecutive_losses=cb['consecutive_losses'],
        max_consecutive_losses=config.MAX_CONSECUTIVE_LOSSES,
        total_trades=cb['total_trades'],
        win_rate=cb['win_rate'],
        kelly_pct=ks['kelly_pct'],
        pause_reason=cb.get('pause_reason'),
    )

def build_session() -> SessionInfo:
    import pytz
    h = datetime.now(pytz.utc).hour
    active = [s for s in config.SESSIONS.values() if s['start'] <= h < s['end']]
    names = [f"{s['emoji']} {s['name']}" for s in active] if active else ['🌙 OFF-HOURS']
    # Session boost
    boost = 1.0
    if 13 <= h < 16: boost = 1.15
    elif 7 <= h < 22: boost = 1.05
    else: boost = 0.95
    tz = pytz.timezone(config.MY_TIMEZONE)
    return SessionInfo(
        active_sessions=names,
        session_boost=boost,
        timestamp=datetime.now(tz).isoformat(),
        timezone=config.MY_TIMEZONE,
    )


# ══════════════════════════════════════════════════════════
# ENDPOINTS
# ══════════════════════════════════════════════════════════

@app.get("/api/dashboard", response_model=FullDashboard,
         summary="Dashboard completo",
         description="Retorna TODOS los datos del dashboard en una sola llamada.")
async def get_dashboard():
    long_s, long_bd, short_s, short_bd, _ = await engine.analyze()

    entry_df = engine.tf_data.get(config.TF_ENTRY)
    last = entry_df.iloc[-1] if entry_df is not None and len(entry_df) > 0 else None

    if last is None:
        raise Exception("No market data available")

    ai = engine.ai_brain.sentiment_state
    history = [build_signal(s) for s in list(engine.strategy.signal_history)[-10:]]

    return FullDashboard(
        market=build_market(last, engine.ob_data),
        indicators=build_indicators(last, entry_df),
        confluence=build_confluence(long_s, long_bd, short_s, short_bd),
        active_signal=build_signal(engine.active_signal),
        risk=build_risk(),
        ai=AIStatus(
            panic_mode=ai.get('panic_mode', False),
            reason=ai.get('reason', 'OK'),
            score=ai.get('score', 50),
        ),
        session=build_session(),
        history=[h for h in history if h],
    )


@app.get("/api/market", response_model=MarketData,
         summary="Datos de mercado",
         description="Precio, OBI, spread, volumen de bids/asks.")
async def get_market():
    await engine.update()
    entry_df = engine.tf_data.get(config.TF_ENTRY)
    last = entry_df.iloc[-1]
    return build_market(last, engine.ob_data)


@app.get("/api/indicators", response_model=IndicatorData,
         summary="Indicadores técnicos",
         description="ADX, RSI, ATR, MACD, BB%, tendencia, divergencias, estructura.")
async def get_indicators():
    await engine.update()
    entry_df = engine.tf_data.get(config.TF_ENTRY)
    last = entry_df.iloc[-1]
    return build_indicators(last, entry_df)


@app.get("/api/confluence", response_model=ConfluenceData,
         summary="Scores de confluencia",
         description="Puntaje LONG/SHORT con desglose de 8 factores.")
async def get_confluence():
    long_s, long_bd, short_s, short_bd, _ = await engine.analyze()
    return build_confluence(long_s, long_bd, short_s, short_bd)


@app.get("/api/signal", response_model=Optional[SignalData],
         summary="Señal activa",
         description="Señal de trading activa con entry/SL/TP y fase del trailing stop. Null si no hay señal.")
async def get_signal():
    await engine.analyze()
    return build_signal(engine.active_signal)


@app.get("/api/risk", response_model=RiskStatus,
         summary="Estado de riesgo",
         description="Circuit breaker, P&L, rachas, Kelly%, win rate.")
async def get_risk():
    return build_risk()


@app.get("/api/history", response_model=List[SignalData],
         summary="Historial de señales",
         description="Últimas 20 señales generadas con su estado (ACTIVE, HIT_TP, HIT_SL, EXPIRED).")
async def get_history():
    signals = [build_signal(s) for s in list(engine.strategy.signal_history)[-20:]]
    return [s for s in signals if s]


@app.get("/api/health",
         summary="Health check",
         description="Estado de salud del sistema.")
async def health():
    return {
        "status": "ok",
        "demo_mode": config.DEMO_MODE,
        "symbol": config.SYMBOL,
        "uptime_cycles": engine.last_update,
    }


@app.get("/api/backtest",
         summary="Ejecutar Backtesting",
         description="Corre un backtest de la estrategia sobre datos sintéticos. "
                     "Retorna métricas, Monte Carlo, y lista de trades.")
async def run_backtest(
    bars: int = 3000,
    score_threshold: int = 65,
    atr_tp_mult: float = 2.5,
    atr_sl_mult: float = 1.5,
):
    from backtest import TitaniumBacktester, MonteCarloSimulator, generate_test_data

    data = generate_test_data(bars)
    bt = TitaniumBacktester(initial_capital=10000)
    result = bt.run(data, score_threshold, atr_tp_mult, atr_sl_mult)

    mc = MonteCarloSimulator(500)
    mc_result = mc.analyze(result['returns'])

    return {
        "metrics": result['metrics'],
        "monte_carlo": mc_result,
        "trades_count": len(result['trades']),
        "last_trades": result['trades'][-10:],
        "params": result['params'],
    }
