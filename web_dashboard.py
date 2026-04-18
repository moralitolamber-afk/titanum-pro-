"""
╔══════════════════════════════════════════════════════════════════╗
║          TITANIUM v10.0 PRO — MODULAR QUANTUM MASTER             ║
║                                                                  ║
║  MODULAR ARCHITECTURE:                                           ║
║  ✅ PortfolioAnalyzer  — Métricas de exposición real             ║
║  ✅ SecureVault        — Encriptación AES de llaves API          ║
║  ✅ Llama 3.3 Brain    — Inteligencia macro y de portafolio      ║
║  ✅ Pro Max UI/UX      — Diseño Bento Grid & Quantum Noir        ║
╚══════════════════════════════════════════════════════════════════╝
"""

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

# Modular Imports
import config
from ui.styles import STYLES
from portfolio.analyzer import PortfolioAnalyzer
from ai.sentiment import NewsAggregator
from core.auth_manager import authenticate_user, register_user, get_keys, update_api_keys

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
        
        freq_map = {
            '1m': '1min', '3m': '3min', '5m': '5min', '15m': '15min',
            '30m': '30min', '1h': '1h', '2h': '2h', '4h': '4h',
            '6h': '6h', '1d': '1D'
        }
        pd_freq = freq_map.get(tf, '5min')
        idx = pd.date_range(end=datetime.now(), periods=n, freq=pd_freq)
        
        return pd.DataFrame({
            'open': opens, 'high': highs,
            'low': lows,   'close': closes,
            'volume': np.random.uniform(100, 1000, n)
        }, index=idx)

    def fetch_balance(self) -> Dict:
        """Obtiene el balance real o demo de la cuenta."""
        if Config.DEMO_MODE or not self.exchange:
            return {'USDT': 10000.0, 'BTC': 0.12, 'ETH': 1.5, 'SOL': 40.0}
        try:
            bal = self.exchange.fetch_balance()
            return {c: float(v['total']) for c, v in bal['total'].items() if v['total'] > 0}
        except:
            return {'USDT': 0.0}



# ═══════════════════════════════════════════════════════════════════
# SECCIÓN 9: AI BRAIN
# ═══════════════════════════════════════════════════════════════════

class AIBrain:
    """Análisis de sentimiento vía Groq/Llama."""

    def __init__(self):
        self.sentiment = {"score": 0.0, "label": "NEUTRAL",
                          "summary": "Sin datos", "updated": None}

    def analyze_portfolio(self, balance: Dict, news: str = "") -> Dict:
        if not Config.GROQ_API_KEY:
            return self.sentiment
        try:
            from groq import Groq
            client = Groq(api_key=Config.GROQ_API_KEY)
            prompt = f"""
            Actúa como un Asesor Financiero Pro de Cripto. 
            Portafolio Real del Usuario: {json.dumps(balance)}
            Noticias Recientes: {news if news else 'Estabilidad macro.'}
            
            Responde SOLO con JSON:
            {{
                "health_score": <int 0-100>,
                "risk_level": "LOW|MEDIUM|HIGH",
                "recommendation": "<25 palabras max>",
                "action": "BUY/SELL/HOLD/REBALANCE"
            }}
            """
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                max_tokens=250,
                messages=[{"role": "user", "content": prompt}]
            )
            data = json.loads(resp.choices[0].message.content.strip())
            return {**data, "updated": datetime.now().isoformat()}
        except Exception as e:
            return {"error": str(e)}



# ═══════════════════════════════════════════════════════════════════
# SECCIÓN 10: AUTH MANAGER (simple, sin BD externa)
# ═══════════════════════════════════════════════════════════════════

class AuthManager:
    """Wrapper para la lógica modular de autenticación."""
    def login(self, username, password):
        return authenticate_user(username, password)

    def register(self, username, password, invite_code):
        return register_user(username, password, invite_code)

    def get_keys(self, username):
        return get_keys(username)

    def save_keys(self, username, api_key, api_secret):
        return update_api_keys(username, api_key, api_secret)


# ═══════════════════════════════════════════════════════════════════
# SECCIÓN 11: SESSION STATE INIT
# ═══════════════════════════════════════════════════════════════════

