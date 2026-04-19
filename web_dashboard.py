"""
TITANIUM v10.2 — Railway Deploy Fixed
Puerto configurado via .streamlit/config.toml + CMD, NO via os.environ
"""

# ════════════════════════════════════════
# IMPORTS — sin configuración de puerto aquí
# ════════════════════════════════════════
import os, json, hashlib, warnings
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List, Optional
import numpy as np
import pandas as pd
import streamlit as st

warnings.filterwarnings('ignore')

# ════════════════════════════════════════
# CONFIG
# ════════════════════════════════════════
class Config:
    SYMBOL        = os.getenv("SYMBOL", "BTC/USDT")
    USE_SPOT      = True
    TF_ENTRY      = "5m"
    TF_CONFIRM    = "15m"
    TF_TREND      = "1h"
    CANDLE_LIMIT  = 200
    DEMO_MODE     = True
    GROQ_API_KEY  = os.getenv("GROQ_API_KEY", "")
    BINANCE_KEY   = os.getenv("BINANCE_API_KEY", "")
    BINANCE_SEC   = os.getenv("BINANCE_SECRET", "")
    MAX_DAILY_DD  = 5.0
    MAX_TOTAL_DD  = 15.0
    EMERGENCY     = -20.0
    MAX_LOSSES    = 5
    COOLDOWN      = 60
    KELLY         = 0.5
    MAX_POS       = 0.10

# ════════════════════════════════════════
# INDICADORES
# ════════════════════════════════════════
def ema(s, n=14): return s.ewm(span=n, adjust=False).mean()
def rsi(s, n=14):
    d = s.diff()
    g = d.where(d>0,0).rolling(n).mean()
    l = (-d.where(d<0,0)).rolling(n).mean()
    return 100 - 100/(1 + g/l.replace(0,1e-10))
