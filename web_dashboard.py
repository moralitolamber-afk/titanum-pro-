"""
╔══════════════════════════════════════════════════════════════════╗
║         TITANIUM v10.1 PRO — RAILWAY DEPLOY READY               ║
╚══════════════════════════════════════════════════════════════════╝
"""

# ═══════════════════════════════════════════════════════════════════
# CONFIGURACIÓN OBLIGATORIA PARA RAILWAY (ANTES de todo)
# ═══════════════════════════════════════════════════════════════════
import os
import sys

# Railway asigna un puerto dinámico en $PORT - DEBES usarlo
PORT = os.environ.get("PORT", "8501")
os.environ["STREAMLIT_SERVER_PORT"] = PORT
os.environ["STREAMLIT_SERVER_ADDRESS"] = "0.0.0.0"
os.environ["STREAMLIT_SERVER_HEADLESS"] = "true"
os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
os.environ["STREAMLIT_SERVER_ENABLECORS"] = "false"
os.environ["STREAMLIT_SERVER_ENABLEWEBSOCKETCOMPRESSION"] = "false"

import warnings
warnings.filterwarnings('ignore')

import json
import hashlib
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd
import streamlit as st

# ═══════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════════

class Config:
    SYMBOL = os.getenv("SYMBOL", "BTC/USDT")
    USE_SPOT = os.getenv("USE_SPOT", "true").lower() == "true"
    TF_ENTRY, TF_CONFIRM, TF_TREND = "5m", "15m", "1h"
    CANDLE_LIMIT = 200
    DEMO_MODE = True
    
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
    BINANCE_SECRET = os.getenv("BINANCE_SECRET", "")
    
    MAX_DAILY_DD = 5.0
    MAX_TOTAL_DD = 15.0
    EMERGENCY_STOP = -20.0
    MAX_CONS_LOSSES = 5
    COOLDOWN_MIN = 60
    KELLY_FRACTION = 0.5
    MAX_POSITION_PCT = 0.10

# ═══════════════════════════════════════════════════════════════════
# INDICADORES MANUALES
# ═══════════════════════════════════════════════════════════════════

def ema(s, n=14): 
    return s.ewm(span=n, adjust=False).mean()

def rsi(s, n=14):
    d = s.diff()
    g = d.where(d > 0, 0).rolling(n).mean()
    l = (-d.where(d < 0, 0)).rolling(n).mean()
    return 100 - 100 / (1 + g / l.replace(0, 1e-10))