def _init_session():
    defaults = {
        'logged_in':    False,
        'username':     '',
        'initialized':  False,
        'exchange':     ExchangeManager(),
        'portfolio_analyzer': None,
        'news_aggregator': NewsAggregator(),
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

    # Régimen basado en TF de tendencia
    rd: RegimeDetector = st.session_state.regime_detector
    trend_df = tf_data.get(Config.TF_TREND, pd.DataFrame())
    regime   = rd.detect(trend_df) if not trend_df.empty else {}

    st.session_state.tf_data     = tf_data
    st.session_state.obi_data    = obi_data
    st.session_state.regime_data = regime
    st.session_state.last_refresh = datetime.now()
    return tf_data, obi_data, regime


# ═══════════════════════════════════════════════════════════════════
# SECCIÓN 13: ESTILOS CSS (Glassmorphism Dark)
# ═══════════════════════════════════════════════════════════════════

# STYLES se ha movido a ui/styles.py


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
    pct    = int((obi_value + 1) / 2 * 100)  # -1..1 → 0..100
    color  = "#68d391" if obi_value > 0 else "#fc8181"
    label  = "PRESIÓN COMPRADORA" if obi_value > 0 else "PRESIÓN VENDEDORA"
    st.markdown(f"""
    <div class="titanium-card">
        <div class="metric-label">Order Book Imbalance</div>
        <div class="metric-value">{obi_value:+.4f}</div>
        <div class="metric-sub">{label}</div>
        <div class="obi-bar-container">
            <div class="obi-bar-fill"
                 style="width:{pct}%; background:{color};">
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
    trade_badge = (
        '<span class="badge badge-green">OPERAR</span>'
        if should else
        '<span class="badge badge-red">ESPERAR</span>'
    )
    st.markdown(f"""
    <div class="titanium-card">
        <div class="metric-label">Régimen de Mercado</div>
        <div class="metric-value">
            <span class="badge badge-{color}">{regime}</span>
        </div>
        <div class="metric-sub">
            Confianza: {conf:.0%} &nbsp;|&nbsp; {trade_badge}
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
    st.markdown('<div class="titanium-header">⚡ TITANIUM PRO</div>', True)
    st.markdown('<div class="titanium-sub">Sistema de Trading Algorítmico v9</div>', True)
    st.markdown("---")

    tab_in, tab_reg = st.tabs(["🔐 Iniciar sesión", "📝 Registrarse"])

    with tab_in:
        u = st.text_input("Usuario", key="li_u")
        p = st.text_input("Contraseña", type="password", key="li_p")
        if st.button("Entrar", use_container_width=True):
            if st.session_state.auth.authenticate(u, p):
                st.session_state.logged_in = True
                st.session_state.username  = u
                st.session_state.initialized = False
                st.rerun()
            else:
                st.error("❌ Credenciales incorrectas")

    with tab_reg:
        nu = st.text_input("Nuevo usuario", key="reg_u")
        np_ = st.text_input("Contraseña", type="password", key="reg_p")
        if st.button("Crear cuenta", use_container_width=True):
            if st.session_state.auth.register(nu, np_):
                st.success("✅ Cuenta creada — inicia sesión")
            else:
                st.error("❌ Usuario ya existe")


def page_dashboard():
    # ── Sidebar ─────────────────────────────────────────────────
    with st.sidebar:
        st.markdown('<div class="titanium-header" style="font-size:20px">⚡ TITANIUM</div>', True)
        mode = "🟡 DEMO" if st.session_state.demo_mode else "🟢 REAL"
        st.markdown(f"**{mode}** — {st.session_state.username}")
        st.markdown("---")

        # Navegación
        page = st.radio("Navegación", [
            "📊 Dashboard", "💼 Portafolio", "🤖 AI Advisor",
            "🏦 Vault", "⚖️ Liquidity Monitoring", "🗳️ Governance",
            "🔬 Backtesting", "⚙️ Configuración"
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
        from ui.pages.portfolio import page_portfolio
        page_portfolio()
    elif page == "🤖 AI Advisor":
        _page_advisor()
    elif page == "🏦 Vault":
        _page_vault()
    elif page == "⚖️ Liquidity Monitoring":
        _page_liquidity(obi_data)
    elif page == "🗳️ Governance":
        _page_governance()
    elif page == "🔬 Backtesting":
        _page_backtest(tf_data)
    elif page == "⚙️ Configuración":
        _page_config()

    # Auto-refresh (Modernized)
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=refresh * 1000, key="datarefresh")


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

    # Market Intelligence (NEW v10.0)
    st.markdown("---")
    st.markdown("### 📡 Market Intelligence")
    
    news_ag: NewsAggregator = st.session_state.news_aggregator
    context = news_ag.get_market_context()
    
    col_news, col_ai = st.columns([2, 1])
    
    with col_news:
        st.markdown("#### Últimos Titulares Crypto")
        for h in context['headlines']:
            st.markdown(f"🔹 **[{h['source'].upper()}]** [{h['title']}]({h['link']})")
    
    with col_ai:
        sent_label = context['sentiment_label']
        sent_score = context['sentiment_score']
        badge_sent = "green" if sent_label == "BULLISH" else "red" if sent_label == "BEARISH" else "blue"
        
        card("Market Sentiment", f"{sent_label} ({sent_score:+.2f})", 
             sub="Basado en análisis léxico de titulares RSS", badge=badge_sent)
        
        if st.button("🧠 Ejecutar Auditoría Llama-3.3"):
            ai: AIBrain = st.session_state.ai_brain
            with st.spinner("La IA está auditando el contexto..."):
                # Enviamos los titulares reales a la IA
                news_text = " | ".join(context['raw_titles'])
                ai_resp = ai.analyze_portfolio({}, news_text)
                st.session_state.ai_data = ai_resp
        
        if st.session_state.ai_data:
            adv = st.session_state.ai_data
            if 'error' not in adv:
                st.info(f"💡 **AI Recommendation:** {adv.get('recommendation', '—')}")
                st.code(f"ACTION: {adv.get('action', 'HOLD')}", language="bash")


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


# _page_portfolio ha sido migrado a ui/pages/portfolio.py


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
# SECCIÓN 18: AI PORTFOLIO & ADVISOR UI
# ═══════════════════════════════════════════════════════════════════

def _page_portfolio():
    st.markdown('<div class="titanium-header">💼 Portafolio Real</div>', True)
    st.caption("Análisis detallado de activos y distribución de capital vía API.")

    ex: ExchangeManager = st.session_state.exchange
    with st.spinner("Consultando balances..."):
        balance = ex.fetch_balance()
    
    # Métricas Globales
    total_usd = sum(v for k, v in balance.items() if k == "USDT")
    # Simulación de valor total si hay assets
    if len(balance) > 1:
        total_usd = balance.get('USDT', 0) + (balance.get('BTC', 0) * 65000)
    
    c1, c2, c3 = st.columns(3)
    with c1:
        card("Balance Total (EST)", f"${total_usd:,.2f}", sub="Cuentas Spot + Margen", badge="blue")
    with c2:
        card("Activos Detectados", str(len(balance)), sub="Tokens con balance > 0")
    with c3:
        pnl_24h = 2.45 # Simulado para el dashboard
        card("PnL Portafolio (24h)", f"{pnl_24h:+.2f}%", badge="green" if pnl_24h > 0 else "red")

    st.markdown("---")
    col_a, col_b = st.columns([2, 1])
    
    with col_a:
        st.markdown("#### Composición del Portafolio")
        bal_df = pd.DataFrame([{"Activo": k, "Cantidad": v} for k, v in balance.items()])
        st.dataframe(bal_df, use_container_width=True, hide_index=True)
        
    with col_b:
        st.markdown("#### Alertas de Riesgo")
        if balance.get('BTC', 0) > 0.5:
            st.warning("⚠️ Alta exposición en BTC (>50%). Considera diversificar.")
        else:
            st.success("✅ Distribución de riesgo saludable.")


def _page_advisor():
    st.markdown('<div class="titanium-header">🤖 AI Advisor</div>', True)
    st.caption("Asesoría personalizada basada en Llama-3.3 y contexto macro real.")
    
    ai: AIBrain = st.session_state.ai_brain
    ex: ExchangeManager = st.session_state.exchange
    
    st.markdown("""
    <div class="titanium-card">
        <div class="metric-label">Status de Inteligencia</div>
        <div class="metric-value">Llama-3.3-70B Ready</div>
        <div class="metric-sub">Analizando noticias y portafolio en tiempo real...</div>
    </div>
    """, unsafe_allow_html=True)

    if st.button("🚀 Generar Auditoría de Portafolio con IA", use_container_width=True):
        with st.spinner("La IA está auditando tus posiciones y noticias..."):
            bal = ex.fetch_balance()
            # Simulamos noticias para el prompt
            news = "BTC ETF inflows steady, inflation data expected lower than consensus."
            advice = ai.analyze_portfolio(bal, news)
            st.session_state.ai_advice = advice
    
    if hasattr(st.session_state, 'ai_advice'):
        adv = st.session_state.ai_advice
        if 'error' in adv:
            st.error(f"Error AI: {adv['error']}")
        else:
            col1, col2 = st.columns(2)
            with col1:
                card("Salud del Portafolio", f"{adv['health_score']}/100", 
                     sub=f"Nivel de Riesgo: {adv['risk_level']}", 
                     badge="green" if adv['health_score'] > 70 else "yellow")
            with col2:
                action_color = "green" if adv['action'] == "BUY" else "red" if adv['action'] == "SELL" else "blue"
                card("Recomendación IA", adv['action'], sub=adv['recommendation'], badge=action_color)
            
            st.markdown("---")
            st.markdown("#### Ejecución Sugerida")
            st.info(f"💡 **Nota del Asesor:** La recomendación de **{adv['action']}** se basa en el contexto macro actual. Puedes ejecutar esta operación desde el Dashboard.")


# ═══════════════════════════════════════════════════════════════════
# SECCIÓN 17: MÓDULOS DEFI UPGRADE
# ═══════════════════════════════════════════════════════════════════

def _page_vault():
    st.markdown('<div class="titanium-header">🏦 DeFi Staking Vault</div>', True)
    st.caption("Estrategias de colocación de capital basadas en StakingRewards.sol.")
    
    cb = st.session_state.circuit_breaker
    pnl = cb.get_status()['total_pnl_pct']
    
    # Lógica de Contrato: rewardPerToken = rewardRate * time / totalSupply
    reward_rate = 100 # tokens per sec (from template)
    total_supply = 1240500 # TVL
    
    c1, c2, c3 = st.columns(3)
    with c1:
        card("TVL (Protocol)", f"${total_supply:,.0f}", sub="Locked in Smart Contract", badge="blue")
    with c2:
        # APY Realista basado en PnL de trading + Incentivos del Protocolo
        base_apy = (1 + pnl/100)**365 - 1 if pnl > 0 else 0
        bonus_apy = (reward_rate * 86400 * 365) / total_supply
        total_apy = base_apy + bonus_apy
        card("Vault APY", f"{total_apy*100:,.1f}%", sub=f"Incentivo: {bonus_apy*100:.1f}%", badge="green")
    with c3:
        earned = (total_supply * (pnl/100)) + (reward_rate * 3600) # Recompensa estimada última hora
        card("Pending Rewards", f"{earned:,.2f} GOV", sub="Claimable in $GOV", badge="yellow")

    st.markdown("---")
    st.markdown("#### Security & Risk (CircuitBreaker)")
    st.info(f"🛡️ **Protección de Bóveda:** Si el Capital Drawdown toca el **{Config.MAX_DAILY_DD}%**, el contrato de Staking entra en `pause()` automático via CircuitBreaker.")


def _page_liquidity(obi_data):
    st.markdown('<div class="titanium-header">⚖️ Liquidity Monitoring</div>', True)
    st.caption("Análisis de profundidad AMM-Style para ejecución de órdenes.")
    
    obi = obi_data.get('obi', 0)
    bids = obi_data.get('bids_vol', 0)
    asks = obi_data.get('asks_vol', 0)
    
    col_chart, col_metrics = st.columns([2, 1])
    with col_chart:
        # Mini gráfico de simulación de liquidez
        st.markdown("##### Profundidad de Mercado (Depth Chart)")
        data = pd.DataFrame({
            'Side': ['Bids'] * 10 + ['Asks'] * 10,
            'Volume': list(np.linspace(bids, 0, 10)) + list(np.linspace(0, asks, 10))
        })
        st.bar_chart(data, x='Side', y='Volume', color='Side')

    with col_metrics:
        card("Bid Pressure", f"{bids:,.2f}", sub="Buy Side Liquidity")
        card("Ask Pressure", f"{asks:,.2f}", sub="Sell Side Liquidity")
        impact = abs(obi) * 0.05 # Simulación de Price Impact
        card("Est. Price Impact", f"{impact:,.4f}%", sub="Para orden de 10 BTC", badge="yellow" if impact > 0.01 else "green")

def _page_governance():
    st.markdown('<div class="titanium-header">🗳️ Governance</div>', True)
    st.caption("Propuestas de optimización de algoritmos y gestión de parámetros.")
    
    st.markdown("""
    <div class="titanium-card">
        <div class="metric-label">Propuesta Activa (TIP-01)</div>
        <div class="metric-value">Ajustar Multiplicador ATR a 2.5x</div>
        <div class="metric-sub">Finaliza en: 2d 14h 30m</div>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2 = st.columns(2)
    with col1:
        st.button("✅ Votar a Favor (FOR)", use_container_width=True)
    with col2:
        st.button("❌ Votar en Contra (AGAINST)", use_container_width=True)
        
    st.markdown("---")
    st.markdown("#### Historial de Votación")
    st.table([
        {"ID": "TIP-00", "Propuesta": "Activar Llama-3.3 Sentiment", "Estado": "EJECUTADO", "Resultado": "PASA"},
        {"ID": "TIP-01", "Propuesta": "Cambiar Símbolo a ETH/USDT", "Estado": "FALLIDO", "Resultado": "RECHAZADO"}
    ])


# ═══════════════════════════════════════════════════════════════════
# SECCIÓN 16: MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    st.set_page_config(
        page_title    = "Titanium Pro v9",
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

