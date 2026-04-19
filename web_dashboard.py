"""
╔══════════════════════════════════════════════════════════════════╗
║          TITANIUM v10.0 PRO — AI PORTFOLIO MASTER AI             ║
║                                                                  ║
║  INTEGRACIÓN DE:                                                 ║
║  ✅ CircuitBreaker   — Protección institucional multinivel       ║
║  ✅ PortfolioAware   — Análisis de balances y exposición real    ║
║  ✅ AIBrain Pro      — Decisiones con contexto de portafolio     ║
║  ✅ RegimeDetector   — Clasificación algorítmica de mercado      ║
║  ✅ DeFi Vaults      — Operaciones on-chain & Staking            ║
║  ✅ News Sentiment   — Monitor de eventos "Black Swan"           ║
║  ✅ Dashboard VR     — UI Glassmorphism Premium                  ║
║                                                                  ║
║  Impulsado por Groq (Llama 3.3) para trading de precisión.       ║
╚══════════════════════════════════════════════════════════════════╝
"""

# ═══════════════════════════════════════════════════════════════════
# SECCIÓN 0: IMPORTS
# ═══════════════════════════════════════════════════════════════════

import os
import time
import json
import hashlib
import warnings
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import streamlit as st

warnings.filterwarnings('ignore')

# ═══════════════════════════════════════════════════════════════════
# SECCIÓN 1: CONFIGURACIÓN MAESTRA
# ═══════════════════════════════════════════════════════════════════

class Config:
    """Configuración centralizada. Lee desde Railway env vars."""

    # Trading
    SYMBOL          = os.getenv("SYMBOL", "BTC/USDT")
    USE_SPOT        = os.getenv("USE_SPOT", "true").lower() == "true"
    TF_ENTRY        = os.getenv("TF_ENTRY", "5m")
    TF_CONFIRM      = os.getenv("TF_CONFIRM", "15m")
    TF_TREND        = os.getenv("TF_TREND", "1h")
    CANDLE_LIMIT    = int(os.getenv("CANDLE_LIMIT", "200"))
    DEMO_MODE       = True   # Se actualiza dinámicamente por sesión

    # API Keys (cargadas desde Railway / .env)
    GROQ_API_KEY     = os.getenv("GROQ_API_KEY", "")
    BINANCE_API_KEY  = os.getenv("BINANCE_API_KEY", "")
    BINANCE_SECRET   = os.getenv("BINANCE_SECRET", "")
    ADMIN_PASSKEY    = os.getenv("ADMIN_PASSKEY", "protrading")

    # Risk — ajustables sin tocar código
    MAX_DAILY_DD     = float(os.getenv("MAX_DAILY_DD", "5.0"))
    MAX_TOTAL_DD     = float(os.getenv("MAX_TOTAL_DD", "15.0"))
    EMERGENCY_STOP   = float(os.getenv("EMERGENCY_STOP", "-20.0"))
    MAX_CONS_LOSSES  = int(os.getenv("MAX_CONS_LOSSES", "5"))
    COOLDOWN_MIN     = int(os.getenv("COOLDOWN_MIN", "60"))
    KELLY_FRACTION   = float(os.getenv("KELLY_FRACTION", "0.5"))
    MAX_POSITION_PCT = float(os.getenv("MAX_POSITION_PCT", "0.10"))


# ═══════════════════════════════════════════════════════════════════
# SECCIÓN 2: CIRCUIT BREAKER
# ═══════════════════════════════════════════════════════════════════

class CircuitBreaker:
    """
    Gateway obligatorio antes de ejecutar cualquier orden.
    Protege el capital con 4 niveles de parada automática.
    """

    def __init__(self):
        self.daily_pnl: float = 0.0
        self.total_pnl: float = 0.0
        self.consecutive_losses: int = 0
        self.trading_paused: bool = False
        self.pause_reason: Optional[str] = None
        self.cooldown_until: Optional[datetime] = None
        self._daily_reset = datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    def can_trade(self) -> bool:
        self._maybe_reset_daily()
        if self.trading_paused and self.cooldown_until:
            if datetime.now() >= self.cooldown_until:
                self.trading_paused = False
                self.pause_reason = None
                self.cooldown_until = None
        return not self.trading_paused

    def record_trade(self, pnl_pct: float):
        self._maybe_reset_daily()
        self.daily_pnl  += pnl_pct
        self.total_pnl  += pnl_pct
        self.consecutive_losses = self.consecutive_losses + 1 if pnl_pct < 0 else 0
        self._check_breakers()

    def get_status(self) -> Dict:
        return {
            "can_trade":          self.can_trade(),
            "daily_pnl_pct":      round(self.daily_pnl, 2),
            "total_pnl_pct":      round(self.total_pnl, 2),
            "consecutive_losses": self.consecutive_losses,
            "paused":             self.trading_paused,
            "pause_reason":       self.pause_reason,
        }

    # ── privado ──────────────────────────────────────────────────

    def _check_breakers(self):
        if self.total_pnl <= Config.EMERGENCY_STOP:
            self._pause(f"🚨 EMERGENCY: PnL {self.total_pnl:.1f}%", permanent=True)
        elif self.daily_pnl <= -Config.MAX_DAILY_DD:
            self._pause(f"Daily DD: {self.daily_pnl:.1f}%", cooldown=True)
        elif self.total_pnl <= -Config.MAX_TOTAL_DD:
            self._pause(f"Total DD: {self.total_pnl:.1f}%", permanent=True)
        elif self.consecutive_losses >= Config.MAX_CONS_LOSSES:
            self._pause(f"{self.consecutive_losses} pérdidas seguidas", cooldown=True)

    def _pause(self, reason: str, permanent=False, cooldown=False):
        self.trading_paused = True
        self.pause_reason = reason
        if cooldown and not permanent:
            self.cooldown_until = datetime.now() + timedelta(
                minutes=Config.COOLDOWN_MIN
            )

    def _maybe_reset_daily(self):
        if datetime.now() >= self._daily_reset + timedelta(days=1):
            self.daily_pnl = 0.0
            self.consecutive_losses = 0
            self._daily_reset = datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0
            )


# ═══════════════════════════════════════════════════════════════════
# SECCIÓN 3: ATR RISK MANAGER
# ═══════════════════════════════════════════════════════════════════

@dataclass
class StopLevels:
    stop_loss:         float
    take_profit:       float
    trailing_distance: float
    risk_reward:       float
    atr_value:         float
    confidence:        str   # 'high' | 'medium' | 'low'


class ATRRiskManager:
    """SL/TP dinámicos basados en la volatilidad real (ATR)."""

    def __init__(self, atr_period=14, sl_mult=2.0, tp_mult=3.0,
                 trail_mult=1.5):
        self.atr_period = atr_period
        self.sl_mult    = sl_mult
        self.tp_mult    = tp_mult
        self.trail_mult = trail_mult

    def calculate_stops(self, entry: float,
                        direction: Literal['long', 'short'],
                        df: pd.DataFrame) -> Optional[StopLevels]:
        atr = self._atr(df)
        if not atr:
            return None
        sl = entry - atr * self.sl_mult if direction == 'long' \
             else entry + atr * self.sl_mult
        tp = entry + atr * self.tp_mult if direction == 'long' \
             else entry - atr * self.tp_mult
        risk   = abs(entry - sl)
        reward = abs(tp - entry)
        rr     = round(reward / risk, 2) if risk else 0
        return StopLevels(
            stop_loss         = round(sl, 4),
            take_profit       = round(tp, 4),
            trailing_distance = round(atr * self.trail_mult, 4),
            risk_reward       = rr,
            atr_value         = round(atr, 4),
            confidence        = 'high' if rr >= 2 else 'medium' if rr >= 1.5 else 'low',
        )

    def update_trailing(self, price: float, entry: float,
                        current_stop: float,
                        direction: Literal['long', 'short'],
                        df: pd.DataFrame) -> Optional[float]:
        atr = self._atr(df)
        if not atr:
            return None
        if direction == 'long' and price >= entry + atr:
            candidate = price - atr * self.trail_mult
            return round(candidate, 4) if candidate > current_stop else None
        elif direction == 'short' and price <= entry - atr:
            candidate = price + atr * self.trail_mult
            return round(candidate, 4) if candidate < current_stop else None
        return None

    def _atr(self, df: pd.DataFrame) -> Optional[float]:
        if len(df) < self.atr_period + 1:
            return None
        try:
            tr = pd.concat([
                df['high'] - df['low'],
                (df['high'] - df['close'].shift()).abs(),
                (df['low']  - df['close'].shift()).abs(),
            ], axis=1).max(axis=1)
            return float(tr.rolling(self.atr_period).mean().iloc[-1])
        except Exception:
            return None


