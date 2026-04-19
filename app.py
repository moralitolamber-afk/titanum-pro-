"""
TITANIUM PRO — Railway Final Fix
- Sin configuración de puerto en Python
- Puerto manejado 100% por Railway via $PORT + CMD
- Mínimo código en el nivel global para evitar crashes silenciosos
"""
import os
import warnings
import json
import hashlib
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List, Optional
import numpy as np
import pandas as pd
import streamlit as st

warnings.filterwarnings('ignore')

# ═══════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════
class Config:
    SYMBOL        = os.getenv("SYMBOL", "BTC/USDT")
    TF_ENTRY      = "5m"
    TF_CONFIRM    = "15m"
    TF_TREND      = "1h"
    CANDLE_LIMIT  = 200
    DEMO_MODE     = True
    GROQ_KEY      = os.getenv("GROQ_API_KEY", "")
    BIN_KEY       = os.getenv("BINANCE_API_KEY", "")
    BIN_SEC       = os.getenv("BINANCE_SECRET", "")
    MAX_DAILY_DD  = 5.0
    MAX_TOTAL_DD  = 15.0
    EMERGENCY     = -20.0
    MAX_LOSSES    = 5
    COOLDOWN      = 60
    KELLY         = 0.5
    MAX_POS       = 0.10

# ═══════════════════════════════════════
# INDICADORES
# ═══════════════════════════════════════
def calc_ema(s, n=14):
    return s.ewm(span=n, adjust=False).mean()

def calc_rsi(s, n=14):
    d = s.diff()
    g = d.where(d > 0, 0).rolling(n).mean()
    l = (-d.where(d < 0, 0)).rolling(n).mean()
    return 100 - 100 / (1 + g / l.replace(0, 1e-10))

def calc_atr(df, n=14):
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift()).abs(),
        (df['low'] - df['close'].shift()).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(n).mean()

# ═══════════════════════════════════════
# CIRCUIT BREAKER
# ═══════════════════════════════════════
class CircuitBreaker:
    def __init__(self):
        self.daily_pnl    = 0.0
        self.total_pnl    = 0.0
        self.losses       = 0
        self.paused       = False
        self.reason       = None
        self.until        = None
        self._reset_t     = datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0)

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
        self.losses = self.losses + 1 if pnl < 0 else 0
        if self.total_pnl <= Config.EMERGENCY:
            self._pause(f"EMERGENCY {self.total_pnl:.1f}%")
        elif self.daily_pnl <= -Config.MAX_DAILY_DD:
            self._pause(f"Daily DD {self.daily_pnl:.1f}%", cd=True)
        elif self.losses >= Config.MAX_LOSSES:
            self._pause(f"{self.losses} pérdidas seguidas", cd=True)

    def status(self):
        return {
            "ok":     self.can_trade(),
            "daily":  round(self.daily_pnl, 2),
            "total":  round(self.total_pnl, 2),
            "losses": self.losses,
            "reason": self.reason
        }

    def _pause(self, r, cd=False):
        self.paused = True
        self.reason = r
        if cd:
            self.until = datetime.now() + timedelta(minutes=Config.COOLDOWN)

    def _daily_reset(self):
        if datetime.now() >= self._reset_t + timedelta(days=1):
            self.daily_pnl = 0.0
            self.losses    = 0
            self._reset_t  = datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0)

# ═══════════════════════════════════════
# ATR RISK
# ═══════════════════════════════════════
@dataclass
class Stops:
    sl: float
    tp: float
    rr: float
    atr_v: float

class ATRRisk:
    def __init__(self, sl=2.0, tp=3.0):
        self.sl = sl
        self.tp = tp

    def calc(self, entry, direction, df) -> Optional[Stops]:
        try:
            a = float(calc_atr(df).iloc[-1])
            if not a or np.isnan(a):
                return None
        except Exception:
            return None
        s = entry - a * self.sl if direction == 'long' else entry + a * self.sl
        t = entry + a * self.tp if direction == 'long' else entry - a * self.tp
        rr = round(abs(t - entry) / abs(entry - s), 2) if abs(entry - s) > 0 else 0
        return Stops(round(s, 2), round(t, 2), rr, round(a, 2))

