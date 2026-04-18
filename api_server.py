from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import time
import pandas as pd
from typing import List, Dict

# Importar motores del bot
import config
from core.exchange import ExchangeManager
from core.strategy import StrategyEngine
from core.ai_brain import AIBrain
from risk.circuit_breaker import CircuitBreaker

app = FastAPI(title="TITANIUM PRO API - Next.js Bridge")

# Habilitar CORS para que el frontend en Vercel pueda hablar con este backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Singleton instances (en producción esto debería persistir en una BD o Redis)
manager = ExchangeManager()
strategy = StrategyEngine()
brain = AIBrain()
breaker = CircuitBreaker()

class BotStatus(BaseModel):
    symbol: str
    price: float
    obi: float
    panic_mode: bool
    ai_score: int
    daily_pnl: float
    can_trade: bool

@app.get("/")
def home():
    return {"status": "Titanium Engine Active", "version": "8.0 PRO"}

@app.get("/api/market-data")
def get_market_data():
    """Endpoint para que el Dashboard de Vercel/Next.js obtenga los datos."""
    try:
        # Nota: En modo serverless, esto debe ser muy rápido.
        tf_data = manager.fetch_all_timeframes()
        ob_data = manager.fetch_obi()
        
        # Último precio
        last_price = tf_data[config.TF_ENTRY]['close'].iloc[-1]
        
        return {
            "symbol": config.SYMBOL,
            "price": float(last_price),
            "obi": float(ob_data['obi']),
            "ai": brain.sentiment_state,
            "breaker": breaker.get_status()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/signals")
def get_signals():
    """Retorna el historial de señales."""
    return [sig.__dict__ for sig in list(strategy.signal_history)]

# Este archivo es el punto de entrada para Vercel Functions
# O para correrlo en Railway/GCP: uvicorn api_server:app --host 0.0.0.0 --port 8000