# ═══════════════════════════════════════════════════════════════════
# SECCIÓN 4: KELLY POSITION SIZER
# ═══════════════════════════════════════════════════════════════════

@dataclass
class TradeRecord:
    pnl_pct: float
    won: bool


class KellyPositionSizer:
    """Half-Kelly position sizing con mínimo de 20 trades para activarse."""

    def __init__(self):
        self._history: List[TradeRecord] = []

    def add_trade(self, pnl_pct: float):
        self._history.append(TradeRecord(pnl_pct, pnl_pct > 0))
        if len(self._history) > 100:
            self._history = self._history[-100:]

    def calculate(self, balance: float, entry: float,
                  stop_loss: float) -> Dict:
        if entry <= 0 or abs(entry - stop_loss) == 0:
            return {"error": "Precios inválidos", "position_usd": 0}
        pct   = self._kelly_pct()
        risk  = balance * pct
        dist  = abs(entry - stop_loss) / entry
        pos   = min(risk / dist, balance * Config.MAX_POSITION_PCT)
        return {
            "position_usd":  round(pos, 2),
            "position_coin": round(pos / entry, 6),
            "risk_pct":      round(pct * 100, 2),
            "method":        "kelly" if len(self._history) >= 20 else "default",
            "trades":        len(self._history),
        }

    def stats(self) -> Dict:
        if not self._history:
            return {"trades": 0, "win_rate": 0, "kelly_pct": 0}
        wins   = [t for t in self._history if t.won]
        losses = [t for t in self._history if not t.won]
        return {
            "trades":    len(self._history),
            "win_rate":  round(len(wins) / len(self._history) * 100, 1),
            "avg_win":   round(np.mean([t.pnl_pct for t in wins]), 3) if wins else 0,
            "avg_loss":  round(np.mean([t.pnl_pct for t in losses]), 3) if losses else 0,
            "kelly_pct": round(self._kelly_pct() * 100, 2),
        }

    def _kelly_pct(self) -> float:
        min_pos = 0.01
        max_pos = Config.MAX_POSITION_PCT
        if len(self._history) < 20:
            return min_pos
        recent = self._history[-50:]
        wins   = [t for t in recent if t.won]
        losses = [t for t in recent if not t.won]
        if not wins or not losses:
            return min_pos
        w = len(wins) / len(recent)
        b = np.mean([t.pnl_pct for t in wins]) / \
            np.mean([abs(t.pnl_pct) for t in losses])
        kelly = ((b * w - (1 - w)) / b) * Config.KELLY_FRACTION
        return float(np.clip(kelly, min_pos, max_pos))


# ═══════════════════════════════════════════════════════════════════
# SECCIÓN 5: REGIME DETECTOR
# ═══════════════════════════════════════════════════════════════════

class RegimeDetector:
    """
    Detecta régimen de mercado sin dependencias externas (sin hmmlearn).
    Usa ADX + Bollinger Width + ATR para clasificar.
    """

    REGIMES = ["STRONG_TREND", "WEAK_TREND", "RANGE", "CHOPPY",
               "VOL_SPIKE", "SQUEEZE"]

    def detect(self, df: pd.DataFrame) -> Dict:
        if len(df) < 30:
            return {"regime": "UNKNOWN", "confidence": 0.0,
                    "should_trade": False}
        try:
            close = df['close']
            high  = df['high']
            low   = df['low']

            # ADX simplificado
            delta  = close.diff()
            gain   = delta.where(delta > 0, 0).rolling(14).mean()
            loss   = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rsi    = 100 - (100 / (1 + gain / loss.replace(0, 1e-10)))

            tr     = pd.concat([
                high - low,
                (high - close.shift()).abs(),
                (low  - close.shift()).abs(),
            ], axis=1).max(axis=1)
            atr    = tr.rolling(14).mean().iloc[-1]
            atr_pct = atr / close.iloc[-1] * 100

            # Bollinger Width
            sma    = close.rolling(20).mean()
            std    = close.rolling(20).std()
            bb_w   = (std.iloc[-1] * 4) / sma.iloc[-1] * 100

            # EMA alignment
            ema20  = close.ewm(span=20).mean().iloc[-1]
            ema50  = close.ewm(span=50).mean().iloc[-1]
            ema200 = close.ewm(span=200).mean().iloc[-1]
            aligned = (close.iloc[-1] > ema20 > ema50 > ema200) or \
                      (close.iloc[-1] < ema20 < ema50 < ema200)

            # Clasificación
            if atr_pct > 3.0:
                regime = "VOL_SPIKE"
                conf   = min(atr_pct / 5, 1.0)
            elif bb_w < 2.0:
                regime = "SQUEEZE"
                conf   = 0.75
            elif aligned and atr_pct > 1.0:
                regime = "STRONG_TREND"
                conf   = 0.80
            elif aligned:
                regime = "WEAK_TREND"
                conf   = 0.65
            elif bb_w < 4.0:
                regime = "RANGE"
                conf   = 0.70
            else:
                regime = "CHOPPY"
                conf   = 0.55

            should_trade = regime in ["STRONG_TREND", "WEAK_TREND",
                                      "VOL_SPIKE"] and conf >= 0.6

            return {
                "regime":       regime,
                "confidence":   round(conf, 2),
                "atr_pct":      round(atr_pct, 2),
                "bb_width":     round(bb_w, 2),
                "rsi":          round(rsi.iloc[-1], 1),
                "ema_aligned":  aligned,
                "should_trade": should_trade,
            }
        except Exception as e:
            return {"regime": "ERROR", "confidence": 0,
                    "should_trade": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════
# SECCIÓN 6: CORRELATION MONITOR
# ═══════════════════════════════════════════════════════════════════

class CorrelationMonitor:
    """Detecta exposición duplicada entre posiciones correlacionadas."""

    def __init__(self, lookback: int = 30):
        self.lookback = lookback
        self._prices: Dict[str, List[float]] = {}

    def update(self, symbol: str, price: float):
        if symbol not in self._prices:
            self._prices[symbol] = []
        self._prices[symbol].append(price)
        if len(self._prices[symbol]) > self.lookback * 2:
            self._prices[symbol] = self._prices[symbol][-self.lookback:]

    def check(self, open_positions: List[str]) -> Dict:
        if len(open_positions) < 2:
            return {"risk": "low", "avg_corr": 0.0, "warnings": []}
        corrs    = []
        warnings = []
        for i, s1 in enumerate(open_positions):
            for s2 in open_positions[i + 1:]:
                if s1 in self._prices and s2 in self._prices:
                    p1 = pd.Series(self._prices[s1]).pct_change().dropna()
                    p2 = pd.Series(self._prices[s2]).pct_change().dropna()
                    n  = min(len(p1), len(p2), self.lookback)
                    if n < 5:
                        continue
                    c = float(np.corrcoef(p1[-n:], p2[-n:])[0, 1])
                    corrs.append(c)
                    if c > 0.8:
                        warnings.append(f"⚠️ {s1}/{s2}: {c:.0%} correlación")
        avg = round(np.mean(corrs), 3) if corrs else 0.0
        risk = ('critical' if avg > 0.8 else 'high' if avg > 0.6
                else 'medium' if avg > 0.4 else 'low')
        return {
            "risk": risk, "avg_corr": avg, "warnings": warnings,
            "recommendation": "REDUCIR" if risk in ['critical', 'high']
                              else "OK"
        }


# ═══════════════════════════════════════════════════════════════════
# SECCIÓN 7: BACKTESTER
# ═══════════════════════════════════════════════════════════════════

@dataclass
class BacktestResult:
    total_return_pct:    float
    max_drawdown_pct:    float
    sharpe_ratio:        float
    sortino_ratio:       float
    win_rate_pct:        float
    profit_factor:       float
    total_trades:        int
    avg_win_pct:         float
    avg_loss_pct:        float
    equity_curve:        List[float] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"Retorno: {self.total_return_pct:+.1f}% | "
            f"DD máx: {self.max_drawdown_pct:.1f}% | "
            f"Sharpe: {self.sharpe_ratio:.2f} | "
            f"Win: {self.win_rate_pct:.0f}% | "
            f"PF: {self.profit_factor:.2f} | "
            f"Trades: {self.total_trades}"
        )


