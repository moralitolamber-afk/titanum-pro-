"""
⚡ TITANIUM v8.0 PRO — Web Dashboard (Streamlit)
Interfaz web en tiempo real. Usa componentes nativos de Streamlit
para evitar conflictos DOM con React.
Se ejecuta con: streamlit run web_dashboard.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime
import pytz
import time
import asyncio
from streamlit_autorefresh import st_autorefresh

import config
from core.exchange import ExchangeManager
from core.indicators import calculate_all, get_trend_direction, get_macro_trend_direction
from core.strategy import StrategyEngine
from core.ai_brain import AIBrain
from risk.circuit_breaker import CircuitBreaker
from risk.position_sizer import KellyPositionSizer
from core.auth_manager import authenticate_user, register_user, get_user_data, update_api_keys

# ── PAGE CONFIG ──────────────────────────────────────────
st.set_page_config(
    page_title="TITANIUM v8.0 PRO",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── AUTH STATE ──────────────────────────────────────────
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'auth_mode' not in st.session_state:
    st.session_state.auth_mode = 'login'

if st.session_state.authenticated:
    # Auto-refresh cada 4 segundos solo si está logueado
    count = st_autorefresh(interval=4000, limit=None, key="titanium_refresh")

# ── CSS (PREMIUM INSTITUTIONAL UI) ────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;700&display=swap');
    
    /* Global Typography & Colors */
    * { font-family: 'Outfit', sans-serif; }
    
    .stApp { 
        background: radial-gradient(circle at 50% -20%, #0c152a 0%, #030712 50%, #000000 100%);
        color: #f8fafc;
    }

    /* Hide Streamlit Branding (Header, Footer, Menu) */
    header[data-testid="stHeader"] { display: none; }
    footer[data-testid="stFooter"] { display: none; }
    #MainMenu { visibility: hidden; }

    /* Adjust Main Container Spacing */
    [data-testid="block-container"] { 
        padding-top: 1rem; 
        padding-left: 3rem; 
        padding-right: 3rem; 
        max-width: 1700px; 
    }

    /* Titles & Headers */
    h1 {
        font-weight: 800 !important;
        background: linear-gradient(135deg, #0ea5e9 0%, #6366f1 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        letter-spacing: -1.5px;
        text-shadow: 0px 4px 25px rgba(14, 165, 233, 0.4);
    }
    h2, h3 { font-weight: 700 !important; color: #f1f5f9; letter-spacing: -0.5px; }

    /* Sidebar Styling Premium */
    section[data-testid="stSidebar"] { 
        background: rgba(10, 15, 30, 0.95) !important;
        backdrop-filter: blur(20px);
        -webkit-backdrop-filter: blur(20px);
        border-right: 1px solid rgba(14, 165, 233, 0.15);
    }
    section[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,0.05) !important; }

    /* Glassmorphism Metrics (Ultra Premium) */
    div[data-testid="stMetric"] {
        background: rgba(15, 23, 42, 0.4);
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
        border: 1px solid rgba(255, 255, 255, 0.05);
        border-radius: 20px;
        padding: 24px;
        position: relative;
        overflow: hidden;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
    }
    
    div[data-testid="stMetric"]::before {
        content: '';
        position: absolute;
        top: 0; left: 0; right: 0; height: 2px;
        background: linear-gradient(90deg, transparent, rgba(56, 189, 248, 0.5), transparent);
        opacity: 0;
        transition: opacity 0.3s ease;
    }
    
    div[data-testid="stMetric"]:hover {
        transform: translateY(-5px);
        box-shadow: 0 15px 40px rgba(14, 165, 233, 0.15);
        border: 1px solid rgba(14, 165, 233, 0.3);
    }
    
    div[data-testid="stMetric"]:hover::before { opacity: 1; }

    div[data-testid="stMetric"] label { 
        color: #94a3b8 !important; 
        font-weight: 600 !important; 
        font-size: 0.8rem !important; 
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    
    div[data-testid="stMetric"] [data-testid="stMetricValue"] { 
        font-family: 'JetBrains Mono', monospace !important;
        font-weight: 700 !important; 
        font-size: 2.2rem !important;
        color: #ffffff !important;
        text-shadow: 0 0 10px rgba(255,255,255,0.1);
    }

    /* Expander / Containers */
    div[data-testid="stExpander"] {
        background: rgba(15, 23, 42, 0.5);
        backdrop-filter: blur(12px);
        border: 1px solid rgba(255,255,255,0.05);
        border-radius: 16px;
    }

    /* Tab Styling */
    button[data-baseweb="tab"] {
        background: transparent !important;
        color: #94a3b8 !important;
        font-weight: 600;
    }
    button[data-baseweb="tab"][aria-selected="true"] {
        color: #38bdf8 !important;
        border-bottom-color: #38bdf8 !important;
    }

    /* Buttons */
    .stButton>button {
        background: linear-gradient(135deg, #0284c7 0%, #3b82f6 100%);
        color: white;
        border: 1px solid rgba(255,255,255,0.1);
        border-radius: 12px;
        font-weight: 700;
        letter-spacing: 0.5px;
        padding: 0.6rem 1.5rem;
        transition: all 0.2s ease;
        box-shadow: 0 4px 15px rgba(2, 132, 199, 0.3);
    }
    .stButton>button:hover {
        transform: scale(1.02) translateY(-2px);
        box-shadow: 0 8px 25px rgba(2, 132, 199, 0.5);
        border: 1px solid rgba(255,255,255,0.3);
    }

    /* Divider */
    hr {
        border-color: rgba(255, 255, 255, 0.05) !important;
        margin: 2rem 0;
    }
    
    /* Dataframes */
    [data-testid="stDataFrame"] {
        border-radius: 16px;
        overflow: hidden;
        border: 1px solid rgba(255,255,255,0.08);
        box-shadow: 0 10px 30px rgba(0,0,0,0.4);
    }
    [data-testid="stDataFrame"] table {
        font-family: 'JetBrains Mono', monospace !important;
    }
</style>
""", unsafe_allow_html=True)


