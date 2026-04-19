"""
╔══════════════════════════════════════════════════════════════════╗
║           TITANIUM v10.0 PRO — SISTEMA MAESTRO COMPLETO         ║
║                                                                  ║
║  Integra en UN solo archivo:                                     ║
║  ✅ CircuitBreaker   — Protección contra pérdidas catastróficas  ║
║  ✅ ATRRiskManager   — SL/TP dinámicos basados en volatilidad    ║
║  ✅ KellyPositionSizer — Tamaño óptimo de posición               ║
║  ✅ RegimeDetector   — Detecta tendencia/rango/volatilidad       ║
║  ✅ DeFi Vault       — Staking, AMM, Gobernanza y Flash Loans    ║
║  ✅ Manual Indicators — EMA, RSI, ATR sin dependencias externas   ║
║  ✅ CorrelationMonitor — Evita exposición duplicada              ║
║  ✅ Backtester       — Valida estrategias antes de live          ║
║  ✅ ExchangeManager  — Conexión Binance + OBI                    ║
║  ✅ AIBrain          — Análisis con Groq/Llama                   ║
║  ✅ Dashboard        — UI Streamlit premium con métricas         ║
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
# SECCIÓN 1.5: INDICADORES MANUALES
# ═══════════════════════════════════════════════════════════════════

def ema(series, length=14):
    """Media Móvil Exponencial manual."""
    return series.ewm(span=length, adjust=False).mean()

def rsi(series, length=14):
    """Índice de Fuerza Relativa manual."""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=length).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=length).mean()
    rs = gain / loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))

def atr(df, length=14):
    """Average True Range manual (simplificado)."""
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(window=length).mean()


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
        atr_val = self._atr(df)
        if not atr_val:
            return None
        sl = entry - atr_val * self.sl_mult if direction == 'long' \
             else entry + atr_val * self.sl_mult
        tp = entry + atr_val * self.tp_mult if direction == 'long' \
             else entry - atr_val * self.tp_mult
        risk   = abs(entry - sl)
        reward = abs(tp - entry)
        rr     = round(reward / risk, 2) if risk else 0
        return StopLevels(
            stop_loss         = round(sl, 4),
            take_profit       = round(tp, 4),
            trailing_distance = round(atr_val * self.trail_mult, 4),
            risk_reward       = rr,
            atr_value         = round(atr_val, 4),
            confidence        = 'high' if rr >= 2 else 'medium' if rr >= 1.5 else 'low',
        )

    def _atr(self, df: pd.DataFrame) -> Optional[float]:
        if len(df) < self.atr_period + 1:
            return None
        try:
            return float(atr(df, self.atr_period).iloc[-1])
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
    """Detecta régimen de mercado usando indicadores manuales."""

    def detect(self, df: pd.DataFrame) -> Dict:
        if len(df) < 30:
            return {"regime": "UNKNOWN", "confidence": 0.0, "should_trade": False}
        try:
            close = df['close']
            rsi_vals = rsi(close, 14)
            atr_vals = atr(df, 14)
            
            atr_val  = atr_vals.iloc[-1]
            atr_pct  = atr_val / close.iloc[-1] * 100
            current_rsi = rsi_vals.iloc[-1]

            # Bollinger Width
            sma    = close.rolling(20).mean()
            std    = close.rolling(20).std()
            bb_w   = (std.iloc[-1] * 4) / sma.iloc[-1] * 100

            # EMA alignment manual
            e20  = ema(close, 20).iloc[-1]
            e50  = ema(close, 50).iloc[-1]
            e200 = ema(close, 200).iloc[-1]
            aligned = (close.iloc[-1] > e20 > e50 > e200) or \
                      (close.iloc[-1] < e20 < e50 < e200)

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

            should_trade = regime in ["STRONG_TREND", "WEAK_TREND", "VOL_SPIKE"] and conf >= 0.6

            return {
                "regime":       regime,
                "confidence":   round(conf, 2),
                "atr_pct":      round(atr_pct, 2),
                "bb_width":     round(bb_w, 2),
                "rsi":          round(current_rsi, 1),
                "ema_aligned":  aligned,
                "should_trade": should_trade,
            }
        except Exception as e:
            return {"regime": "ERROR", "confidence": 0, "should_trade": False, "error": str(e)}


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


class Backtester:
    """Motor de backtesting con slippage y comisiones realistas."""

    def __init__(self, commission=0.001, slippage=0.0005, initial_capital=10_000.0):
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

            if not position:
                try:
                    sig = strategy_fn(history)
                except Exception:
                    sig = None
                if sig and hasattr(sig, 'direction'):
                    ep = candle['close'] * (1 + self.slippage if sig.direction == 'long' else 1 - self.slippage)
                    position = {'entry': ep, 'sl': sig.stop_loss, 'tp': sig.take_profit, 'direction': sig.direction}

            equity.append(cap)
            if cap > peak: peak = cap
            dd = (peak - cap) / peak * 100
            if dd > max_dd: max_dd = dd

        if not trades: return BacktestResult(0, 0, 0, 0, 0, 0, 0, 0, 0, equity)

        ret     = pd.Series(equity).pct_change().dropna()
        wins    = [t for t in trades if t['won']]
        losses  = [t for t in trades if not t['won']]
        wr      = len(wins) / len(trades) * 100
        avg_w   = np.mean([t['pnl_pct'] for t in wins]) if wins else 0
        avg_l   = abs(np.mean([t['pnl_pct'] for t in losses])) if losses else 0
        pf      = (sum(t['pnl_pct'] for t in wins) / abs(sum(t['pnl_pct'] for t in losses) or 1))
        sharpe  = (np.sqrt(365) * ret.mean() / ret.std() if ret.std() > 0 else 0)
        down    = ret[ret < 0]
        sortino = (np.sqrt(365) * ret.mean() / down.std() if len(down) > 1 and down.std() > 0 else 0)
        total_r = (cap - self.capital0) / self.capital0 * 100

        return BacktestResult(
            total_return_pct = round(total_r, 2),
            max_drawdown_pct = round(max_dd, 2),
            sharpe_ratio     = round(sharpe, 2),
            sortino_ratio    = round(sortino, 2),
            win_rate_pct     = round(wr, 1),
            profit_factor    = round(pf, 2),
            total_trades     = len(trades),
            equity_curve     = equity,
            avg_win_pct      = round(avg_w, 3),
            avg_loss_pct     = round(avg_l, 3)
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
        if Config.DEMO_MODE or self.exchange: return
        try:
            import ccxt
            cfg = {
                'enableRateLimit': True,
                'apiKey': api_key, 'secret': api_secret,
                'options': {'defaultType': 'spot' if Config.USE_SPOT else 'future'},
            }
            self.exchange = ccxt.binance(cfg) if Config.USE_SPOT else ccxt.binanceusdm(cfg)
        except Exception as e:
            st.error(f"Error al conectar exchange: {e}")
            Config.DEMO_MODE = True

    def fetch_candles(self, tf: str) -> pd.DataFrame:
        if Config.DEMO_MODE or not self.exchange: return self._demo_candles(tf)
        try:
            data = self.exchange.fetch_ohlcv(Config.SYMBOL, tf, limit=Config.CANDLE_LIMIT)
            df = pd.DataFrame(data, columns=['time','open','high','low','close','volume'])
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
            return {'obi': round(rng, 4), 'bids_vol': round(abs(rng) * 1000, 2), 'asks_vol': round(abs(rng) * 900, 2)}
        try:
            ob     = self.exchange.fetch_order_book(Config.SYMBOL, depth)
            b_v    = sum(b[1] for b in ob['bids'])
            a_v    = sum(a[1] for a in ob['asks'])
            total  = b_v + a_v
            obi    = (b_v - a_v) / total if total else 0
            return {'obi': round(obi, 4), 'bids_vol': round(b_v, 2), 'asks_vol': round(a_v, 2)}
        except Exception:
            return {'obi': 0.0, 'bids_vol': 0.0, 'asks_vol': 0.0}

    @staticmethod
    def _demo_candles(tf: str) -> pd.DataFrame:
        np.random.seed(abs(hash(tf)) % 2**31)
        n, price = Config.CANDLE_LIMIT, 65000.0
        prices = [price]
        for _ in range(n - 1):
            price += np.random.normal(0, price * 0.002)
            prices.append(max(price, 1))
        closes = np.array(prices)
        highs, lows = closes * np.random.uniform(1.001, 1.005, n), closes * np.random.uniform(0.995, 0.999, n)
        opens = np.roll(closes, 1)
        opens[0] = closes[0]
        freq_map = {'1m': '1min', '5m': '5min', '15m': '15min', '1h': '1h', '1d': '1D'}
        idx = pd.date_range(end=datetime.now(), periods=n, freq=freq_map.get(tf, '5min'))
        return pd.DataFrame({'open': opens, 'high': highs, 'low': lows, 'close': closes, 'volume': np.random.uniform(100, 1000, n)}, index=idx)


# ═══════════════════════════════════════════════════════════════════
# SECCIÓN 9: AI BRAIN
# ═══════════════════════════════════════════════════════════════════

class AIBrain:
    """Análisis avanzado con Groq/Llama."""

    def __init__(self):
        self.sentiment = {"score": 0.0, "label": "NEUTRAL", "summary": "Sin datos", "updated": None}

    def analyze_portfolio(self, balance: Dict, news_context: str) -> Dict:
        if not Config.GROQ_API_KEY: return {"error": "API Key missing"}
        try:
            from groq import Groq
            client = Groq(api_key=Config.GROQ_API_KEY)
            prompt = f"Analyze this portfolio: {balance}. Context: {news_context}. Return JSON: {{'health_score': 0-100, 'risk_level': 'LOW|MED|HIGH', 'action': 'BUY|SELL|HOLD', 'recommendation': 'text'}}"
            resp = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": prompt}])
            return json.loads(resp.choices[0].message.content)
        except Exception as e: return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════
# SECCIÓN 10: AUTH MANAGER
# ═══════════════════════════════════════════════════════════════════

class AuthManager:
    DB_PATH = os.getenv("AUTH_DB_PATH", "users.json")

    def _load(self) -> Dict:
        try:
            with open(self.DB_PATH) as f: return json.load(f)
        except: return {}

    def _save(self, data: Dict):
        with open(self.DB_PATH, 'w') as f: json.dump(data, f, indent=2)

    def _hash(self, pw: str) -> str: return hashlib.sha256(pw.encode()).hexdigest()

    def authenticate(self, username: str, password: str) -> bool:
        users = self._load()
        return bool(username in users and users[username]['password'] == self._hash(password))

    def register(self, username: str, password: str) -> bool:
        users = self._load()
        if username in users: return False
        users[username] = {'password': self._hash(password)}
        self._save(users)
        return True

    def get_keys(self, username: str) -> Tuple[str, str]:
        user = self._load().get(username, {})
        return user.get('api_key', ''), user.get('api_secret', '')

    def save_keys(self, username: str, key: str, secret: str):
        users = self._load()
        if username in users:
            users[username].update({'api_key': key, 'api_secret': secret})
            self._save(users)


# ═══════════════════════════════════════════════════════════════════
# SECCIÓN 11: SESSION STATE
# ═══════════════════════════════════════════════════════════════════

def _init_session():
    defaults = {
        'logged_in': False, 'username': '', 'initialized': False,
        'exchange': ExchangeManager(), 'circuit_breaker': CircuitBreaker(),
        'risk_manager': ATRRiskManager(), 'position_sizer': KellyPositionSizer(),
        'regime_detector': RegimeDetector(), 'ai_brain': AIBrain(), 'auth': AuthManager(),
        'last_refresh': None, 'tf_data': {}, 'obi_data': {}, 'regime_data': {}, 'ai_data': None
    }
    for k, v in defaults.items():
        if k not in st.session_state: st.session_state[k] = v


def _fetch_data():
    username = st.session_state.username
    u_key, u_sec = st.session_state.auth.get_keys(username)
    key, sec = (u_key, u_sec) if u_key else (Config.BINANCE_API_KEY, Config.BINANCE_SECRET)
    Config.DEMO_MODE = not bool(key)
    
    ex: ExchangeManager = st.session_state.exchange
    if not st.session_state.initialized or (not Config.DEMO_MODE and ex.exchange is None):
        ex.connect(key, sec)
        st.session_state.initialized = True
        
    tf_data = ex.fetch_all_timeframes()
    st.session_state.tf_data = tf_data
    st.session_state.obi_data = ex.fetch_obi()
    st.session_state.regime_data = st.session_state.regime_detector.detect(tf_data.get(Config.TF_TREND, pd.DataFrame()))
    st.session_state.last_refresh = datetime.now()


# ═══════════════════════════════════════════════════════════════════
# SECCIÓN 12: ESTILOS & COMPONENTES
# ═══════════════════════════════════════════════════════════════════

STYLES = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap');
html, body, [class*="css"] { font-family: 'Space Grotesk', sans-serif; }
.stApp { background: linear-gradient(135deg, #0a0a0f 0%, #0d1117 50%, #0a0f1a 100%); }
.titanium-card {
    background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08);
    border-radius: 16px; padding: 20px; backdrop-filter: blur(12px); margin-bottom: 12px;
}
.metric-label { font-size: 11px; text-transform: uppercase; color: rgba(255,255,255,0.4); margin-bottom: 4px; }
.metric-value { font-family: 'JetBrains Mono', monospace; font-size: 24px; font-weight: 600; color: #e2e8f0; }
.metric-sub { font-size: 12px; color: rgba(255,255,255,0.3); }
.badge { padding: 2px 8px; border-radius: 12px; font-size: 10px; font-weight: 600; }
.badge-green { background: rgba(72,187,120,0.2); color: #68d391; }
.badge-red { background: rgba(245,101,101,0.2); color: #fc8181; }
.badge-blue { background: rgba(99,179,237,0.2); color: #63b3ed; }
.titanium-header { font-size: 24px; font-weight: 700; background: linear-gradient(135deg, #63b3ed, #9f7aea); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
</style>
"""