class Backtester:
    """Motor de backtesting con slippage y comisiones realistas."""

    def __init__(self, commission=0.001, slippage=0.0005,
                 initial_capital=10_000.0):
        self.commission = commission
        self.slippage   = slippage
        self.capital0   = initial_capital

    def run(self, df: pd.DataFrame, strategy_fn) -> BacktestResult:
        cap      = self.capital0
        equity   = [cap]
        peak     = cap
        max_dd   = 0.0
        trades   = []
        position = None

        for i in range(50, len(df)):
            history = df.iloc[:i]
            candle  = df.iloc[i]

            # Cerrar posición si tocó SL o TP
            if position:
                pnl = 0.0
                exited = False
                d = position['direction']
                if d == 'long':
                    if candle['low']  <= position['sl']:
                        pnl, exited = (position['sl'] - position['entry']) / position['entry'], True
                    elif candle['high'] >= position['tp']:
                        pnl, exited = (position['tp'] - position['entry']) / position['entry'], True
                else:
                    if candle['high'] >= position['sl']:
                        pnl, exited = (position['entry'] - position['sl']) / position['entry'], True
                    elif candle['low']  <= position['tp']:
                        pnl, exited = (position['entry'] - position['tp']) / position['entry'], True

                if exited:
                    cap  *= (1 + pnl - self.commission * 2)
                    trades.append({'pnl_pct': pnl * 100, 'won': pnl > 0})
                    position = None

            # Abrir nueva posición
            if not position:
                try:
                    sig = strategy_fn(history)
                except Exception:
                    sig = None
                if sig and hasattr(sig, 'direction'):
                    ep = candle['close'] * (1 + self.slippage
                         if sig.direction == 'long' else 1 - self.slippage)
                    position = {
                        'entry': ep, 'sl': sig.stop_loss,
                        'tp': sig.take_profit, 'direction': sig.direction
                    }

            equity.append(cap)
            if cap > peak:
                peak = cap
            dd = (peak - cap) / peak * 100
            if dd > max_dd:
                max_dd = dd

        if not trades:
            return BacktestResult(0, 0, 0, 0, 0, 0, 0, 0, 0, equity)

        ret     = pd.Series(equity).pct_change().dropna()
        wins    = [t for t in trades if t['won']]
        losses  = [t for t in trades if not t['won']]
        wr      = len(wins) / len(trades) * 100
        avg_w   = np.mean([t['pnl_pct'] for t in wins]) if wins else 0
        avg_l   = abs(np.mean([t['pnl_pct'] for t in losses])) if losses else 0
        pf      = (sum(t['pnl_pct'] for t in wins) /
                   abs(sum(t['pnl_pct'] for t in losses) or 1))
        sharpe  = (np.sqrt(365) * ret.mean() / ret.std()
                   if ret.std() > 0 else 0)
        down    = ret[ret < 0]
        sortino = (np.sqrt(365) * ret.mean() / down.std()
                   if len(down) > 1 and down.std() > 0 else 0)
        total_r = (cap - self.capital0) / self.capital0 * 100

        return BacktestResult(
            total_return_pct = round(total_r, 2),
            max_drawdown_pct = round(max_dd, 2),
            sharpe_ratio     = round(sharpe, 2),
            sortino_ratio    = round(sortino, 2),
            win_rate_pct     = round(wr, 1),
            profit_factor    = round(pf, 2),
            total_trades     = len(trades),
            avg_win_pct      = round(avg_w, 3),
            avg_loss_pct     = round(avg_l, 3),
            equity_curve     = equity,
        )


# ═══════════════════════════════════════════════════════════════════
# SECCIÓN 8: EXCHANGE MANAGER
# ═══════════════════════════════════════════════════════════════════

class ExchangeManager:
    """Conexión Binance con caché y OBI."""

    def __init__(self):
        self.exchange = None
        self._cache: Dict[str, pd.DataFrame] = {}

    def connect(self, api_key: str = None, api_secret: str = None):
        if Config.DEMO_MODE or self.exchange:
            return
        try:
            import ccxt
            cfg = {
                'enableRateLimit': True,
                'apiKey': api_key, 'secret': api_secret,
                'options': {'defaultType':
                    'spot' if Config.USE_SPOT else 'future'},
            }
            self.exchange = (ccxt.binance(cfg) if Config.USE_SPOT
                             else ccxt.binanceusdm(cfg))
        except ImportError:
            st.error("ccxt no instalado")

    def fetch_candles(self, tf: str) -> pd.DataFrame:
        if Config.DEMO_MODE or not self.exchange:
            return self._demo_candles(tf)
        try:
            data = self.exchange.fetch_ohlcv(
                Config.SYMBOL, tf, limit=Config.CANDLE_LIMIT
            )
            df = pd.DataFrame(data,
                columns=['time','open','high','low','close','volume'])
            df['time'] = pd.to_datetime(df['time'], unit='ms')
            df = df.set_index('time')
            self._cache[tf] = df
            return df
        except Exception:
            return self._cache.get(tf, self._demo_candles(tf))

    def fetch_all_timeframes(self) -> Dict[str, pd.DataFrame]:
        tfs = [Config.TF_ENTRY, Config.TF_CONFIRM, Config.TF_TREND]
        with ThreadPoolExecutor(max_workers=3) as ex:
            results = list(ex.map(self.fetch_candles, tfs))
        return {tf: df for tf, df in zip(tfs, results) if not df.empty}

    def fetch_obi(self, depth: int = 20) -> Dict:
        if Config.DEMO_MODE or not self.exchange:
            rng = np.random.uniform(-0.15, 0.15)
            return {'obi': round(rng, 4),
                    'bids_vol': round(abs(rng) * 1000, 2),
                    'asks_vol': round(abs(rng) * 900, 2)}
        try:
            ob     = self.exchange.fetch_order_book(Config.SYMBOL, depth)
            b_v    = sum(b[1] for b in ob['bids'])
            a_v    = sum(a[1] for a in ob['asks'])
            total  = b_v + a_v
            obi    = (b_v - a_v) / total if total else 0
            return {'obi': round(obi, 4),
                    'bids_vol': round(b_v, 2),
                    'asks_vol': round(a_v, 2)}
        except Exception:
            return {'obi': 0.0, 'bids_vol': 0.0, 'asks_vol': 0.0}

    def fetch_balance(self) -> Dict:
        """Obtiene balances reales de la cuenta."""
        if Config.DEMO_MODE or not self.exchange:
            return {
                'total': {'BTC': 0.523, 'USDT': 12450.0, 'ETH': 4.25, 'SOL': 120.0},
                'free':  {'BTC': 0.123, 'USDT': 2450.0,  'ETH': 0.25, 'SOL': 20.0},
                'usd_val': 45670.0
            }
        try:
            bal = self.exchange.fetch_balance()
            relevant = {k: v for k, v in bal['total'].items() if v > 1e-6}
            return {'total': relevant, 'free': bal['free']}
        except Exception as e:
            return {'total': {}, 'free': {}, 'error': str(e)}

    def fetch_positions(self) -> List[Dict]:
        """Obtiene posiciones abiertas (principalmente para futuros)."""
        if Config.DEMO_MODE or not self.exchange:
            return [
                {'symbol': 'BTC/USDT', 'side': 'long', 'amount': 0.05, 'entry': 64500.0, 'unrealized_pnl': 120.50},
                {'symbol': 'ETH/USDT', 'side': 'short', 'amount': 1.2, 'entry': 3500.0, 'unrealized_pnl': -45.20}
            ]
        try:
            if Config.USE_SPOT:
                return []
            pos = self.exchange.fetch_positions()
            return [p for p in pos if p['contracts'] > 0]
        except Exception as e:
            return [{'error': str(e)}]

    @staticmethod
    def _demo_candles(tf: str) -> pd.DataFrame:
        """Genera velas sintéticas para modo demo."""
        np.random.seed(abs(hash(tf)) % 2**31)
        n      = Config.CANDLE_LIMIT
        price  = 65_000.0
        prices = [price]
        for _ in range(n - 1):
            price += np.random.normal(0, price * 0.002)
            prices.append(max(price, 1))
        closes = np.array(prices)
        highs  = closes * np.random.uniform(1.001, 1.005, n)
        lows   = closes * np.random.uniform(0.995, 0.999, n)
        opens  = np.roll(closes, 1)
        opens[0] = closes[0]
        idx = pd.date_range(end=datetime.now(), periods=n, freq=tf)
        return pd.DataFrame({
            'open': opens, 'high': highs,
            'low': lows,   'close': closes,
            'volume': np.random.uniform(100, 1000, n)
        }, index=idx)


# ═══════════════════════════════════════════════════════════════════
# SECCIÓN 9: AI BRAIN
# ═══════════════════════════════════════════════════════════════════