# ── INIT STATE ───────────────────────────────────────────
if 'exchange' not in st.session_state:
    st.session_state.exchange = ExchangeManager()
    st.session_state.strategy = StrategyEngine()
    st.session_state.ai_brain = AIBrain()
    st.session_state.breaker = CircuitBreaker()
    st.session_state.sizer = KellyPositionSizer()
    st.session_state.active_signal = None
    st.session_state.initialized = False


# ── LOGIN / REGISTER UI ──────────────────────────────────
if not st.session_state.authenticated:
    # Layout estético centralizado
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 1.5, 1])
    with c2:
        st.markdown("<div class='stExpander' style='padding: 2rem; border-radius: 20px; border: 1px solid rgba(56, 189, 248, 0.3); background: rgba(15, 23, 42, 0.8); box-shadow: 0 10px 40px rgba(0,0,0,0.5); text-align: center;'>", unsafe_allow_html=True)
        st.markdown("<h1 style='text-align:center; font-size: 3rem;'>⚡ TITANIUM <span style='font-weight: 300; color: #94a3b8;'>PRO</span></h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align:center; color: #64748b; font-size: 1.1rem; margin-bottom: 2rem;'>Institutional Algorithmic Trading Access</p>", unsafe_allow_html=True)
        
        tab_log, tab_reg = st.tabs(["🔐 Entrar", "📝 Registro VIP"])
        
        with tab_log:
            with st.form("login_form", clear_on_submit=True):
                usr = st.text_input("Usuario Trader", placeholder="Ej: NeoTrader")
                pwd = st.text_input("Clave Secreta", type="password", placeholder="••••••••")
                submitted = st.form_submit_button("Ingresar al Motor", use_container_width=True)
                
                if submitted:
                    ok, msg = authenticate_user(usr, pwd)
                    if ok:
                        st.session_state.authenticated = True
                        st.session_state.username = usr
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
                        
        with tab_reg:
            with st.form("register_form", clear_on_submit=True):
                new_usr = st.text_input("Nuevo Usuario", placeholder="Crea tu alias")
                new_pwd = st.text_input("Nueva Clave", type="password", placeholder="Mínimo 6 caracteres")
                invite = st.text_input("Passkey VIP (Invitación)", type="password", placeholder="Código de tu patrocinador")
                reg_submitted = st.form_submit_button("Solicitar Acceso", use_container_width=True)
                
                if reg_submitted:
                    rok, rmsg = register_user(new_usr, new_pwd, invite)
                    if rok:
                        st.success(rmsg)
                        st.balloons()
                    else:
                        st.error(rmsg)
                        
        st.markdown("</div>", unsafe_allow_html=True)
    st.stop()