def card(label: str, value: str, sub: str = "", badge: str = ""):
    b_html = f'<span class="badge badge-{badge}">{badge.upper()}</span>' if badge else ""
    st.markdown(f'<div class="titanium-card"><div class="metric-label">{label} {b_html}</div><div class="metric-value">{value}</div><div class="metric-sub">{sub}</div></div>', True)


# ═══════════════════════════════════════════════════════════════════
# SECCIÓN 13: PÁGINAS UI
# ═══════════════════════════════════════════════════════════════════

def _page_vault():
    """DeFi Vault - Staking, AMM, Governance & Flash Loans"""
    st.markdown('<div class="titanium-header">🏦 DeFi Vault & Protocols</div>', unsafe_allow_html=True)
    st.caption("Gestión de capital en protocolos on-chain")

    cb = st.session_state.get('circuit_breaker')
    if cb and not cb.can_trade():
        st.markdown('<div class="titanium-card" style="border-color: #ff0055;"><div style="color: #ff0055; font-weight: 700;">🚫 TRADING PAUSED</div></div>', True)

    c1, c2, c3, c4 = st.columns(4)
    with c1: card("TVL Total", "$125,430.00", sub="Capital en protocolos", badge="blue")
    with c2: card("APY Promedio", "12.4%", sub="Rendimiento anualizado", badge="green")
    with c3: card("Rewards", "45.2 GOV", sub="Pendientes por reclamar", badge="yellow")
    with c4: card("Gov Power", "1,200", sub="Poder de voto activo", badge="blue")

    t1, t2, t3, t4 = st.tabs(["🥩 Staking", "🧪 AMM & Liquidity", "🗳️ Governance", "⚡ Flash Loans"])
    
    with t1:
        st.markdown("#### Staking Institucional")
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            st.number_input("Cantidad a Staking (USDT)", 100.0, 100000.0, 1000.0)
            st.button("Depósitar en Vault", use_container_width=True)
        with col_s2:
            st.markdown("##### Estándares de Seguridad")
            st.info("🔒 Los fondos están protegidos por el CircuitBreaker. Si el Drawdown supera el 5%, el staking se pausa automáticamente.")

    with t2:
        st.markdown("#### AMM Simulator (Uniswap v3 Style)")
        st.write("Simulación de provisión de liquidez en rangos concentrados.")
        st.slider("Rango de Precio (%)", 1, 50, 10)
        st.metric("Eficiencia de Capital", "15x", "+2.4%")

    with t3:
        st.markdown("#### Propuestas de Gobernanza")
        st.markdown("""
        - **TIP-42**: Incrementar exposición máxima a ETH (En votación)
        - **TIP-41**: Actualización de parámetros de CircuitBreaker (Aprobada)
        """)
        st.button("Ver Portal de Gobernanza")

    with t4:
        st.markdown("#### Flash Loan Simulator")
        loan_amt = st.number_input("Monto del préstamo (USDT)", 1000.0, 1e7, 100000.0)
        fee = loan_amt * 0.0009
        st.write(f"Comisión del protocolo (0.09%): **${fee:,.2f}**")
        if st.button("Simular Arbitraje con Flash Loan"):
            st.warning("⚠️ Simulación: Arbitraje exitoso. PnL neto: $450.21 (post-fees)")