# ═══════════════════════════════════════
# KELLY SIZER
# ═══════════════════════════════════════
class Kelly:
    def __init__(self):
        self._h: List[float] = []  # FIX 2: guardar pnl real, no solo bool

    def add(self, pnl):
        self._h.append(float(pnl))
        if len(self._h) > 100:
            self._h = self._h[-100:]

    def size(self, bal, entry, sl):
        if not entry or abs(entry - sl) == 0:
            return 0.0
        k = self._k()
        return round(min(bal * k / (abs(entry - sl) / entry),
                         bal * Config.MAX_POS), 2)

    def _k(self):
        if len(self._h) < 10:
            return 0.02
        wins   = [p for p in self._h if p > 0]
        losses = [abs(p) for p in self._h if p < 0]
        if not wins or not losses:
            return 0.02
        w = len(wins) / len(self._h)
        # FIX 3: Kelly estándar con b real (avg_win/avg_loss), no b=2 fijo
        b = np.mean(wins) / np.mean(losses)
        k = (b * w - (1 - w)) / b
        return float(np.clip(k * Config.KELLY, 0.01, Config.MAX_POS))

# ═══════════════════════════════════════
# EXCHANGE
# ═══════════════════════════════════════
FREQ = {
    '1m': '1min', '3m': '3min', '5m': '5min',
    '15m': '15min', '30m': '30min',
    '1h': '1h', '4h': '4h', '1d': '1D'
}