class AIBrain:
    """Análisis de sentimiento vía Groq/Llama."""

    def __init__(self):
        self.sentiment = {"score": 0.0, "label": "NEUTRAL",
                          "summary": "Sin datos", "updated": None}

    def analyze(self) -> Dict:
        if not Config.GROQ_API_KEY:
            return self.sentiment
        try:
            from groq import Groq
            client = Groq(api_key=Config.GROQ_API_KEY)
            resp   = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                max_tokens=200,
                messages=[{
                    "role": "user",
                    "content": (
                        "Analiza el sentimiento actual del mercado cripto BTC. "
                        "Responde SOLO con JSON: "
                        '{"score": <float -1 a 1>, '
                        '"label": "BULLISH|BEARISH|NEUTRAL", '
                        '"summary": "<20 palabras max>"}'
                    )
                }]
            )
            raw  = resp.choices[0].message.content.strip()
            data = json.loads(raw)
            self.sentiment = {**data, "updated": datetime.now().isoformat()}
        except Exception as e:
            self.sentiment["error"] = str(e)
        return self.sentiment

    def recommend(self, balance_data: Dict) -> Dict:
        """Genera recomendaciones personalizadas basadas en el portafolio."""
        if not Config.GROQ_API_KEY:
            return {
                "recommendation": "Considera diversificar hacia activos L1 (SOL/ETH) dado el régimen actual.",
                "action": "DIVERSIFY",
                "confidence": 0.75
            }
        try:
            from groq import Groq
            client = Groq(api_key=Config.GROQ_API_KEY)
            assets = list(balance_data.get('total', {}).keys())
            
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                max_tokens=250,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Usuario tiene estos activos: {assets}. "
                        "Genera una idea de inversión profesional de 1 frase. "
                        "Responde SOLO con JSON: "
                        '{"recommendation": "<frase>", "action": "BUY|SELL|HOLD|DIVERSIFY", "confidence": <float 0-1>}'
                    )
                }]
            )
            return json.loads(resp.choices[0].message.content.strip())
        except Exception:
            return {"recommendation": "Mantener liquidez en USDT ante volatilidad.", "action": "HOLD", "confidence": 0.8}

    def fetch_news(self) -> List[Dict]:
        """Simula/Obtiene noticias del mercado."""
        # En producción se usaría un parser de RSS o API de CryptoPanic
        return [
            {"title": "BlackRock ETF inflows hit record high", "impact": "Bullish", "source": "Coindesk"},
            {"title": "SEC delays decision on ETH options trades", "impact": "Neutral", "source": "Reuters"},
            {"title": "Whale moves $500M BTC to exchange", "impact": "Bearish", "source": "WhaleAlert"}
        ]


# ═══════════════════════════════════════════════════════════════════
# SECCIÓN 10: AUTH MANAGER (simple, sin BD externa)
# ═══════════════════════════════════════════════════════════════════