# ── FETCH & ANALYZE ──────────────────────────────────────
# Obtain User Data
usr_data = get_user_data(st.session_state.get('username', ''))
u_key = usr_data.get('binance_api_key', '')
u_sec = usr_data.get('binance_secret', '')

# Modify Demo Mode dynamically if keys exist (User Profile OR Global Env)
has_keys = bool(u_key and u_sec) or bool(config.BINANCE_API_KEY and config.BINANCE_SECRET)
config.DEMO_MODE = not has_keys

# Si usamos llaves globales, las pasamos a la conexión
if not bool(u_key and u_sec) and not config.DEMO_MODE:
    u_key = config.BINANCE_API_KEY
    u_sec = config.BINANCE_SECRET

def fetch_data():
    ex = st.session_state.exchange
    brain = st.session_state.ai_brain
    
    # 1. Background AI check (Non-blocking)
    import threading
    if (time.time() - brain.sentiment_state["last_check"]) > 300:
        threading.Thread(target=brain.analyze_sentiment, daemon=True).start()

    # 2. Parallel Market Data Fetching
    if not st.session_state.initialized or (not config.DEMO_MODE and ex.exchange is None):
        ex.connect(api_key=u_key, api_secret=u_sec)
        st.session_state.initialized = True
    
    # These are now parallelized inside exchange.py
    tf_data = ex.fetch_all_timeframes()
    ob_data = ex.fetch_obi()
    
    for tf in tf_data:
        tf_data[tf] = calculate_all(tf_data[tf])
    return tf_data, ob_data

def get_data():
    return fetch_data()

def safe_val(row, col, default=0):
    v = row.get(col, default)
    return default if pd.isna(v) else float(v)


# ── FETCH & ANALYZE ──────────────────────────────────────
tf_data, ob_data = get_data()
entry_df = tf_data.get(config.TF_ENTRY)
last = entry_df.iloc[-1] if entry_df is not None and len(entry_df) > 0 else None

strategy = st.session_state.strategy
long_s, long_bd, short_s, short_bd, new_sig = strategy.analyze(tf_data, ob_data)

ai_status = st.session_state.ai_brain.sentiment_state
breaker = st.session_state.breaker
sizer = st.session_state.sizer

if new_sig and breaker.can_trade() and not ai_status.get('panic_mode', False):
    st.session_state.active_signal = new_sig

active_signal = st.session_state.active_signal

# Check signal status
if active_signal and last is not None:
    price_now = last['close']
    closed = strategy.check_signal_status(active_signal, price_now)
    if closed:
        pnl = closed.calculate_pnl(price_now)
        breaker.record_trade(pnl)
        sizer.add_trade(pnl)
        st.session_state.active_signal = None
        active_signal = None