def atr(df, n=14):
    tr = pd.concat([df['high']-df['low'],
                    (df['high']-df['close'].shift()).abs(),
                    (df['low']-df['close'].shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()

# ════════════════════════════════════════
# CIRCUIT BREAKER
# ════════════════════════════════════════
class CircuitBreaker:
    def __init__(self):
        self.daily_pnl = 0.0
        self.total_pnl = 0.0
        self.losses = 0
        self.paused = False
        self.reason = None
        self.until = None
        self._reset_t = datetime.now().replace(hour=0, minute=0, second=0)

    def can_trade(self):
        self._daily_reset()
        if self.paused and self.until and datetime.now() >= self.until:
            self.paused = False
            self.reason = None
        return not self.paused

    def record(self, pnl):
        self._daily_reset()
        self.daily_pnl += pnl
        self.total_pnl += pnl
        self.losses = self.losses+1 if pnl<0 else 0
        if self.total_pnl <= Config.EMERGENCY:
            self._pause(f"EMERGENCY {self.total_pnl:.1f}%")
        elif self.daily_pnl <= -Config.MAX_DAILY_DD:
            self._pause(f"Daily DD {self.daily_pnl:.1f}%", True)
        elif self.losses >= Config.MAX_LOSSES:
            self._pause(f"{self.losses} pérdidas seguidas", True)

    def status(self):
        return {"ok": self.can_trade(), "daily": round(self.daily_pnl,2),
                "total": round(self.total_pnl,2), "losses": self.losses,
                "reason": self.reason}

    def _pause(self, r, cd=False):
        self.paused, self.reason = True, r
        if cd: self.until = datetime.now() + timedelta(minutes=Config.COOLDOWN)

    def _daily_reset(self):
        if datetime.now() >= self._reset_t + timedelta(days=1):
            self.daily_pnl, self.losses = 0.0, 0
            self._reset_t = datetime.now().replace(hour=0, minute=0, second=0)

# ════════════════════════════════════════
# ATR RISK MANAGER
# ════════════════════════════════════════
@dataclass
class Stops:
    sl: float; tp: float; trail: float; rr: float; atr_v: float

class ATRRisk:
    def __init__(self, sl=2.0, tp=3.0): self.sl, self.tp = sl, tp

    def calc(self, entry, direction, df) -> Optional[Stops]:
        try: a = float(atr(df).iloc[-1])
        except: return None
        if not a or a != a: return None
        s = entry - a*self.sl if direction=='long' else entry + a*self.sl
        t = entry + a*self.tp if direction=='long' else entry - a*self.tp
        rr = round(abs(t-entry)/abs(entry-s),2) if abs(entry-s)>0 else 0
        return Stops(round(s,4), round(t,4), round(a*1.5,4), rr, round(a,4))

# ════════════════════════════════════════
# KELLY SIZER
# ════════════════════════════════════════
class Kelly:
    def __init__(self): self._h = []
    def add(self, pnl): self._h.append(pnl>0); self._h = self._h[-100:]
    def size(self, bal, entry, sl):
        if not entry or abs(entry-sl)==0: return 0
        k = self._k()
        return round(min(bal*k / (abs(entry-sl)/entry), bal*Config.MAX_POS), 2)
    def _k(self):
        if len(self._h)<10: return 0.02
        w = sum(self._h)/len(self._h)
        return float(np.clip(((2*w-(1-w))/2)*Config.KELLY, 0.01, Config.MAX_POS))

# ════════════════════════════════════════
# EXCHANGE — con freq map correcto
# ════════════════════════════════════════
FREQ_MAP = {'1m':'1min','3m':'3min','5m':'5min','15m':'15min',
            '30m':'30min','1h':'1h','4h':'4h','6h':'6h','1d':'1D'}

class Exchange:
    def __init__(self): self.ex = None

    def connect(self, k=None, s=None):
        if Config.DEMO_MODE: return
        try:
            import ccxt
            self.ex = ccxt.binance({'apiKey':k,'secret':s,'enableRateLimit':True})
        except Exception as e:
            st.warning(f"Exchange error: {e} — DEMO mode")
            Config.DEMO_MODE = True

    def all_tf(self):
        from concurrent.futures import ThreadPoolExecutor
        tfs = [Config.TF_ENTRY, Config.TF_CONFIRM, Config.TF_TREND]
        with ThreadPoolExecutor(max_workers=3) as ex:
            results = list(ex.map(self._candles, tfs))
        return {tf: df for tf, df in zip(tfs, results)}

    def _candles(self, tf):
        if Config.DEMO_MODE or not self.ex:
            return self._demo(tf)
        try:
            d = self.ex.fetch_ohlcv(Config.SYMBOL, tf, limit=Config.CANDLE_LIMIT)
            df = pd.DataFrame(d, columns=['time','open','high','low','close','volume'])
            df['time'] = pd.to_datetime(df['time'], unit='ms')
            return df.set_index('time')
        except: return self._demo(tf)

    def _demo(self, tf):
        n = Config.CANDLE_LIMIT
        np.random.seed(abs(hash(tf)) % 9999)
        c = 65000 + np.cumsum(np.random.normal(0, 80, n))
        freq = FREQ_MAP.get(tf, '5min')
        return pd.DataFrame({'open':c,'high':c*1.002,'low':c*0.998,
                             'close':c,'volume':np.random.uniform(10,100,n)},
                            index=pd.date_range(end=datetime.now(), periods=n, freq=freq))

    def obi(self):
        if Config.DEMO_MODE or not self.ex:
            return round(np.random.uniform(-0.12, 0.12), 4)
        try:
            ob = self.ex.fetch_order_book(Config.SYMBOL, 20)
            b = sum(x[1] for x in ob['bids'])
            a = sum(x[1] for x in ob['asks'])
            return round((b-a)/(b+a), 4) if (b+a) else 0.0
        except: return 0.0

# ════════════════════════════════════════
# AUTH
# ════════════════════════════════════════
class Auth:
    _DB = "/tmp/users.json"
    def _load(self):
        try:
            with open(self._DB) as f: return json.load(f)
        except: return {"admin": {"pw": hashlib.sha256(b"protrading").hexdigest()}}
    def _save(self, d):
        try:
            with open(self._DB,'w') as f: json.dump(d,f)
        except: pass
    def _h(self,p): return hashlib.sha256(p.encode()).hexdigest()
    def login(self,u,p):
        users = self._load()
        return u in users and users[u].get('pw') == self._h(p)
    def register(self,u,p):
        users = self._load()
        if u in users: return False
        users[u] = {'pw': self._h(p)}
        self._save(users); return True
    def keys(self,u):
        users = self._load()
        return users.get(u,{}).get('k',''), users.get(u,{}).get('s','')
    def save_keys(self,u,k,s):
        users = self._load()
        if u in users: users[u].update({'k':k,'s':s}); self._save(users)

# ════════════════════════════════════════
# UI HELPERS
# ════════════════════════════════════════
def card(label, val, sub="", color="#63b3ed"):
    st.markdown(f"""
    <div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);
                border-radius:12px;padding:16px;margin-bottom:8px">
        <div style="color:#718096;font-size:10px;text-transform:uppercase;letter-spacing:1px">{label}</div>
        <div style="color:{color};font-size:22px;font-weight:700;font-family:monospace">{val}</div>
        <div style="color:#4a5568;font-size:11px;margin-top:2px">{sub}</div>
    </div>""", unsafe_allow_html=True)

# ════════════════════════════════════════
# SESSION INIT
# ════════════════════════════════════════
def init():
    if 'ready' not in st.session_state:
        st.session_state.update({
            'ready': True, 'in': False, 'user': '',
            'ex': Exchange(), 'cb': CircuitBreaker(),
            'rm': ATRRisk(), 'ks': Kelly(), 'au': Auth(),
            'data': None, 'last': None
        })

# ════════════════════════════════════════
# PAGES
# ════════════════════════════════════════
def login_page():
    st.markdown("""
    <h1 style="background:linear-gradient(90deg,#63b3ed,#9f7aea);
               -webkit-background-clip:text;-webkit-text-fill-color:transparent;
               font-size:2.5rem;margin-bottom:0">⚡ TITANIUM PRO</h1>
    <p style="color:#718096;margin-top:0">Sistema institucional de trading v10.2</p>
    """, unsafe_allow_html=True)

    t1, t2 = st.tabs(["🔐 Login", "📝 Registro"])
    with t1:
        u = st.text_input("Usuario", key="lu")
        p = st.text_input("Contraseña", type="password", key="lp")
        if st.button("Entrar", use_container_width=True):
            if st.session_state.au.login(u, p):
                st.session_state.update({'in': True, 'user': u, 'data': None})
                st.rerun()
            else:
                st.error("❌ Credenciales incorrectas")
    with t2:
        u2 = st.text_input("Nuevo usuario", key="ru")
        p2 = st.text_input("Contraseña", type="password", key="rp")
        if st.button("Crear cuenta", use_container_width=True):
            st.success("✅ Cuenta creada") if st.session_state.au.register(u2,p2) else st.error("❌ Ya existe")

def main_page():
    ex: Exchange = st.session_state.ex
    cb: CircuitBreaker = st.session_state.cb

    # Sidebar
    with st.sidebar:
        st.markdown(f"### ⚡ Titanium\n**{st.session_state.user}**")
        mode = "🟡 DEMO" if Config.DEMO_MODE else "🟢 REAL"
        st.caption(mode)
        page = st.radio("", ["📊 Dashboard","🎯 Circuit Breaker",
                              "📐 Position Sizer","⚙️ Config"],
                        label_visibility="collapsed")
        st.divider()
        if st.button("🔄 Refresh", use_container_width=True):
            st.session_state.data = None
        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.update({'in': False, 'data': None})
            st.rerun()

    # Fetch data (cacheado en session)
    if st.session_state.data is None:
        with st.spinner("Cargando datos..."):
            st.session_state.data = ex.all_tf()

    data = st.session_state.data
    df_e = data.get(Config.TF_ENTRY, pd.DataFrame())

    # ── Dashboard ──
    if page == "📊 Dashboard":
        st.markdown("""<h2 style="background:linear-gradient(90deg,#63b3ed,#9f7aea);
            -webkit-background-clip:text;-webkit-text-fill-color:transparent">
            Market Dashboard</h2>""", unsafe_allow_html=True)

        price = df_e['close'].iloc[-1] if not df_e.empty else 0
        obi_v = ex.obi()
        s = cb.status()

        c1, c2, c3, c4 = st.columns(4)
        with c1: card("BTC/USDT", f"${price:,.2f}", "Precio actual")
        with c2:
            obi_color = "#68d391" if obi_v > 0 else "#fc8181"
            card("OBI", f"{obi_v:+.4f}", "Order Book Imbalance", obi_color)
        with c3:
            cb_color = "#68d391" if s['ok'] else "#fc8181"
            card("Circuit", "ACTIVO" if s['ok'] else "PAUSADO",
                 f"PnL: {s['total']:+.1f}%", cb_color)
        with c4:
            if not df_e.empty:
                rsi_v = rsi(df_e['close']).iloc[-1]
                rsi_color = "#fc8181" if rsi_v>70 else "#68d391" if rsi_v<30 else "#63b3ed"
                card("RSI(14)", f"{rsi_v:.1f}",
                     "Sobrecomprado" if rsi_v>70 else "Sobrevendido" if rsi_v<30 else "Neutral",
                     rsi_color)

        if not df_e.empty:
            st.subheader(f"📈 {Config.TF_ENTRY} — últimas 100 velas")
            st.line_chart(df_e['close'].tail(100))

    # ── Circuit Breaker ──
    elif page == "🎯 Circuit Breaker":
        st.markdown("## 🎯 Circuit Breaker")
        s = cb.status()
        c1, c2, c3 = st.columns(3)
        with c1: card("Estado", "ACTIVO" if s['ok'] else "PAUSADO",
                     color="#68d391" if s['ok'] else "#fc8181")
        with c2: card("PnL Diario", f"{s['daily']:+.2f}%",
                     f"Límite: -{Config.MAX_DAILY_DD}%")
        with c3: card("PnL Total", f"{s['total']:+.2f}%",
                     f"Emergency: {Config.EMERGENCY}%")
        if s['reason']:
            st.error(f"🚨 {s['reason']}")
        st.divider()
        st.caption("Simular trade")
        pnl = st.slider("PnL (%)", -10.0, 10.0, -1.5, 0.5)
        if st.button("Registrar"):
            cb.record(pnl); st.rerun()

    # ── Position Sizer ──
    elif page == "📐 Position Sizer":
        st.markdown("## 📐 Position Sizer (Half-Kelly)")
        price = df_e['close'].iloc[-1] if not df_e.empty else 65000.0
        bal = st.number_input("Capital (USD)", 100.0, 1e7, 10000.0, 100.0)
        entry = st.number_input("Entrada", 1.0, 1e8, float(price), 10.0)
        direction = st.selectbox("Dirección", ["long","short"])

        if st.button("Calcular", use_container_width=True):
            stops = st.session_state.rm.calc(entry, direction, df_e)
            if stops:
                size = st.session_state.ks.size(bal, entry, stops.sl)
                c1,c2,c3,c4 = st.columns(4)
                with c1: card("Stop Loss", f"${stops.sl:,.2f}", color="#fc8181")
                with c2: card("Take Profit", f"${stops.tp:,.2f}", color="#68d391")
                with c3: card("R:R", f"{stops.rr}x",
                             "high" if stops.rr>=2 else "medium")
                with c4: card("Posición", f"${size:,.0f}",
                             f"ATR: {stops.atr_v:.0f}", color="#9f7aea")
            else:
                st.warning("Datos insuficientes para calcular ATR")

    # ── Config ──
    elif page == "⚙️ Config":
        st.markdown("## ⚙️ Configuración")
        u = st.session_state.user
        k, s = st.session_state.au.keys(u)
        nk = st.text_input("Binance API Key", value=k, type="password")
        ns = st.text_input("Binance Secret", value=s, type="password")
        if st.button("💾 Guardar", use_container_width=True):
            st.session_state.au.save_keys(u, nk, ns)
            Config.DEMO_MODE = not bool(nk and ns)
            st.session_state.update({'data': None, 'ex': Exchange()})
            st.success("✅ Guardado")
            st.rerun()

# ════════════════════════════════════════
# MAIN
# ════════════════════════════════════════
def main():
    st.set_page_config(
        page_title="Titanium Pro",
        page_icon="⚡",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    init()
    if not st.session_state['in']:
        login_page()
    else:
        main_page()

if __name__ == "__main__":
    main()