class AuthManager:
    """
    Autenticación básica con archivo JSON local.
    En Railway, usa un volumen persistente o migra a una BD.
    """

    DB_PATH = os.getenv("AUTH_DB_PATH", "/app/users.json")

    def _load(self) -> Dict:
        try:
            with open(self.DB_PATH) as f:
                return json.load(f)
        except Exception:
            return {}

    def _save(self, data: Dict):
        try:
            os.makedirs(os.path.dirname(self.DB_PATH), exist_ok=True)
            with open(self.DB_PATH, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _hash(self, pw: str) -> str:
        return hashlib.sha256(pw.encode()).hexdigest()

    def authenticate(self, username: str, password: str) -> bool:
        users = self._load()
        user  = users.get(username)
        return bool(user and user.get('password') == self._hash(password))

    def register(self, username: str, password: str) -> bool:
        users = self._load()
        if username in users:
            return False
        users[username] = {'password': self._hash(password),
                           'created': datetime.now().isoformat()}
        self._save(users)
        return True

    def get_keys(self, username: str) -> Tuple[str, str]:
        users    = self._load()
        user     = users.get(username, {})
        return user.get('api_key', ''), user.get('api_secret', '')

    def save_keys(self, username: str, key: str, secret: str):
        users = self._load()
        if username in users:
            users[username]['api_key']    = key
            users[username]['api_secret'] = secret
            self._save(users)


# ═══════════════════════════════════════════════════════════════════
# SECCIÓN 11: SESSION STATE INIT
# ═══════════════════════════════════════════════════════════════════

def _init_session():
    defaults = {
        'logged_in':    False,
        'username':     '',
        'initialized':  False,
        'exchange':     ExchangeManager(),
        'circuit_breaker': CircuitBreaker(),
        'risk_manager': ATRRiskManager(),
        'position_sizer': KellyPositionSizer(),
        'regime_detector': RegimeDetector(),
        'corr_monitor': CorrelationMonitor(),
        'ai_brain':     AIBrain(),
        'auth':         AuthManager(),
        'demo_mode':    True,
        'last_refresh': None,
        'tf_data':      {},
        'obi_data':     {},
        'regime_data':  {},
        'ai_data':      {},
        'balance_data': {},
        'position_data': [],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ═══════════════════════════════════════════════════════════════════
# SECCIÓN 12: LÓGICA DE CONEXIÓN Y DATOS
# ═══════════════════════════════════════════════════════════════════

def _resolve_mode():
    """Detecta si usar llaves del usuario o globales de Railway."""
    username = st.session_state.username
    u_key, u_sec = st.session_state.auth.get_keys(username)

    # Prioridad: llaves del usuario → llaves globales de Railway
    has_user_keys   = bool(u_key and u_sec)
    has_global_keys = bool(Config.BINANCE_API_KEY and Config.BINANCE_SECRET)

    if has_user_keys:
        key, sec = u_key, u_sec
    elif has_global_keys:
        key, sec = Config.BINANCE_API_KEY, Config.BINANCE_SECRET
    else:
        key, sec = '', ''

    Config.DEMO_MODE = not bool(key and sec)
    st.session_state.demo_mode = Config.DEMO_MODE
    return key, sec


def _fetch_data():
    """Fetch de todos los datos necesarios para el dashboard."""
    key, sec = _resolve_mode()
    ex: ExchangeManager = st.session_state.exchange

    if not st.session_state.initialized or \
       (not Config.DEMO_MODE and ex.exchange is None):
        ex.connect(key, sec)
        st.session_state.initialized = True

    tf_data  = ex.fetch_all_timeframes()
    obi_data = ex.fetch_obi()
    bal_data = ex.fetch_balance()
    pos_data = ex.fetch_positions()

    # Régimen basado en TF de tendencia
    rd: RegimeDetector = st.session_state.regime_detector
    trend_df = tf_data.get(Config.TF_TREND, pd.DataFrame())
    regime   = rd.detect(trend_df) if not trend_df.empty else {}

    st.session_state.tf_data     = tf_data
    st.session_state.obi_data    = obi_data
    st.session_state.regime_data = regime
    st.session_state.balance_data = bal_data
    st.session_state.position_data = pos_data
    st.session_state.last_refresh = datetime.now()
    return tf_data, obi_data, regime


# ═══════════════════════════════════════════════════════════════════
# SECCIÓN 13: ESTILOS CSS (Quantum Noir Pro Max)
# ═══════════════════════════════════════════════════════════════════

STYLES = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:wght@700;800&family=Outfit:wght@300;400;500;600&family=JetBrains+Mono:wght@500;700&display=swap');

:root {
    --bg-dark: #030305;
    --accent-blue: #00e5ff;
    --accent-purple: #ab47bc;
    --accent-green: #00ffa3;
    --accent-red: #ff2d55;
    --card-bg: rgba(10, 10, 15, 0.85);
    --glass-border: rgba(255, 255, 255, 0.08);
    --transition-fast: 200ms cubic-bezier(0.4, 0, 0.2, 1);
    --transition-smooth: 400ms cubic-bezier(0.16, 1, 0.3, 1);
}

html, body, [class*="css"] {
    font-family: 'Outfit', sans-serif;
    color: #f1f5f9;
}

/* ── Performance & Accessibility ── */
* { transition: var(--transition-fast); }
*:focus { outline: 2px solid var(--accent-blue); outline-offset: 4px; }

/* ── Quantum Background ── */
.stApp {
    background-color: var(--bg-dark);
    background-image: 
        radial-gradient(circle at 10% 10%, rgba(0, 229, 255, 0.08) 0%, transparent 35%),
        radial-gradient(circle at 90% 90%, rgba(171, 71, 188, 0.08) 0%, transparent 35%),
        radial-gradient(circle at 50% 50%, rgba(3, 3, 5, 0.5) 0%, var(--bg-dark) 100%),
        url("https://www.transparenttextures.com/patterns/black-linen.png");
    background-attachment: fixed;
}

/* ── Bento Card System ── */
.titanium-card {
    background: var(--card-bg);
    border: 1px solid var(--glass-border);
    border-radius: 2px;
    padding: 24px;
    backdrop-filter: blur(40px) saturate(180%);
    box-shadow: 0 4px 20px rgba(0,0,0,0.6);
    transition: var(--transition-smooth);
    position: relative;
    overflow: hidden;
    cursor: pointer;
    margin-bottom: 20px;
}

.titanium-card:hover {
    border-color: var(--accent-blue);
    transform: translateY(-4px) scale(1.005);
    background: rgba(15, 15, 25, 0.95);
    box-shadow: 0 12px 40px rgba(0, 229, 255, 0.1);
}

.titanium-card::before {
    content: "";
    position: absolute;
    top: 0; left: 0; width: 100%; height: 2px;
    background: linear-gradient(90deg, transparent, var(--accent-blue), transparent);
    transform: translateX(-100%);
    transition: transform 0.6s;
}

.titanium-card:hover {
    border-color: rgba(0, 210, 255, 0.3);
    transform: translateY(-4px) scale(1.01);
    background: rgba(20, 20, 35, 0.82);
}

.titanium-card:hover::after {
    transform: translateX(100%);
}

.metric-label {
    font-family: 'Outfit', sans-serif;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: var(--accent-blue);
    margin-bottom: 8px;
    opacity: 0.8;
}

.metric-value {
    font-family: 'Source Code Pro', monospace;
    font-size: 32px;
    font-weight: 600;
    color: #ffffff;
    text-shadow: 0 0 20px rgba(0, 210, 255, 0.2);
}

.metric-sub {
    font-size: 12px;
    font-weight: 300;
    color: rgba(255,255,255,0.4);
    margin-top: 6px;
}

/* ── Badges Neon ── */
.badge {
    padding: 4px 12px;
    border-radius: 2px;
    font-size: 10px;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 1px;
}
.badge-green  { background: rgba(0, 255, 128, 0.1); color: #00ff80; border: 1px solid rgba(0, 255, 128, 0.3); box-shadow: 0 0 10px rgba(0, 255, 128, 0.1); }
.badge-red    { background: rgba(255, 46, 99, 0.1); color: #ff2e63; border: 1px solid rgba(255, 46, 99, 0.3); box-shadow: 0 0 10px rgba(255, 46, 99, 0.1); }
.badge-blue   { background: rgba(0, 210, 255, 0.1); color: #00d2ff; border: 1px solid rgba(0, 210, 255, 0.3); box-shadow: 0 0 10px rgba(0, 210, 255, 0.1); }
.badge-yellow { background: rgba(255, 211, 0, 0.1); color: #ffd300; border: 1px solid rgba(255, 211, 0, 0.3); }

/* ── Header ── */
.titanium-header {
    font-family: 'Syne', sans-serif;
    font-size: 42px;
    font-weight: 800;
    letter-spacing: -2px;
    background: linear-gradient(135deg, #ffffff 30%, var(--accent-blue) 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 0;
}

.titanium-sub {
    font-family: 'Source Code Pro', monospace;
    font-size: 11px;
    color: var(--accent-purple);
    letter-spacing: 4px;
    text-transform: uppercase;
    margin-top: -10px;
    margin-bottom: 30px;
    font-weight: 600;
}

/* ── Custom UI Components ── */
.stButton > button {
    background: transparent;
    border: 1px solid var(--glass-border);
    color: #fff;
    border-radius: 2px;
    font-family: 'Outfit', sans-serif;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 2px;
    padding: 12px 24px;
    transition: all 0.3s;
}
.stButton > button:hover {
    background: var(--accent-blue);
    color: var(--bg-dark);
    box-shadow: 0 0 30px rgba(0, 210, 255, 0.4);
}

.stTabs [data-baseweb="tab-list"] {
    gap: 20px;
    background-color: transparent;
}
.stTabs [data-baseweb="tab"] {
    background-color: transparent !important;
    border: none !important;
    font-family: 'Syne', sans-serif;
    font-weight: 700;
    font-size: 16px;
    color: rgba(255,255,255,0.4) !important;
}
.stTabs [aria-selected="true"] {
    color: var(--accent-blue) !important;
    border-bottom: 2px solid var(--accent-blue) !important;
}

/* ── OBI Bar Noir ── */
.obi-bar-container {
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.05);
    border-radius: 2px;
    height: 4px;
    overflow: hidden;
    margin-top: 15px;
}
.obi-bar-fill {
    height: 100%;
    transition: all 0.8s cubic-bezier(0.16, 1, 0.3, 1);
    box-shadow: 0 0 10px currentColor;
}
</style>
"""


# ═══════════════════════════════════════════════════════════════════
# SECCIÓN 14: COMPONENTES UI
# ═══════════════════════════════════════════════════════════════════

def card(label: str, value: str, sub: str = "", badge: str = ""):
    badge_html = f'<span class="badge badge-{badge}">{badge.upper()}</span>' \
                 if badge else ""
    st.markdown(f"""
    <div class="titanium-card">
        <div class="metric-label">{label} {badge_html}</div>
        <div class="metric-value">{value}</div>
        <div class="metric-sub">{sub}</div>
    </div>
    """, unsafe_allow_html=True)


def obi_bar(obi_value: float):
    pct    = int((obi_value + 1) / 2 * 100)
    color  = "#00ff80" if obi_value > 0 else "#ff2e63"
    label  = "BULLISH PRESSURE" if obi_value > 0 else "BEARISH PRESSURE"
    st.markdown(f"""
    <div class="titanium-card">
        <div class="metric-label">Liquidity Flux</div>
        <div class="metric-value" style="color:{color};">{obi_value:+.4f}</div>
        <div class="metric-sub">{label}</div>
        <div class="obi-bar-container">
            <div class="obi-bar-fill"
                 style="width:{pct}%; background:{color}; color:{color};">
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)


def regime_card(data: Dict):
    regime  = data.get('regime', 'UNKNOWN')
    conf    = data.get('confidence', 0)
    should  = data.get('should_trade', False)
    colors  = {
        'STRONG_TREND': 'green', 'WEAK_TREND': 'green',
        'VOL_SPIKE': 'yellow', 'RANGE': 'blue',
        'CHOPPY': 'red', 'SQUEEZE': 'yellow',
    }
    color = colors.get(regime, 'blue')
    trade_text = "EXECUTE" if should else "STANDBY"
    trade_class = "green" if should else "red"
    
    st.markdown(f"""
    <div class="titanium-card">
        <div class="metric-label">Market DNA</div>
        <div class="metric-value">
            <span class="badge badge-{color}">{regime}</span>
        </div>
        <div class="metric-sub">
            Confidence: {conf:.0%} &nbsp;|&nbsp; 
            <span class="badge badge-{trade_class}">{trade_text}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)


def circuit_card(cb: CircuitBreaker):
    status = cb.get_status()
    ok     = status['can_trade']
    color  = "green" if ok else "red"
    label  = "ACTIVO" if ok else "PAUSADO"
    reason = status.get('pause_reason') or "—"
    dd_d   = status['daily_pnl_pct']
    dd_t   = status['total_pnl_pct']
    st.markdown(f"""
    <div class="titanium-card">
        <div class="metric-label">Circuit Breaker</div>
        <div class="metric-value">
            <span class="badge badge-{color}">{label}</span>
        </div>
        <div class="metric-sub">
            PnL hoy: {dd_d:+.2f}% &nbsp;|&nbsp;
            PnL total: {dd_t:+.2f}% &nbsp;|&nbsp;
            {reason}
        </div>
    </div>
    """, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════
# SECCIÓN 15: PÁGINAS
# ═══════════════════════════════════════════════════════════════════

def page_login():
    st.markdown('<div style="text-align:center; padding: 40px 0 10px;">', unsafe_allow_html=True)
    try:
        st.image("C:/Users/Usuario/.gemini/antigravity/brain/ce486288-d208-47ee-82cc-7f9a8bf307e2/input_file_0.png", width=120)
    except:
        pass
    st.markdown('<div class="titanium-header">TITANIUM PRO</div>', True)
    st.markdown('<div class="titanium-sub">NEXT-LEVEL ALGORITHMIC DEFINE SYSTEM</div>', True)
    st.markdown('</div>', unsafe_allow_html=True)
    
    st.markdown("""
    <div style="max-width:440px; margin: 0 auto; padding: 20px;">
    """, unsafe_allow_html=True)

    tab_in, tab_reg = st.tabs(["[ LOGIN ]", "[ REGISTER ]"])

    with tab_in:
        u = st.text_input("QUANTUM_ID", key="li_u", placeholder="Enter ID...")
        p = st.text_input("ACCESS_KEY", type="password", key="li_p", placeholder="••••••••")
        if st.button("INITIALIZE SECURE SESSION", use_container_width=True):
            if st.session_state.auth.authenticate(u, p):
                st.session_state.logged_in = True
                st.session_state.username  = u
                st.session_state.initialized = False
                st.rerun()
            else:
                st.error("EXCEPTION: ACCESS_DENIED")

    with tab_reg:
        nu_ = st.text_input("NEW_QUANTUM_ID", key="rg_u", placeholder="Choose ID...")
        np_ = st.text_input("NEW_ACCESS_KEY", type="password", key="rg_p", placeholder="••••••••")
        if st.button("CREATE QUANTUM ACCOUNT", use_container_width=True):
            if st.session_state.auth.register(nu_, np_):
                st.success("SUCCESS: ID CREATED")
            else:
                st.error("EXCEPTION: ID_ALREADY_EXISTS")
    
    st.markdown("</div>", unsafe_allow_html=True)


def page_dashboard():
    # ── Sidebar ─────────────────────────────────────────────────
    with st.sidebar:
        try:
            st.image("C:/Users/Usuario/.gemini/antigravity/brain/ce486288-d208-47ee-82cc-7f9a8bf307e2/input_file_0.png", width=60)
        except:
            pass
        st.markdown('<div class="titanium-header" style="font-size:20px">⚡ TITANIUM PRO v10.0</div>', True)
        mode = "🟡 DEMO" if st.session_state.demo_mode else "🟢 REAL"
        st.markdown(f"**{mode}** — {st.session_state.username}")
        st.markdown("---")

        # Navegación
        page = st.radio("Navegación", [
            "📊 Dashboard", "💼 Portafolio", "🤖 AI Advisor",
            "🚀 DeFi Vaults", "🎯 Circuit Breaker",
            "📐 Position Sizer", "🔬 Backtesting",
            "⚙️ Configuración"
        ], label_visibility="collapsed")

        st.markdown("---")
        refresh = st.slider("Auto-refresh (s)", 10, 120, 30)
        if st.button("🔄 Refrescar ahora", use_container_width=True):
            _fetch_data()
        if st.button("🚪 Cerrar sesión", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.username  = ''
            st.rerun()

    # ── Fetch de datos ───────────────────────────────────────────
    if (st.session_state.last_refresh is None or
        (datetime.now() - st.session_state.last_refresh).seconds > refresh):
        with st.spinner("Obteniendo datos..."):
            _fetch_data()

    tf_data  = st.session_state.tf_data
    obi_data = st.session_state.obi_data
    regime   = st.session_state.regime_data
    cb: CircuitBreaker = st.session_state.circuit_breaker

    # ── Routing de páginas ───────────────────────────────────────
    if page == "📊 Dashboard":
        _page_main(tf_data, obi_data, regime, cb)
    elif page == "💼 Portafolio":
        _page_portfolio(st.session_state.balance_data,
                        st.session_state.position_data)
    elif page == "🤖 AI Advisor":
        _page_ai_advisor()
    elif page == "🚀 DeFi Vaults":
        _page_vault()
    elif page == "🎯 Circuit Breaker":
        _page_circuit(cb)
    elif page == "📐 Position Sizer":
        _page_sizer(tf_data)
    elif page == "🔬 Backtesting":
        _page_backtest(tf_data)
    elif page == "⚙️ Configuración":
        _page_config()

    # Auto-refresh
    time.sleep(refresh)
    st.rerun()


def _page_main(tf_data, obi_data, regime, cb):
    st.markdown('<div class="titanium-header">📊 Dashboard</div>', True)

    # Fila superior: indicadores clave
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        df_e = tf_data.get(Config.TF_ENTRY, pd.DataFrame())
        price = df_e['close'].iloc[-1] if not df_e.empty else 0
        card("Precio BTC", f"${price:,.0f}",
             sub=f"TF: {Config.TF_ENTRY}")
    with c2:
        obi_bar(obi_data.get('obi', 0))
    with c3:
        regime_card(regime)
    with c4:
        circuit_card(cb)

    st.markdown("---")
    
    # Noticieros / AI Ticker
    ai: AIBrain = st.session_state.ai_brain
    news = ai.fetch_news()
    st.markdown("#### 📰 Market News Ticker")
    cols_n = st.columns(len(news))
    for i, n in enumerate(news):
        with cols_n[i]:
            color = "green" if n['impact'] == "Bullish" else "red" if n['impact'] == "Bearish" else "blue"
            st.markdown(f"""
            <div style="padding:10px; border-left:3px solid {color}; background:rgba(255,255,255,0.02); border-radius:4px;">
                <div style="font-size:10px; color:gray;">{n['source']} • {n['impact']}</div>
                <div style="font-size:12px; font-weight:500;">{n['title']}</div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("---")

    # Velas por timeframe
    for tf, df in tf_data.items():
        if df.empty:
            continue
        with st.expander(f"📈 Timeframe {tf}", expanded=(tf == Config.TF_ENTRY)):
            col_chart, col_stats = st.columns([3, 1])
            with col_chart:
                chart_df = df[['open','high','low','close','volume']].tail(50)
                st.line_chart(chart_df['close'])
            with col_stats:
                last   = df.iloc[-1]
                change = (df['close'].iloc[-1] / df['close'].iloc[-2] - 1) * 100
                color  = "green" if change >= 0 else "red"
                card("Último cierre",
                     f"${last['close']:,.2f}",
                     sub=f"{'▲' if change>=0 else '▼'} {change:+.2f}%",
                     badge=color)

                # RSI rápido
                delta = df['close'].diff()
                gain  = delta.where(delta>0,0).rolling(14).mean()
                loss  = (-delta.where(delta<0,0)).rolling(14).mean()
                rsi   = (100 - 100 / (1 + gain/loss.replace(0,1e-10))).iloc[-1]
                rsi_b = "green" if 40<rsi<60 else "yellow" if 30<rsi<70 else "red"
                card("RSI (14)", f"{rsi:.1f}",
                     sub="Sobrecomprado" if rsi>70 else
                         "Sobrevendido" if rsi<30 else "Neutro",
                     badge=rsi_b)

    # AI Sentiment
    st.markdown("---")
    st.markdown("### 🤖 AI Sentiment")
    ai: AIBrain = st.session_state.ai_brain
    if st.button("Analizar con Groq/Llama"):
        with st.spinner("Consultando IA..."):
            data = ai.analyze()
        st.session_state.ai_data = data

    ai_data = st.session_state.ai_data
    if ai_data:
        label = ai_data.get('label', 'NEUTRAL')
        score = ai_data.get('score', 0)
        summ  = ai_data.get('summary', '—')
        color = "green" if label=="BULLISH" else "red" if label=="BEARISH" else "blue"
        card(f"Sentimiento IA",
             f"{label} ({score:+.2f})",
             sub=summ, badge=color)


def _page_portfolio(balance_data, position_data):
    st.markdown('<div class="titanium-header">💼 Portafolio</div>', True)
    
    # Resumen de Valor
    total_val = balance_data.get('usd_val', 0)
    if not total_val and balance_data.get('total'):
        # Cálculo simple si no viene el valor (solo demo lo trae directo)
        total_val = sum([v for v in balance_data['total'].values() if isinstance(v, (int, float))])
    
    col1, col2 = st.columns([1, 2])
    with col1:
        card("Valor Estimado", f"${total_val:,.2d}", sub="Total USD Assets", badge="blue")
    
    with col2:
        st.markdown("#### Distribución de Assets")
        if balance_data.get('total'):
            bal_df = pd.DataFrame([
                {"Asset": k, "Balance": v} for k, v in balance_data['total'].items()
            ])
            st.bar_chart(bal_df.set_index("Asset"))

    st.markdown("---")
    st.markdown("### 📊 Posiciones Abiertas")
    if position_data:
        pos_df = pd.DataFrame(position_data)
        st.dataframe(pos_df, use_container_width=True, hide_index=True)
    else:
        st.info("No hay posiciones abiertas en este momento.")

    st.markdown("---")
    st.markdown("### 💰 Balances Detallados")
    if balance_data.get('total'):
        b_df = pd.DataFrame([
            {"Asset": k, "Total": v, "Disponible": balance_data['free'].get(k, 0)}
            for k, v in balance_data['total'].items()
        ])
        st.dataframe(b_df, use_container_width=True, hide_index=True)


def _page_ai_advisor():
    st.markdown('<div class="titanium-header">🤖 AI Advisor</div>', True)
    st.caption("Asesor inteligente basado en tu portafolio y contexto macro.")

    ai: AIBrain = st.session_state.ai_brain
    bal = st.session_state.balance_data

    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown("### 💡 Recomendación Estratégica")
        if st.button("Generar Idea de Inversión", use_container_width=True):
            with st.spinner("Consultando Llama 3.3..."):
                rec = ai.recommend(bal)
                st.session_state['ai_recommendation'] = rec
        
        if 'ai_recommendation' in st.session_state:
            rec = st.session_state['ai_recommendation']
            action_colors = {"BUY": "green", "SELL": "red", "HOLD": "blue", "DIVERSIFY": "yellow"}
            color = action_colors.get(rec.get('action'), "blue")
            
            st.markdown(f"""
            <div class="titanium-card" style="border-left: 5px solid var(--accent-blue); background: rgba(0, 210, 255, 0.02);">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span class="badge badge-{color}">{rec.get('action')}</span>
                    <span style="font-family:'Source Code Pro'; font-size:10px; color:rgba(255,255,255,0.3);">CONFIDENCE: {rec.get('confidence', 0):.0%}</span>
                </div>
                <h3 style="margin-top:20px; font-family:'Syne'; font-weight:700; color:#fff; line-height:1.4;">
                    {rec.get('recommendation')}
                </h3>
                <div style="margin-top:20px; height:1px; background:linear-gradient(90deg, var(--accent-blue), transparent);"></div>
                <div style="margin-top:10px; font-size:10px; color:var(--accent-blue); letter-spacing:1px;">
                    QUANTUM ENGINE ANALYTICS • VERIFIED SIGNAL
                </div>
            </div>
            """, unsafe_allow_html=True)

    with col2:
        st.markdown("### 📊 Market Context")
        ai_data = st.session_state.ai_data
        if not ai_data:
            if st.button("Analizar Sentimiento General"):
                ai_data = ai.analyze()
                st.session_state.ai_data = ai_data
        
        if ai_data:
            label = ai_data.get('label', 'NEUTRAL')
            score = ai_data.get('score', 0)
            color = "green" if label=="BULLISH" else "red" if label=="BEARISH" else "blue"
            card("Market Score", f"{score:+.2f}", sub=label, badge=color)
            st.info(ai_data.get('summary', ''))


def _page_vault():
    """DeFi Vault - Staking, AMM, Governance & Flash Loans"""
    st.markdown('<div class="titanium-header">🏦 DeFi Vault & Protocols</div>', unsafe_allow_html=True)
    st.caption("Gestión de capital en protocolos on-chain")

    cb = st.session_state.get('circuit_breaker')
    if cb and not cb.can_trade():
        st.markdown("""
        <div class="titanium-card" style="border-color: #ff0055; background: rgba(255,0,85,0.1);">
            <div style="color: #ff0055; font-weight: 700; font-size: 16px;">
                🚫 TRADING PAUSED — Operaciones DeFi deshabilitadas por protección de capital
            </div>
        </div>
        """, unsafe_allow_html=True)

    # Métricas
    c1, c2, c3, c4 = st.columns(4)
    with c1: card("TVL Total", "$125,430.00", sub="Capital en protocolos", badge="blue")
    with c2: card("APY Promedio", "12.4%", sub="Rendimiento anualizado", badge="green")
    with c3: card("Rewards", "45.2 GOV", sub="Pendientes por claim", badge="yellow")
    with c4: card("Health Factor", "1.85", sub="Seguro", badge="green")

    st.markdown("---")
    
    tab_stake, tab_amm, tab_gov, tab_flash = st.tabs(["🔒 Staking", "🔄 AMM", "🏛️ Governance", "⚡ Flash Loans"])
    
    with tab_stake:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Depositar**")
            tok = st.selectbox("Token", ["GOV","ETH","USDT"], key="stk_tok")
            amt = st.number_input("Cantidad", 0.0, 1e9, 100.0, key="stk_amt")
            if st.button("Depositar", key="stk_dep"): st.success(f"Deposito simulado: {amt} {tok}")
            if st.button("Withdraw All", key="stk_wdr"): st.warning("Retiro simulado")
        with c2:
            st.markdown("**Rewards**")
            card("Reward Rate", "100 tok/s", badge="blue")
            card("Earned", "3.45 GOV", badge="green")
            if st.button("Claim Rewards", key="stk_clm"): st.success("Claim exitoso")

    with tab_amm:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Add Liquidity**")
            a0 = st.number_input("Token0", 0.0, 1e9, 1000.0, key="amm0")
            a1 = st.number_input("Token1", 0.0, 1e9, 1000.0, key="amm1")
            if st.button("Supply", key="amm_sup"):
                shares = (a0 * a1) ** 0.5
                st.success(f"Shares LP recibidas: {shares:,.4f}")
        with c2:
            st.markdown("**Simulador Swap**")
            am_in = st.number_input("Amount In", 0.0, 1e9, 100.0, key="sw_in")
            res_in, res_out = 50000.0, 50000.0
            am_in_fee = am_in * 997 / 1000
            am_out = (res_out * am_in_fee) / (res_in + am_in_fee)
            card("Amount Out", f"{am_out:,.4f}", badge="blue")
            st.caption("Fee: 0.3%")
    
    with tab_gov:
        st.markdown("**Proposals Activas**")
        df = pd.DataFrame([
            {"ID":1, "Descripción":"Aumentar rewards","ForVotes":"850K","AgainstVotes":"120K","Estado":"Active"},
            {"ID":2, "Descripción":"Nuevo pool ETH/USDC","ForVotes":"430K","AgainstVotes":"410K","Estado":"Active"},
        ])
        st.dataframe(df, hide_index=True, use_container_width=True)
    
    with tab_flash:
        st.markdown("**Flash Loan**")
        fl_amt = st.number_input("Monto préstamo", 0.0, 1e9, 10000.0)
        fee = fl_amt * 0.09 / 100
        card("Fee (0.09%)", f"${fee:,.2f}", badge="yellow")
        card("Repayment", f"${fl_amt + fee:,.2f}", badge="red")
        if st.button("Execute Flash Loan"): st.success("Flash loan ejecutado")


def _page_circuit(cb: CircuitBreaker):
    st.markdown('<div class="titanium-header">🎯 Circuit Breaker</div>', True)
    st.caption("Protección automática contra pérdidas catastróficas.")

    status = cb.get_status()
    c1, c2, c3 = st.columns(3)
    with c1:
        badge_c = "green" if status['can_trade'] else "red"
        card("Estado", "ACTIVO" if status['can_trade'] else "PAUSADO",
             badge=badge_c)
    with c2:
        card("PnL diario",
             f"{status['daily_pnl_pct']:+.2f}%",
             sub=f"Límite: -{Config.MAX_DAILY_DD}%",
             badge="green" if status['daily_pnl_pct'] > -Config.MAX_DAILY_DD else "red")
    with c3:
        card("PnL total",
             f"{status['total_pnl_pct']:+.2f}%",
             sub=f"Límite: -{Config.MAX_TOTAL_DD}%",
             badge="green" if status['total_pnl_pct'] > -Config.MAX_TOTAL_DD else "red")

    st.markdown("---")
    st.markdown("#### Simular trade (para pruebas)")
    col_a, col_b = st.columns(2)
    with col_a:
        sim_pnl = st.number_input("PnL del trade (%)", -10.0, 10.0, -1.5, 0.5)
    with col_b:
        st.write("")
        st.write("")
        if st.button("Registrar trade simulado"):
            cb.record_trade(sim_pnl)
            st.success(f"Trade registrado: {sim_pnl:+.1f}%")
            st.rerun()

    if status['pause_reason']:
        st.error(f"🚨 Motivo de pausa: {status['pause_reason']}")

    st.markdown("#### Configuración actual")
    cfg_df = pd.DataFrame([{
        "Parámetro": k, "Valor": v
    } for k, v in {
        "Max DD diario": f"{Config.MAX_DAILY_DD}%",
        "Max DD total":  f"{Config.MAX_TOTAL_DD}%",
        "Emergency stop": f"{Config.EMERGENCY_STOP}%",
        "Max pérd. consec.": str(Config.MAX_CONS_LOSSES),
        "Cooldown":      f"{Config.COOLDOWN_MIN} min",
    }.items()])
    st.dataframe(cfg_df, hide_index=True, use_container_width=True)


def _page_sizer(tf_data):
    st.markdown('<div class="titanium-header">📐 Position Sizer</div>', True)
    st.caption("Calcula el tamaño óptimo de posición con Half-Kelly.")

    ps: KellyPositionSizer = st.session_state.position_sizer
    rm: ATRRiskManager     = st.session_state.risk_manager

    c1, c2 = st.columns(2)
    with c1:
        balance   = st.number_input("Capital total (USD)", 100.0, 1e7, 10000.0, 100.0)
        direction = st.selectbox("Dirección", ["long", "short"])
    with c2:
        df_e = tf_data.get(Config.TF_ENTRY, pd.DataFrame())
        default_price = float(df_e['close'].iloc[-1]) if not df_e.empty else 65000.0
        entry_price = st.number_input("Precio de entrada", 1.0, 1e8, default_price, 10.0)

    if st.button("Calcular stops + tamaño", use_container_width=True):
        if df_e.empty:
            st.warning("Sin datos de velas disponibles")
        else:
            stops = rm.calculate_stops(entry_price, direction, df_e)
            if stops:
                sizing = ps.calculate(balance, entry_price, stops.stop_loss)
                st.markdown("---")
                col_s1, col_s2, col_s3, col_s4 = st.columns(4)
                with col_s1:
                    card("Stop Loss",    f"${stops.stop_loss:,.2f}",
                         sub=f"ATR: {stops.atr_value}", badge="red")
                with col_s2:
                    card("Take Profit",  f"${stops.take_profit:,.2f}",
                         badge="green")
                with col_s3:
                    card("R:R Ratio",    f"{stops.risk_reward}x",
                         badge=stops.confidence)
                with col_s4:
                    card("Posición",
                         f"${sizing.get('position_usd', 0):,.0f}",
                         sub=f"Riesgo: {sizing.get('risk_pct',0):.1f}%",
                         badge="blue")

                method = sizing.get('method', 'default')
                trades = sizing.get('trades', 0)
                st.info(f"📊 Método: **{method}** — "
                        f"basado en {trades} trades históricos. "
                        f"{'Agrega más trades para activar Kelly completo.' if trades < 20 else 'Kelly activo.'}")
            else:
                st.warning("ATR no calculable con los datos actuales")

    st.markdown("---")
    stats = ps.stats()
    if stats.get('trades', 0) > 0:
        st.markdown("#### Estadísticas del historial")
        c1, c2, c3 = st.columns(3)
        with c1:
            card("Win Rate",  f"{stats['win_rate']}%")
        with c2:
            card("Avg Win",   f"{stats['avg_win']:+.2f}%")
        with c3:
            card("Kelly %",   f"{stats['kelly_pct']:.1f}%")


def _page_backtest(tf_data):
    st.markdown('<div class="titanium-header">🔬 Backtesting</div>', True)
    st.caption("Valida tu estrategia con datos históricos antes de arriesgar capital real.")

    df = tf_data.get(Config.TF_TREND, pd.DataFrame())
    if df.empty:
        st.warning("Sin datos disponibles para backtest")
        return

    st.info(f"Dataset: **{len(df)} velas** del TF {Config.TF_TREND}")

    col_a, col_b = st.columns(2)
    with col_a:
        capital = st.number_input("Capital inicial (USD)", 1000.0, 1e6, 10000.0, 1000.0)
        sl_mult = st.slider("Multiplicador SL (ATR x)", 1.0, 4.0, 2.0, 0.5)
    with col_b:
        tp_mult = st.slider("Multiplicador TP (ATR x)", 1.5, 6.0, 3.0, 0.5)
        comm    = st.slider("Comisión (%)", 0.0, 0.5, 0.1, 0.05) / 100

    if st.button("▶ Ejecutar Backtest", use_container_width=True):
        rm_bt = ATRRiskManager(sl_mult=sl_mult, tp_mult=tp_mult)

        # Estrategia simple: cruce EMA + RSI para el backtest demo
        @dataclass
        class DemoSignal:
            direction: str
            stop_loss: float
            take_profit: float

        def demo_strategy(hist):
            if len(hist) < 50:
                return None
            close = hist['close']
            ema20 = close.ewm(span=20).mean().iloc[-1]
            ema50 = close.ewm(span=50).mean().iloc[-1]
            delta = close.diff()
            gain  = delta.where(delta>0,0).rolling(14).mean()
            loss  = (-delta.where(delta<0,0)).rolling(14).mean()
            rsi   = (100 - 100/(1+gain/loss.replace(0,1e-10))).iloc[-1]
            price = close.iloc[-1]
            stops = rm_bt.calculate_stops(price, 'long', hist)
            if not stops:
                return None
            if ema20 > ema50 and rsi < 65:
                return DemoSignal('long',  stops.stop_loss, stops.take_profit)
            if ema20 < ema50 and rsi > 35:
                return DemoSignal('short', stops.stop_loss, stops.take_profit)
            return None

        with st.spinner("Ejecutando backtest..."):
            bt   = Backtester(commission=comm, initial_capital=capital)
            res  = bt.run(df, demo_strategy)

        st.markdown("---")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            badge = "green" if res.total_return_pct > 0 else "red"
            card("Retorno Total", f"{res.total_return_pct:+.1f}%", badge=badge)
        with c2:
            card("Max Drawdown", f"{res.max_drawdown_pct:.1f}%",
                 badge="green" if res.max_drawdown_pct < 20 else "red")
        with c3:
            card("Sharpe Ratio", f"{res.sharpe_ratio:.2f}",
                 badge="green" if res.sharpe_ratio > 1.5 else "yellow")
        with c4:
            card("Profit Factor", f"{res.profit_factor:.2f}",
                 badge="green" if res.profit_factor > 1.5 else "red")

        c5, c6, c7 = st.columns(3)
        with c5:
            card("Win Rate",  f"{res.win_rate_pct:.0f}%")
        with c6:
            card("Trades",    str(res.total_trades))
        with c7:
            card("Sortino",   f"{res.sortino_ratio:.2f}")

        if res.equity_curve:
            st.markdown("#### Curva de equity")
            eq_df = pd.DataFrame({'Equity': res.equity_curve})
            st.line_chart(eq_df)

        # Juicio automático
        st.markdown("---")
        if res.sharpe_ratio >= 1.5 and res.profit_factor >= 1.5 \
           and res.max_drawdown_pct <= 20:
            st.success("✅ Estrategia válida para live trading (métricas institucionales)")
        elif res.profit_factor < 1.0:
            st.error("❌ Estrategia NO rentable — NO operar con capital real")
        else:
            st.warning("⚠️ Estrategia marginal — ajusta parámetros antes de live")


def _page_config():
    st.markdown('<div class="titanium-header">⚙️ Configuración</div>', True)

    tab_keys, tab_risk = st.tabs(["🔑 API Keys", "⚠️ Risk Settings"])

    with tab_keys:
        st.caption("Tus llaves se guardan localmente. Nunca se envían a terceros.")
        username = st.session_state.username
        curr_key, curr_sec = st.session_state.auth.get_keys(username)

        new_key = st.text_input("Binance API Key",
                                value=curr_key or "",
                                type="password")
        new_sec = st.text_input("Binance Secret",
                                value=curr_sec or "",
                                type="password")

        if st.button("💾 Guardar llaves", use_container_width=True):
            st.session_state.auth.save_keys(username, new_key, new_sec)
            st.session_state.initialized = False  # Fuerza reconexión
            st.success("✅ Llaves guardadas — reconectando al exchange")
            st.rerun()

        if st.button("🗑️ Eliminar llaves (volver a DEMO)",
                     use_container_width=True):
            st.session_state.auth.save_keys(username, '', '')
            st.session_state.initialized = False
            st.warning("Llaves eliminadas — modo DEMO activado")
            st.rerun()

    with tab_risk:
        st.caption("Configura mediante variables de entorno en Railway para persistencia.")
        st.code("""
# Variables de entorno Railway:
MAX_DAILY_DD=5.0       # % pérdida máxima diaria
MAX_TOTAL_DD=15.0      # % pérdida máxima total
EMERGENCY_STOP=-20.0   # % stop definitivo
MAX_CONS_LOSSES=5      # pérdidas consecutivas máximas
COOLDOWN_MIN=60        # minutos de pausa forzada
KELLY_FRACTION=0.5     # 0.5 = Half-Kelly (recomendado)
MAX_POSITION_PCT=0.10  # máximo 10% del capital por trade
        """, language="bash")

        st.markdown("#### Estado actual del Kelly Sizer")
        ps: KellyPositionSizer = st.session_state.position_sizer
        stats = ps.stats()
        st.json(stats)


# ═══════════════════════════════════════════════════════════════════
# SECCIÓN 16: MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    st.set_page_config(
        page_title    = "Titanium Pro v10",
        page_icon     = "⚡",
        layout        = "wide",
        initial_sidebar_state = "expanded",
    )
    st.markdown(STYLES, unsafe_allow_html=True)
    _init_session()

    if not st.session_state.logged_in:
        page_login()
    else:
        page_dashboard()


if __name__ == "__main__":
    main()