# ══════════════════════════════════════════════════════════
# SIDEBAR PROFILE & PORTFOLIO MANAGER
# ══════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("## 👤 Perfil Trader")
    st.caption(f"Conectado como: **{st.session_state.get('username', 'VIP')}**")
    st.divider()
    
    st.markdown("### 🏦 Conexión Portafolio (Binance API)")
    st.markdown("<small style='color: #94a3b8;'>El bot puede manejar tu portafolio y conectar el API de Binance para mejorar la información del mercado y graficar sobre fuego real.</small>", unsafe_allow_html=True)
    
    with st.expander("⚙️ Configurar Llaves (API Key)", expanded=not has_keys):
        with st.form("api_form"):
            in_key = st.text_input("Binance API Key", value=u_key, type="password")
            in_sec = st.text_input("Binance Secret", value=u_sec, type="password")
            if st.form_submit_button("Guardar & Conectar"):
                update_api_keys(st.session_state.username, in_key, in_sec)
                # Forzar reconexión
                st.session_state.initialized = False
                ext = st.session_state.exchange
                if ext.exchange:
                    try:
                        ext.close()
                    except: pass
                st.success("Llaves guardadas. Reiniciando bot...")
                st.rerun()

    status_color = "🟢 LIVE TRADING" if has_keys else "🟠 SIMULACIÓN (DEMO)"
    st.markdown(f"<br><div style='text-align:center; padding: 10px; border-radius: 10px; background: rgba(255,255,255,0.05);'><b>Modo Actual:</b><br/>{status_color}</div>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# HEADER (nativo)
# ══════════════════════════════════════════════════════════
tz = pytz.timezone(config.MY_TIMEZONE)
now_str = datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S')
h_utc = datetime.now(pytz.utc).hour
sessions_active = [s for s in config.SESSIONS.values() if s['start'] <= h_utc < s['end']]
session_str = ' + '.join(f"{s['emoji']} {s['name']}" for s in sessions_active) if sessions_active else '🌙 OFF-HOURS'

ai_reason = ai_status.get('reason', 'OK')
ai_score = ai_status.get('score', 50)
panic = ai_status.get('panic_mode', False)

# ── BLACK SWAN ALERT BANNER ──────────────────────────────
if panic:
    st.markdown(f"""
    <div style="background: linear-gradient(90deg, #991b1b, #ef4444, #991b1b); padding: 1.5rem; border-radius: 12px; margin-bottom: 2rem; border: 1px solid #f87171; box-shadow: 0 10px 40px rgba(220, 38, 38, 0.4); text-align: center;">
        <h1 style="color: white; margin: 0; font-size: 2.2rem; text-shadow: 2px 2px 10px rgba(0,0,0,0.5);">💀 BLACK SWAN DETECTED</h1>
        <p style="color: white; font-weight: 600; font-size: 1.2rem; margin: 0.5rem 0;">{ai_reason}</p>
        <div style="background: white; color: #dc2626; display: inline-block; padding: 0.2rem 1rem; border-radius: 5px; font-weight: 800; letter-spacing: 1px;">TRADING PAUSED</div>
    </div>
    """, unsafe_allow_html=True)

title_col, ai_col = st.columns([3, 1])
with title_col:
    st.title("⚡ TITANIUM v8.0 PRO")
    st.caption(f"{config.SYMBOL}  •  {session_str}  •  {now_str} COT")
with ai_col:
    if not panic:
        score_color = "#4ade80" if ai_score >= 50 else "#f87171"
        st.markdown(f"""
        <div style="text-align: right; padding: 10px; background: rgba(255,255,255,0.03); border-radius: 12px; border: 1px solid rgba(255,255,255,0.05);">
            <div style="color: #94a3b8; font-size: 0.75rem; text-transform: uppercase;">AI Sentiment Score</div>
            <div style="color: {score_color}; font-size: 1.8rem; font-family: 'JetBrains Mono'; font-weight: 700;">{ai_score}</div>
            <div style="color: #cbd5e1; font-size: 0.8rem;">{ai_reason}</div>
        </div>
        """, unsafe_allow_html=True)

st.divider()


# ══════════════════════════════════════════════════════════
# MAIN TRADING DASHBOARD
# ══════════════════════════════════════════════════════════
if last is not None:
    price = last['close']
    obi = ob_data['obi']
    adx = safe_val(last, 'ADX')
    rsi = safe_val(last, 'RSI', 50)
    atr = safe_val(last, 'ATR')
    atr_pct = safe_val(last, 'ATR_pct', 0)
    mh = safe_val(last, 'MACD_hist')
    d_trend, d_strength = get_trend_direction(entry_df)
    m_trend = get_macro_trend_direction(entry_df)

    # -- ROW 1: TRADE & RISK STATUS (The most critical info for the trader) --
    cb = breaker.get_status()
    ks = sizer.get_status()
    can_trade = cb.get('can_trade', True)
    
    col_sig, col_risk = st.columns([1, 1])
    
    with col_sig:
        st.subheader("🎯 Active Trade Status")
        if active_signal:
            st.success(f"ACTIVE: {active_signal.direction} @ ${active_signal.entry:,.1f}")
            s1, s2, s3, s4 = st.columns(4)
            s1.metric("Current Price", f"${price:,.1f}")
            s2.metric("Stop Loss", f"${active_signal.stop_loss:,.1f}", f"-{active_signal.sl_distance:,.1f}", delta_color="inverse")
            s3.metric("Take Profit", f"${active_signal.take_profit:,.1f}", f"+{active_signal.tp_distance:,.1f}")
            s4.metric("Trailing Phase", getattr(active_signal, 'trailing_phase', 'INITIAL'))
        else:
            st.info("⏳ Flat Position. Waiting for 8+ confluence factors...")
            s1, s2, s3, s4 = st.columns(4)
            s1.metric("Current Price", f"${price:,.1f}")
            s2.metric("Trend", d_trend, f"Strength: {d_strength:.0%}")
            s3.metric("OBI Flow", f"{obi:+.3f}")
            s4.metric("Volatility (ATR)", f"{atr:.1f}")

    with col_risk:
        st.subheader("🛡️ Risk Management")
        if can_trade:
            st.success("🟢 BREAKER: ARMED (Trading Active)")
        else:
            st.error(f"🔴 BREAKER: TRIPPED ({cb.get('pause_reason', '?')})")
            
        r1, r2, r3, r4 = st.columns(4)
        daily = cb.get('daily_pnl_pct', 0)
        total = cb.get('total_pnl_pct', 0)
        wr = ks.get('win_rate', 0)
        kelly = ks.get('kelly_pct', config.MIN_POSITION_PCT * 100)
        
        r1.metric("Daily P&L", f"{daily:+.2f}%")
        r2.metric("Total Equity", f"{total:+.2f}%")
        r3.metric("Win Rate", f"{wr:.0f}%")
        r4.metric("Kelly Size", f"{kelly:.1f}%")

    st.divider()

    # -- ROW 2: FULL WIDTH CHART --
    st.subheader("📊 Market Action")
    if entry_df is not None and len(entry_df) > 10:
        fig = go.Figure()

        fig.add_trace(go.Candlestick(
            x=entry_df['time'], open=entry_df['open'],
            high=entry_df['high'], low=entry_df['low'], close=entry_df['close'],
            increasing_line_color='#4ade80', decreasing_line_color='#f87171',
            increasing_fillcolor='rgba(34,197,94,0.3)', decreasing_fillcolor='rgba(239,68,68,0.3)',
            name='BTC/USDT'
        ))

        if 'EMA_FAST' in entry_df.columns:
            fig.add_trace(go.Scatter(x=entry_df['time'], y=entry_df['EMA_FAST'], line=dict(color='#60a5fa', width=1.5), name=f'EMA {config.EMA_FAST}', opacity=0.8))
            fig.add_trace(go.Scatter(x=entry_df['time'], y=entry_df['EMA_MID'], line=dict(color='#a78bfa', width=1.5), name=f'EMA {config.EMA_MID}', opacity=0.8))
            fig.add_trace(go.Scatter(x=entry_df['time'], y=entry_df['EMA_SLOW'], line=dict(color='#f472b6', width=1.5), name=f'EMA {config.EMA_SLOW}', opacity=0.8))

        if 'BB_upper' in entry_df.columns:
            fig.add_trace(go.Scatter(x=entry_df['time'], y=entry_df['BB_upper'], line=dict(color='rgba(148,163,184,0.3)', width=1, dash='dot'), name='BB Upper', showlegend=False))
            fig.add_trace(go.Scatter(x=entry_df['time'], y=entry_df['BB_lower'], line=dict(color='rgba(148,163,184,0.3)', width=1, dash='dot'), name='BB Lower', fill='tonexty', fillcolor='rgba(148,163,184,0.04)', showlegend=False))

        if active_signal:
            fig.add_hline(y=active_signal.entry, line_dash="dash", line_color="#facc15", line_width=1, annotation_text=f"Entry: {active_signal.entry:,.1f}")
            fig.add_hline(y=active_signal.stop_loss, line_dash="dash", line_color="#f87171", line_width=1, annotation_text=f"SL: {active_signal.stop_loss:,.1f}")
            fig.add_hline(y=active_signal.take_profit, line_dash="dash", line_color="#4ade80", line_width=1, annotation_text=f"TP: {active_signal.take_profit:,.1f}")

        # Premium Plotly Tweaks
        fig.update_layout(
            template='plotly_dark',
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(10,15,30,0.6)',
            height=550,
            margin=dict(l=5, r=5, t=15, b=5),
            xaxis=dict(gridcolor='rgba(255,255,255,0.03)', rangeslider=dict(visible=False), showline=False),
            yaxis=dict(gridcolor='rgba(255,255,255,0.03)', side='right', showline=False),
            legend=dict(orientation='h', yanchor='bottom', y=1.02, font=dict(size=12, family="JetBrains Mono")),
        )
        st.plotly_chart(fig, use_container_width=True, key="main_chart")

    st.divider()

    # -- ROW 3: CONFLUENCE INTEL --
    st.subheader("🧮 Confluence Engine Details")
    c_left, c_right = st.columns([2, 1])
    
    with c_left:
        st.write("**Real-Time Signal Score**")
        pcol1, pcol2 = st.columns(2)
        with pcol1:
            st.progress(min(long_s, 100), text=f"🟢 LONG: {long_s}/100")
        with pcol2:
            st.progress(min(short_s, 100), text=f"🔴 SHORT: {short_s}/100")
            
        bd = long_bd if long_s >= short_s else short_bd
        if bd:
            cols = st.columns(4)
            for i, (k, (sc, mx)) in enumerate(bd.items()):
                icon = '✅' if sc >= mx * 0.6 else ('⚠️' if sc > 0 else '❌')
                cols[i % 4].caption(f"{icon} **{k}**: {sc}/{mx}")
                
    with c_right:
        st.write("**Pattern Recognition**")
        i1, i2 = st.columns(2)
        mkt_s = last.get('market_structure', 'RANGING')
        rsi_div = last.get('rsi_divergence', 'NONE')
        
        i1.metric("Macro Trend", m_trend.replace('MACRO_', ''))
        i2.metric("Micro Struct", mkt_s.replace('_STRUCT', '').replace('_', ' '))
        
        c_mac1, c_mac2 = st.columns(2)
        c_mac1.metric("MACD Core", f"{abs(mh):.1f} {'▲' if mh > 0 else '▼'}")
        c_mac2.metric("RSI State", f"{rsi:.1f}")
        
        if rsi_div != 'NONE':
            st.caption(f"⚡ Smart Divergence spotted: **{rsi_div}**")

st.divider()

# ══════════════════════════════════════════════════════════
# TABS: HISTORY & BACKTESTING
# ══════════════════════════════════════════════════════════
tab1, tab2 = st.tabs(["📋 Trade History", "🧪 Backtesting Engine"])

with tab1:
    history = list(strategy.signal_history)
    if history:
        h_data = []
        for sig in history[-15:]:
            h_data.append({
                'Time': sig.timestamp.astimezone(tz).strftime('%H:%M:%S'),
                'Dir': f"{'🟢' if sig.direction == 'LONG' else '🔴'} {sig.direction}",
                'Score': sig.score,
                'Entry': f"${sig.entry:,.1f}",
                'SL': f"${sig.stop_loss:,.1f}",
                'TP': f"${sig.take_profit:,.1f}",
                'R:R': f"1:{sig.risk_reward:.1f}",
                'Status': sig.status,
            })
        st.dataframe(pd.DataFrame(h_data), hide_index=True, use_container_width=True)
    else:
        st.info("No trades executed yet in this session.")

with tab2:
    bt_col1, bt_col2, bt_col3, bt_col4 = st.columns(4)
    with bt_col1:
        bt_bars = st.number_input("Barras a Evaluar", min_value=500, max_value=10000,
                                   value=3000, step=500, key="bt_bars")
    with bt_col2:
        bt_threshold = st.number_input("Score mínimo (Confluencia)", min_value=20, max_value=90,
                                        value=65, step=5, key="bt_threshold")
    with bt_col3:
        bt_tp = st.number_input("ATR Take Profit Mult", min_value=1.0, max_value=5.0,
                                 value=2.5, step=0.5, key="bt_tp")
    with bt_col4:
        bt_sl = st.number_input("ATR Stop Loss Mult", min_value=0.5, max_value=3.0,
                                 value=1.5, step=0.5, key="bt_sl")

    if st.button("🚀 Run Institutional Backtest", key="run_bt", type="primary"):
        with st.spinner("Compiling Synthetic Data & Running Matrix..."):
            from backtest import TitaniumBacktester, MonteCarloSimulator, generate_test_data

            data = generate_test_data(int(bt_bars))
            bt = TitaniumBacktester(initial_capital=10000)
            result = bt.run(data, int(bt_threshold), bt_tp, bt_sl)
            mc = MonteCarloSimulator(500)
            mc_result = mc.analyze(result['returns'])

            st.session_state['bt_result'] = result
            st.session_state['mc_result'] = mc_result

    if 'bt_result' in st.session_state:
        result = st.session_state['bt_result']
        mc_result = st.session_state['mc_result']
        m = result['metrics']

        st.markdown("### 📊 Strategy Performance")
        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric("Return Total", f"{m['total_return']:+.2f}%")
        m2.metric("Sharpe Ratio", f"{m['sharpe_ratio']:.3f}")
        m3.metric("Sortino Ratio", f"{m['sortino_ratio']:.3f}")
        m4.metric("Max Drawdown", f"{m['max_drawdown']:.2f}%")
        m5.metric("Win Rate", f"{m['win_rate']:.1f}%")
        m6.metric("Profit Factor", f"{m['profit_factor']:.2f}")

        eq = result['equity']
        fig_eq = go.Figure()
        fig_eq.add_trace(go.Scatter(
            x=list(range(len(eq))), y=eq.values,
            fill='tozeroy', fillcolor='rgba(96,165,250,0.1)',
            line=dict(color='#60a5fa', width=2),
            name='Equity'
        ))
        fig_eq.add_hline(y=10000, line_dash="dash", line_color="#94a3b8", annotation_text="Capital Base: $10,000")
        fig_eq.update_layout(
            template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(17,24,39,0.8)',
            height=300, margin=dict(l=10, r=10, t=30, b=10), yaxis=dict(gridcolor='rgba(255,255,255,0.04)'), xaxis=dict(gridcolor='rgba(255,255,255,0.04)')
        )
        st.plotly_chart(fig_eq, use_container_width=True)

        st.markdown("### 🎲 Monte Carlo Stress Test (500 Sims)")
        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("Expected Return", f"{mc_result['expected_return']:+.2f}%")
        mc2.metric("P(Loss)", f"{mc_result['probability_of_loss']:.1f}%")
        mc3.metric("Expected Drawdown", f"{mc_result['expected_max_dd']:.2f}%")
        mc4.metric("Worst Case DD", f"{mc_result['worst_case_dd']:.2f}%")
        st.caption(f"95% Confidence Interval: [{mc_result['return_ci_low']:+.2f}%, {mc_result['return_ci_high']:+.2f}%]")