def atr(df, n=14):
    tr = pd.concat([
        df['high'] - df['low'], 
        (df['high'] - df['close'].shift()).abs(),
        (df['low'] - df['close'].shift()).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(n).mean()

# ═══════════════════════════════════════════════════════════════════
# CIRCUIT BREAKER
# ═══════════════════════════════════════════════════════════════════

class CircuitBreaker:
    def __init__(self):
        self.daily_pnl = 0.0
        self.total_pnl = 0.0
        self.consecutive_losses = 0
        self.trading_paused = False
        self.pause_reason = None
        self.cooldown_until = None
        self._daily_reset = datetime.now().replace(hour=0, minute=0, second=0)

    def can_trade(self) -> bool:
        self._maybe_reset()
        if self.trading_paused and self.cooldown_until:
            if datetime.now() >= self.cooldown_until:
                self.trading_paused = False
                self.pause_reason = None
        return not self.trading_paused

    def record_trade(self, pnl_pct: float):
        self._maybe_reset()
        self.daily_pnl += pnl_pct
        self.total_pnl += pnl_pct
        self.consecutive_losses = self.consecutive_losses + 1 if pnl_pct < 0 else 0
        self._check()

    def get_status(self):
        return {
            "can_trade": self.can_trade(),
            "daily_pnl": round(self.daily_pnl, 2),
            "total_pnl": round(self.total_pnl, 2),
            "consecutive": self.consecutive_losses,
            "paused": self.trading_paused,
            "reason": self.pause_reason
        }

    def _check(self):
        if self.total_pnl <= Config.EMERGENCY_STOP:
            self._pause(f"Emergency: {self.total_pnl:.1f}%", True)
        elif self.daily_pnl <= -Config.MAX_DAILY_DD:
            self._pause(f"Daily DD: {self.daily_pnl:.1f}%", cooldown=True)
        elif self.consecutive_losses >= Config.MAX_CONS_LOSSES:
            self._pause("5 pérdidas seguidas", cooldown=True)

    def _pause(self, reason, permanent=False, cooldown=False):
        self.trading_paused = True
        self.pause_reason = reason
        if cooldown and not permanent:
            self.cooldown_until = datetime.now() + timedelta(minutes=Config.COOLDOWN_MIN)

    def _maybe_reset(self):
        if datetime.now() >= self._daily_reset + timedelta(days=1):
            self.daily_pnl = 0.0
            self.consecutive_losses = 0
            self._daily_reset = datetime.now().replace(hour=0, minute=0, second=0)

# ═══════════════════════════════════════════════════════════════════
# ATR RISK MANAGER
# ═══════════════════════════════════════════════════════════════════

@dataclass
class StopLevels:
    stop_loss: float
    take_profit: float
    trailing: float
    risk_reward: float
    atr: float
    confidence: str

class ATRRiskManager:
    def __init__(self, period=14, sl=2.0, tp=3.0, trail=1.5):
        self.period, self.sl, self.tp, self.trail = period, sl, tp, trail

    def calculate_stops(self, entry, direction, df) -> Optional[StopLevels]:
        a = self._atr(df)
        if not a: 
            return None
        sl = entry - a * self.sl if direction == 'long' else entry + a * self.sl
        tp = entry + a * self.tp if direction == 'long' else entry - a * self.tp
        rr = round(abs(tp - entry) / abs(entry - sl), 2) if abs(entry - sl) > 0 else 0
        return StopLevels(
            round(sl, 4), round(tp, 4), round(a * self.trail, 4), 
            rr, round(a, 4), 'high' if rr >= 2 else 'medium'
        )

    def _atr(self, df):
        try: 
            return float(atr(df, self.period).iloc[-1])
        except: 
            return None

# ═══════════════════════════════════════════════════════════════════
# KELLY POSITION SIZER
# ═══════════════════════════════════════════════════════════════════

@dataclass
class TradeRecord:
    pnl_pct: float
    won: bool

class KellyPositionSizer:
    def __init__(self):
        self._history: List[TradeRecord] = []

    def add_trade(self, pnl_pct: float):
        self._history.append(TradeRecord(pnl_pct, pnl_pct > 0))
        if len(self._history) > 100:
            self._history = self._history[-100:]

    def calculate(self, balance, entry, sl):
        if entry <= 0 or abs(entry - sl) == 0:
            return {"error": "Invalid prices", "size_usd": 0}
        pct = self._kelly()
        risk = balance * pct
        dist = abs(entry - sl) / entry
        pos = min(risk / dist, balance * Config.MAX_POSITION_PCT)
        return {
            "size_usd": round(pos, 2),
            "size_coin": round(pos / entry, 6),
            "risk_pct": round(pct * 100, 2),
            "method": "kelly" if len(self._history) >= 20 else "default"
        }

    def stats(self):
        if not self._history: 
            return {"trades": 0}
        wins = [t for t in self._history if t.won]
        return {
            "trades": len(self._history),
            "win_rate": round(len(wins) / len(self._history) * 100, 1) if self._history else 0,
            "kelly_pct": round(self._kelly() * 100, 2)
        }

    def _kelly(self):
        min_p, max_p = 0.01, Config.MAX_POSITION_PCT
        if len(self._history) < 20: 
            return min_p
        recent = self._history[-50:]
        wins = [t for t in recent if t.won]
        losses = [t for t in recent if not t.won]
        if not wins or not losses: 
            return min_p
        w = len(wins) / len(recent)
        b = np.mean([t.pnl_pct for t in wins]) / np.mean([abs(t.pnl_pct) for t in losses])
        k = ((b * w - (1 - w)) / b) * Config.KELLY_FRACTION
        return float(np.clip(k, min_p, max_p))

# ═══════════════════════════════════════════════════════════════════
# REGIME DETECTOR
# ═══════════════════════════════════════════════════════════════════

class RegimeDetector:
    def detect(self, df):
        if len(df) < 30: 
            return {"regime": "UNKNOWN", "confidence": 0, "should_trade": False}
        try:
            c = df['close']
            r = rsi(c, 14).iloc[-1]
            a = atr(df, 14).iloc[-1] / c.iloc[-1] * 100
            bb = (c.rolling(20).std().iloc[-1] * 4) / c.rolling(20).mean().iloc[-1] * 100
            e20, e50, e200 = ema(c, 20).iloc[-1], ema(c, 50).iloc[-1], ema(c, 200).iloc[-1]
            aligned = (c.iloc[-1] > e20 > e50 > e200) or (c.iloc[-1] < e20 < e50 < e200)
            
            if a > 3.0: 
                regime, conf = "VOL_SPIKE", 0.85
            elif bb < 2.0: 
                regime, conf = "SQUEEZE", 0.75
            elif aligned: 
                regime, conf = "STRONG_TREND" if a > 1.0 else "WEAK_TREND", 0.8
            else: 
                regime, conf = "RANGE" if bb < 4.0 else "CHOPPY", 0.6
            
            return {
                "regime": regime, 
                "confidence": round(conf, 2), 
                "rsi": round(r, 1),
                "should_trade": regime in ["STRONG_TREND", "VOL_SPIKE"]
            }
        except: 
            return {"regime": "ERROR", "confidence": 0, "should_trade": False}

# ═══════════════════════════════════════════════════════════════════
# EXCHANGE MANAGER
# ═══════════════════════════════════════════════════════════════════

class ExchangeManager:
    def __init__(self):
        self.exchange = None
        self._cache = {}
        self._import_error = None

    def connect(self, key=None, sec=None):
        if Config.DEMO_MODE: 
            return
        try:
            import ccxt
            cfg = {
                'enableRateLimit': True, 
                'apiKey': key, 
                'secret': sec,
                'options': {'defaultType': 'spot' if Config.USE_SPOT else 'future'}
            }
            self.exchange = ccxt.binance(cfg) if Config.USE_SPOT else ccxt.binanceusdm(cfg)
        except ImportError:
            self._import_error = "ccxt not installed - DEMO mode forced"
            Config.DEMO_MODE = True
        except Exception as e:
            self._import_error = f"Exchange error: {e}"
            Config.DEMO_MODE = True

    def get_import_error(self):
        return self._import_error

    def fetch_candles(self, tf):
        if Config.DEMO_MODE or not self.exchange:
            return self._demo_candles(tf)
        try:
            data = self.exchange.fetch_ohlcv(Config.SYMBOL, tf, limit=Config.CANDLE_LIMIT)
            df = pd.DataFrame(data, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
            df['time'] = pd.to_datetime(df['time'], unit='ms')
            return df.set_index('time')
        except:
            return self._cache.get(tf, self._demo_candles(tf))

    def fetch_all_timeframes(self):
        """Versión secuencial para evitar problemas en Railway"""
        tfs = [Config.TF_ENTRY, Config.TF_CONFIRM, Config.TF_TREND]
        results = {}
        for tf in tfs:
            df = self.fetch_candles(tf)
            if not df.empty:
                results[tf] = df
        return results

    def fetch_obi(self):
        if Config.DEMO_MODE or not self.exchange:
            return {'obi': round(np.random.uniform(-0.15, 0.15), 4)}
        try:
            ob = self.exchange.fetch_order_book(Config.SYMBOL, 20)
            b = sum(x[1] for x in ob['bids'])
            a = sum(x[1] for x in ob['asks'])
            return {'obi': round((b - a) / (b + a), 4) if (b + a) > 0 else 0.0}
        except:
            return {'obi': 0.0}

    def _demo_candles(self, tf):
        n = Config.CANDLE_LIMIT
        np.random.seed(abs(hash(tf)) % (2**31))
        base = 65000
        closes = base + np.cumsum(np.random.normal(0, base * 0.002, n))
        
        freq_map = {
            '1m': '1min', '3m': '3min', '5m': '5min', '15m': '15min',
            '30m': '30min', '1h': '1h', '4h': '4h', '1d': '1D'
        }
        freq = freq_map.get(tf, '5min')
        
        return pd.DataFrame({
            'open': closes, 
            'high': closes * 1.002, 
            'low': closes * 0.998,
            'close': closes, 
            'volume': np.random.uniform(10, 100, n)
        }, index=pd.date_range(end=datetime.now(), periods=n, freq=freq))

# ═══════════════════════════════════════════════════════════════════
# AUTH MANAGER
# ═══════════════════════════════════════════════════════════════════

class AuthManager:
    DB_PATH = os.getenv("USERS_DB_PATH")
    
    def __init__(self):
        self._memory_db = {}
        self._use_memory = not self.DB_PATH

    def _load(self):
        if self._use_memory:
            return self._memory_db
        try:
            with open(self.DB_PATH) as f: 
                return json.load(f)
        except: 
            return {}

    def _save(self, data):
        if self._use_memory:
            self._memory_db = data
            return
        try:
            with open(self.DB_PATH, 'w') as f: 
                json.dump(data, f)
        except: 
            pass

    def _hash(self, pw): 
        return hashlib.sha256(pw.encode()).hexdigest()

    def auth(self, u, p):
        users = self._load()
        user = users.get(u)
        return bool(user and user.get('pw') == self._hash(p))

    def register(self, u, p):
        users = self._load()
        if u in users: 
            return False
        users[u] = {'pw': self._hash(p), 'created': datetime.now().isoformat()}
        self._save(users)
        return True

# ═══════════════════════════════════════════════════════════════════
# UI & STYLES
# ═══════════════════════════════════════════════════════════════════

STYLES = """<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;700&family=JetBrains+Mono&display=swap');
html,body,[class*="css"]{font-family:'Space Grotesk',sans-serif}
.stApp{background:#0a0a0f;color:#e2e8f0}
.titanium-card{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.1);
  border-radius:12px;padding:15px;margin-bottom:10px}
.metric-label{font-size:10px;text-transform:uppercase;color:#718096}
.metric-value{font-family:'JetBrains Mono';font-size:22px;font-weight:700;color:#edf2f7}
.badge{padding:2px 8px;border-radius:10px;font-size:9px}
.badge-green{background:rgba(72,187,120,0.2);color:#68d391}
.badge-red{background:rgba(245,101,101,0.2);color:#fc8181}
.badge-blue{background:rgba(99,179,237,0.2);color:#63b3ed}
.titanium-header{font-size:26px;font-weight:700;
  background:linear-gradient(90deg,#63b3ed,#9f7aea);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent}
</style>"""

def card(label, value, sub="", badge=""):
    b = f'<span class="badge badge-{badge}">{badge.upper()}</span>' if badge else ""
    st.markdown(
        f'<div class="titanium-card"><div class="metric-label">{label} {b}</div>'
        f'<div class="metric-value">{value}</div><div style="font-size:11px;color:#718096;">{sub}</div></div>', 
        unsafe_allow_html=True
    )

# ═══════════════════════════════════════════════════════════════════
# SESSION INIT
# ═══════════════════════════════════════════════════════════════════

def _init():
    if 'init' not in st.session_state:
        st.session_state.update({
            'init': True, 
            'logged_in': False, 
            'username': '',
            'ex': ExchangeManager(), 
            'cb': CircuitBreaker(),
            'rm': ATRRiskManager(), 
            'ps': KellyPositionSizer(),
            'rd': RegimeDetector(), 
            'auth': AuthManager(),
            'tf_data': {}, 
            'obi': {}, 
            'regime': {}
        })

# ═══════════════════════════════════════════════════════════════════
# PAGES
# ═══════════════════════════════════════════════════════════════════

def page_login():
    st.markdown('<div class="titanium-header">⚡ TITANIUM V10.1 PRO</div>', unsafe_allow_html=True)
    st.caption("Sistema institucional de trading algorítmico")
    
    tab1, tab2 = st.tabs(["Login", "Register"])
    with tab1:
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.button("Login", use_container_width=True):
            if st.session_state.auth.auth(u, p):
                st.session_state.logged_in = True
                st.session_state.username = u
                st.rerun()
            else:
                st.error("Invalid credentials")
    
    with tab2:
        nu = st.text_input("New username", key="reg_u")
        np = st.text_input("New password", type="password", key="reg_p")
        if st.button("Create account", use_container_width=True):
            if st.session_state.auth.register(nu, np):
                st.success("Account created - please login")
            else:
                st.error("Username exists")

def page_dashboard():
    with st.sidebar:
        st.markdown("### Navigation")
        page = st.radio(
            "Menu", 
            ["📊 Dashboard", "🎯 Circuit Breaker", "📐 Position Sizer",
             "🔬 Backtest", "⚙️ Settings"], 
            label_visibility="collapsed"
        )
        if st.button("Logout"): 
            st.session_state.logged_in = False
            st.rerun()
    
    ex = st.session_state.ex
    import_error = ex.get_import_error()
    if import_error:
        st.warning(f"⚠️ {import_error}")
    
    if not st.session_state.tf_data:
        with st.spinner("Cargando datos..."):
            st.session_state.tf_data = ex.fetch_all_timeframes()
            st.session_state.obi = ex.fetch_obi()
            df_trend = st.session_state.tf_data.get(Config.TF_TREND, pd.DataFrame())
            st.session_state.regime = st.session_state.rd.detect(df_trend) if not df_trend.empty else {}
    
    tf_data = st.session_state.tf_data
    obi = st.session_state.obi
    regime = st.session_state.regime
    cb = st.session_state.cb

    if page == "📊 Dashboard":
        st.markdown('<div class="titanium-header">Market Dashboard</div>', unsafe_allow_html=True)
        
        c1, c2, c3, c4 = st.columns(4)
        df_entry = tf_data.get(Config.TF_ENTRY, pd.DataFrame())
        price = df_entry['close'].iloc[-1] if not df_entry.empty else 0
        
        with c1: 
            card("BTC Price", f"${price:,.2f}", sub=f"TF: {Config.TF_ENTRY}")
        with c2: 
            card("OBI", f"{obi.get('obi', 0):+.4f}", sub="Order Book")
        with c3:
            r = regime.get('regime', 'UNKNOWN')
            conf = regime.get('confidence', 0)
            badge = 'green' if r in ['STRONG_TREND'] else 'blue'
            card("Regime", r, sub=f"Conf: {conf:.0%}", badge=badge)
        with c4:
            status = cb.get_status()
            badge = 'green' if status['can_trade'] else 'red'
            card("Circuit", "ACTIVE" if status['can_trade'] else "PAUSED", 
                 sub=f"PnL: {status['total_pnl']:+.1f}%", badge=badge)
        
        if not df_entry.empty:
            st.line_chart(df_entry['close'].tail(100))
    
    elif page == "🎯 Circuit Breaker":
        st.markdown('<div class="titanium-header">Circuit Breaker</div>', unsafe_allow_html=True)
        status = cb.get_status()
        
        c1, c2, c3 = st.columns(3)
        with c1: 
            card("Status", "ACTIVE" if status['can_trade'] else "PAUSED",
                 badge='green' if status['can_trade'] else 'red')
        with c2: 
            card("Daily PnL", f"{status['daily_pnl']:+.2f}%")
        with c3: 
            card("Total PnL", f"{status['total_pnl']:+.2f}%")
        
        if status['reason']:
            st.error(f"Paused: {status['reason']}")
    
    elif page == "📐 Position Sizer":
        st.markdown('<div class="titanium-header">Position Sizer (Kelly)</div>', unsafe_allow_html=True)
        ps = st.session_state.ps
        stats = ps.stats()
        if stats['trades'] > 0:
            c1, c2 = st.columns(2)
            with c1: 
                card("Trades", str(stats['trades']))
            with c2: 
                card("Win Rate", f"{stats['win_rate']}%")
        else:
            st.info("No hay trades registrados todavía")
    
    elif page == "🔬 Backtest":
        st.markdown('<div class="titanium-header">Backtester</div>', unsafe_allow_html=True)
        df = tf_data.get(Config.TF_TREND, pd.DataFrame())
        
        if df.empty:
            st.warning("No data for backtest")
        else:
            if st.button("Run Backtest"):
                with st.spinner("Ejecutando backtest..."):
                    @dataclass
                    class Sig:
                        direction: str
                        stop_loss: float
                        take_profit: float
                    
                    def strat(hist):
                        if len(hist) < 50: 
                            return None
                        c = hist['close']
                        e20 = ema(c, 20).iloc[-1]
                        e50 = ema(c, 50).iloc[-1]
                        r = rsi(c, 14).iloc[-1]
                        price = c.iloc[-1]
                        
                        rm = ATRRiskManager()
                        stops = rm.calculate_stops(price, 'long', hist)
                        if not stops: 
                            return None
                        
                        if e20 > e50 and r < 65:
                            return Sig('long', stops.stop_loss, stops.take_profit)
                        return None
                    
                    bt = Backtester()
                    res = bt.run(df, strat)
                    
                    c1, c2, c3 = st.columns(3)
                    with c1: 
                        card("Return", f"{res.total_return:+.1f}%",
                             badge='green' if res.total_return > 0 else 'red')
                    with c2: 
                        card("Sharpe", f"{res.sharpe:.2f}")
                    with c3: 
                        card("Trades", str(res.trades))

# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    st.set_page_config(
        page_title="Titanium V10.1", 
        layout="wide",
        initial_sidebar_state="expanded"
    )
    st.markdown(STYLES, unsafe_allow_html=True)
    _init()
    
    if not st.session_state.logged_in:
        page_login()
    else:
        page_dashboard()

if __name__ == "__main__":
    main()