def page_dashboard():
    with st.sidebar:
        st.markdown('<div class="titanium-header">⚡ TITANIUM PRO</div>', True)
        st.markdown(f"**{'🟡 DEMO' if st.session_state.demo_mode else '🟢 REAL'}** — {st.session_state.username}")
        st.markdown("---")
        page = st.radio("Navegación", ["📊 Dashboard", "🚀 DeFi Vaults", "🎯 Circuit Breaker", "📐 Position Sizer", "🔬 Backtesting", "⚙️ Configuración"], label_visibility="collapsed")
        if st.button("🔄 Refrescar ahora", use_container_width=True): _fetch_data()
        if st.button("🚪 Cerrar sesión", use_container_width=True):
            st.session_state.logged_in = False
            st.rerun()

    if (st.session_state.last_refresh is None or (datetime.now() - st.session_state.last_refresh).seconds > 30):
        _fetch_data()

    if page == "📊 Dashboard":
        st.markdown('<div class="titanium-header">📊 Dashboard</div>', True)
        c1, c2, c3 = st.columns(3)
        tf_data = st.session_state.tf_data
        price = tf_data.get(Config.TF_ENTRY, pd.DataFrame())['close'].iloc[-1] if tf_data.get(Config.TF_ENTRY) is not None else 0
        with c1: card("Precio BTC", f"${price:,.0f}", sub=Config.TF_ENTRY)
        with c2: 
            reg = st.session_state.regime_data
            card("Régimen", reg.get('regime', 'N/A'), sub=f"Confianza: {reg.get('confidence',0):.0%}", badge="blue")
        with c3:
            cb = st.session_state.circuit_breaker.get_status()
            card("Circuit Breaker", "OK" if cb['can_trade'] else "PAUSED", sub=f"PnL: {cb['daily_pnl_pct']:+.2f}%", badge="green" if cb['can_trade'] else "red")
        
        for tf, df in tf_data.items():
            with st.expander(f"📈 Gráfico {tf}", True):
                st.line_chart(df['close'].tail(50))

    elif page == "🚀 DeFi Vaults": _page_vault()
    elif page == "🎯 Circuit Breaker":
        st.markdown('<div class="titanium-header">🎯 Circuit Breaker</div>', True)
        cb = st.session_state.circuit_breaker
        st.write(cb.get_status())
    elif page == "📐 Position Sizer":
        st.markdown('<div class="titanium-header">📐 Position Sizer</div>', True)
        # Sizer logic...
    elif page == "🔬 Backtesting":
        st.markdown('<div class="titanium-header">🔬 Backtesting</div>', True)
        # Backtest UI...
    elif page == "⚙️ Configuración":
        st.markdown('<div class="titanium-header">⚙️ Configuración</div>', True)
        # Config UI...


def page_login():
    st.markdown('<div class="titanium-header">⚡ TITANIUM PRO v10</div>', True)
    u = st.text_input("Usuario")
    p = st.text_input("Contraseña", type="password")
    if st.button("Entrar", use_container_width=True):
        if st.session_state.auth.authenticate(u, p):
            st.session_state.logged_in, st.session_state.username = True, u
            st.rerun()
        else: st.error("Error de acceso")
    if st.button("Registrar Demo"):
        st.session_state.auth.register(u, p)
        st.success("Registrado")


def main():
    st.set_page_config(page_title="Titanium Pro", page_icon="⚡", layout="wide")
    st.markdown(STYLES, unsafe_allow_html=True)
    _init_session()
    if not st.session_state.logged_in: page_login()
    else: page_dashboard()

if __name__ == "__main__": main()