class Exchange:
    def __init__(self):
        self.ex     = None
        self._error = None  # FIX 4b: error guardado para mostrar en UI

    def connect(self, k=None, s=None):
        if Config.DEMO_MODE:
            return
        try:
            import ccxt
            self.ex = ccxt.binance({
                'apiKey': k, 'secret': s, 'enableRateLimit': True
            })
        except Exception as e:
            # FIX 4: NO llamar st.warning dentro de thread — guardar error
            self._error = str(e)
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
            d = self.ex.fetch_ohlcv(
                Config.SYMBOL, tf, limit=Config.CANDLE_LIMIT)
            df = pd.DataFrame(
                d, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
            df['time'] = pd.to_datetime(df['time'], unit='ms')
            return df.set_index('time')
        except Exception:
            return self._demo(tf)

    def _demo(self, tf):
        n    = Config.CANDLE_LIMIT
        np.random.seed(abs(hash(tf)) % 9999)
        c    = 65000 + np.cumsum(np.random.normal(0, 80, n))
        freq = FREQ.get(tf, '5min')
        return pd.DataFrame({
            'open': c, 'high': c * 1.002,
            'low': c * 0.998, 'close': c,
            'volume': np.random.uniform(10, 100, n)
        }, index=pd.date_range(end=datetime.now(), periods=n, freq=freq))

    def obi(self):
        if Config.DEMO_MODE or not self.ex:
            return round(float(np.random.uniform(-0.12, 0.12)), 4)
        try:
            ob = self.ex.fetch_order_book(Config.SYMBOL, 20)
            b  = sum(x[1] for x in ob['bids'])
            a  = sum(x[1] for x in ob['asks'])
            return round((b - a) / (b + a), 4) if (b + a) else 0.0
        except Exception:
            return 0.0

# ═══════════════════════════════════════
# AUTH
# ═══════════════════════════════════════
class Auth:
    # FIX 5: /tmp es efímero en Streamlit Cloud — usar path relativo
    # En Streamlit Cloud el working dir persiste dentro de la sesión
    _DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")

    def _load(self):
        try:
            with open(self._DB) as f:
                return json.load(f)
        except Exception:
            return {"admin": {
                "pw": hashlib.sha256(b"protrading").hexdigest()
            }}

    def _save(self, d):
        try:
            with open(self._DB, 'w') as f:
                json.dump(d, f)
        except Exception:
            pass

    def _h(self, p):
        return hashlib.sha256(p.encode()).hexdigest()

    def login(self, u, p):
        users = self._load()
        return u in users and users[u].get('pw') == self._h(p)

    def register(self, u, p):
        users = self._load()
        if u in users:
            return False
        users[u] = {'pw': self._h(p)}
        self._save(users)
        return True

    def keys(self, u):
        users = self._load()
        return users.get(u, {}).get('k', ''), users.get(u, {}).get('s', '')

    def save_keys(self, u, k, s):
        users = self._load()
        if u in users:
            users[u].update({'k': k, 's': s})
            self._save(users)

# ═══════════════════════════════════════
# UI HELPERS
# ═══════════════════════════════════════
def card(label, val, sub="", color="#63b3ed", badge=""):
    # FIX 1: badge kwarg añadido — línea 436 lo llamaba con badge= y crasheaba
    st.markdown(f"""
    <div style="background:rgba(255,255,255,0.03);
                border:1px solid rgba(255,255,255,0.08);
                border-radius:12px;padding:16px;margin-bottom:8px">
        <div style="color:#718096;font-size:10px;
                    text-transform:uppercase;letter-spacing:1px">{label}</div>
        <div style="color:{color};font-size:22px;
                    font-weight:700;font-family:monospace">{val}</div>
        <div style="color:#4a5568;font-size:11px;margin-top:2px">{sub}</div>
    </div>""", unsafe_allow_html=True)

# ═══════════════════════════════════════
# SESSION
# ═══════════════════════════════════════
def init():
    if 'ready' not in st.session_state:
        st.session_state.update({
            'ready':     True,
            'in':        False,
            'user':      '',
            'ex':        Exchange(),
            'cb':        CircuitBreaker(),
            'rm':        ATRRisk(),
            'ks':        Kelly(),
            'au':        Auth(),
            'data':      None,
            # FIX 6: DEMO_MODE en session_state para persistir entre reruns
            'demo_mode': True,
        })
    # Sincronizar Config con session_state en cada rerun
    Config.DEMO_MODE = st.session_state.get('demo_mode', True)

# ═══════════════════════════════════════
# LOGIN PAGE
# ═══════════════════════════════════════
def login_page():
    st.markdown("""
    <h1 style="background:linear-gradient(90deg,#63b3ed,#9f7aea);
               -webkit-background-clip:text;
               -webkit-text-fill-color:transparent;
               font-size:2.5rem">⚡ TITANIUM PRO</h1>
    <p style="color:#718096">Sistema institucional de trading algorítmico</p>
    """, unsafe_allow_html=True)

    t1, t2 = st.tabs(["🔐 Login", "📝 Registro"])
    with t1:
        u = st.text_input("Usuario", key="lu")
        p = st.text_input("Contraseña", type="password", key="lp")
        if st.button("Entrar", use_container_width=True):
            if st.session_state.au.login(u, p):
                st.session_state.update({
                    'in': True, 'user': u, 'data': None
                })
                st.rerun()
            else:
                st.error("❌ Credenciales incorrectas")
    with t2:
        u2 = st.text_input("Nuevo usuario", key="ru")
        p2 = st.text_input("Contraseña", type="password", key="rp")
        if st.button("Crear cuenta", use_container_width=True):
            if st.session_state.au.register(u2, p2):
                st.success("✅ Cuenta creada")
            else:
                st.error("❌ Usuario ya existe")

# ═══════════════════════════════════════
# MAIN PAGE
# ═══════════════════════════════════════
def main_page():
    ex: Exchange       = st.session_state.ex
    cb: CircuitBreaker = st.session_state.cb

    with st.sidebar:
        st.markdown(f"### ⚡ Titanium\n**{st.session_state.user}**")
        mode = "🟡 DEMO" if Config.DEMO_MODE else "🟢 REAL"
        st.caption(mode)
        page = st.radio("", [
            "📊 Dashboard",
            "🎯 Circuit Breaker",
            "📐 Position Sizer",
            "⚙️ Config"
        ], label_visibility="collapsed")
        st.divider()
        if st.button("🔄 Refresh", use_container_width=True):
            st.session_state.data = None
            st.rerun()
        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.update({'in': False, 'data': None})
            st.rerun()

    # Fetch data
    if st.session_state.data is None:
        with st.spinner("Cargando datos de mercado..."):
            st.session_state.data = ex.all_tf()
        # FIX 4c: mostrar error de exchange en el hilo principal de UI
        if ex._error:
            st.warning(f"⚠️ Exchange: {ex._error} — usando DEMO")
            ex._error = None

    data = st.session_state.data
    df_e = data.get(Config.TF_ENTRY, pd.DataFrame())

    # ── Dashboard ──────────────────────────────────────────────
    if page == "📊 Dashboard":
        st.markdown("""
        <h2 style="background:linear-gradient(90deg,#63b3ed,#9f7aea);
            -webkit-background-clip:text;-webkit-text-fill-color:transparent">
            Market Dashboard</h2>""", unsafe_allow_html=True)

        price = float(df_e['close'].iloc[-1]) if not df_e.empty else 0.0
        obi_v = ex.obi()
        s     = cb.status()

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            card("BTC/USDT", f"${price:,.2f}", Config.SYMBOL)
        with c2:
            col = "#68d391" if obi_v > 0 else "#fc8181"
            card("OBI", f"{obi_v:+.4f}", "Order Book Imbalance", col)
        with c3:
            col = "#68d391" if s['ok'] else "#fc8181"
            card("Circuit", "ACTIVO" if s['ok'] else "PAUSADO",
                 f"PnL total: {s['total']:+.1f}%", col)
        with c4:
            if not df_e.empty:
                rsi_v = float(calc_rsi(df_e['close']).iloc[-1])
                col   = ("#fc8181" if rsi_v > 70
                         else "#68d391" if rsi_v < 30
                         else "#63b3ed")
                card("RSI(14)", f"{rsi_v:.1f}",
                     "Sobrecomprado" if rsi_v > 70
                     else "Sobrevendido" if rsi_v < 30
                     else "Neutral", col)

        if not df_e.empty:
            st.subheader(f"📈 {Config.TF_ENTRY} — últimas 100 velas")
            st.line_chart(df_e['close'].tail(100))

            # EMAs
            close  = df_e['close']
            e20    = calc_ema(close, 20)
            e50    = calc_ema(close, 50)
            ema_df = pd.DataFrame({
                'Precio': close.tail(100),
                'EMA20':  e20.tail(100),
                'EMA50':  e50.tail(100),
            })
            st.line_chart(ema_df)

    # ── Circuit Breaker ────────────────────────────────────────
    elif page == "🎯 Circuit Breaker":
        st.markdown("## 🎯 Circuit Breaker")
        s = cb.status()

        c1, c2, c3 = st.columns(3)
        with c1:
            col = "#68d391" if s['ok'] else "#fc8181"
            card("Estado", "ACTIVO" if s['ok'] else "PAUSADO",
                 badge=col, color=col)
        with c2:
            col = "#68d391" if s['daily'] > -Config.MAX_DAILY_DD else "#fc8181"
            card("PnL Diario", f"{s['daily']:+.2f}%",
                 f"Límite: -{Config.MAX_DAILY_DD}%", col)
        with c3:
            col = "#68d391" if s['total'] > -Config.MAX_TOTAL_DD else "#fc8181"
            card("PnL Total", f"{s['total']:+.2f}%",
                 f"Emergency: {Config.EMERGENCY}%", col)

        if s['reason']:
            st.error(f"🚨 {s['reason']}")

        st.divider()
        st.caption("Simular trade para probar los límites")
        pnl = st.slider("PnL (%)", -10.0, 10.0, -1.5, 0.5)
        if st.button("Registrar trade simulado"):
            cb.record(pnl)
            st.rerun()

        st.divider()
        st.caption("Configuración activa")
        st.json({
            "max_daily_dd":   f"{Config.MAX_DAILY_DD}%",
            "max_total_dd":   f"{Config.MAX_TOTAL_DD}%",
            "emergency_stop": f"{Config.EMERGENCY}%",
            "max_losses":     Config.MAX_LOSSES,
            "cooldown_min":   Config.COOLDOWN,
        })

    # ── Position Sizer ─────────────────────────────────────────
    elif page == "📐 Position Sizer":
        st.markdown("## 📐 Position Sizer (Half-Kelly)")

        price     = float(df_e['close'].iloc[-1]) if not df_e.empty else 65000.0
        bal       = st.number_input("Capital (USD)", 100.0, 1e7, 10000.0, 100.0)
        entry     = st.number_input("Precio de entrada", 1.0, 1e8, price, 10.0)
        direction = st.selectbox("Dirección", ["long", "short"])

        if st.button("Calcular stops y tamaño", use_container_width=True):
            if df_e.empty:
                st.warning("Sin datos de velas")
            else:
                stops = st.session_state.rm.calc(entry, direction, df_e)
                if stops:
                    size = st.session_state.ks.size(bal, entry, stops.sl)
                    c1, c2, c3, c4 = st.columns(4)
                    with c1:
                        card("Stop Loss",   f"${stops.sl:,.2f}",
                             color="#fc8181")
                    with c2:
                        card("Take Profit", f"${stops.tp:,.2f}",
                             color="#68d391")
                    with c3:
                        col = "#68d391" if stops.rr >= 2 else "#f6ad55"
                        card("R:R",         f"{stops.rr}x",
                             "high" if stops.rr >= 2 else "medium", col)
                    with c4:
                        card("Posición",    f"${size:,.0f}",
                             f"ATR: {stops.atr_v:.0f}", "#9f7aea")
                else:
                    st.warning("ATR no calculable — agrega más velas")

    # ── Config ─────────────────────────────────────────────────
    elif page == "⚙️ Config":
        st.markdown("## ⚙️ Configuración")
        u    = st.session_state.user
        k, s = st.session_state.au.keys(u)

        nk = st.text_input("Binance API Key",    value=k, type="password")
        ns = st.text_input("Binance API Secret", value=s, type="password")

        if st.button("💾 Guardar llaves", use_container_width=True):
            st.session_state.au.save_keys(u, nk, ns)
            # FIX 6b: actualizar session_state Y Config juntos
            demo = not bool(nk and ns)
            Config.DEMO_MODE = demo
            st.session_state.demo_mode = demo
            st.session_state.update({'data': None, 'ex': Exchange()})
            st.success("✅ Guardado — modo "
                       + ("REAL 🟢" if not demo else "DEMO 🟡"))
            st.rerun()

        if st.button("🗑️ Eliminar llaves (volver a DEMO)",
                     use_container_width=True):
            st.session_state.au.save_keys(u, '', '')
            Config.DEMO_MODE = True
            st.session_state.demo_mode = True
            st.session_state.update({'data': None, 'ex': Exchange()})
            st.warning("Modo DEMO activado")
            st.rerun()

        st.divider()
        st.caption("Variables de entorno disponibles en Railway:")
        st.code("""
BINANCE_API_KEY=tu_key
BINANCE_SECRET=tu_secret
GROQ_API_KEY=tu_groq_key
MAX_DAILY_DD=5.0
MAX_TOTAL_DD=15.0
        """, language="bash")

# ═══════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════
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
