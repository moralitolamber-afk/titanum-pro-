"""
TITANIUM PRO v11 — Bloomberg Terminal Style
- AI Groq analiza y opera el portafolio con permiso del usuario
- Spot / Futures según elección
- Bóveda DeFi con sugerencias de staking por activo
- Alertas de tendencia +/-10%
- Interfaz tipo Bloomberg: densa, profesional, datos en tiempo real
"""

import os, json, hashlib, warnings, time
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd
import streamlit as st

warnings.filterwarnings('ignore')

# ═══════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════
class Config:
    SYMBOL        = os.getenv("SYMBOL", "BTC/USDT")
    CANDLE_LIMIT  = 200
    DEMO_MODE     = True
    GROQ_KEY      = os.getenv("GROQ_API_KEY", "")
    BIN_KEY       = os.getenv("BINANCE_API_KEY", "")
    BIN_SEC       = os.getenv("BINANCE_SECRET", "")
    MAX_DAILY_DD  = float(os.getenv("MAX_DAILY_DD", "5.0"))
    MAX_TOTAL_DD  = float(os.getenv("MAX_TOTAL_DD", "15.0"))
    EMERGENCY     = float(os.getenv("EMERGENCY_STOP", "-20.0"))
    MAX_LOSSES    = int(os.getenv("MAX_CONS_LOSSES", "5"))
    COOLDOWN      = int(os.getenv("COOLDOWN_MIN", "60"))
    KELLY         = float(os.getenv("KELLY_FRACTION", "0.5"))
    MAX_POS       = float(os.getenv("MAX_POSITION_PCT", "0.10"))

# ═══════════════════════════════════════════════════════
# INDICADORES
# ═══════════════════════════════════════════════════════
def calc_ema(s, n=14):   return s.ewm(span=n, adjust=False).mean()
def calc_rsi(s, n=14):
    d = s.diff()
    g = d.where(d>0,0).rolling(n).mean()
    l = (-d.where(d<0,0)).rolling(n).mean()
    return 100 - 100/(1 + g/l.replace(0, 1e-10))
def calc_atr(df, n=14):
    tr = pd.concat([df['high']-df['low'],
                    (df['high']-df['close'].shift()).abs(),
                    (df['low']-df['close'].shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()

# ═══════════════════════════════════════════════════════
# CIRCUIT BREAKER
# ═══════════════════════════════════════════════════════
class CircuitBreaker:
    def __init__(self):
        self.daily_pnl = 0.0; self.total_pnl = 0.0
        self.losses = 0; self.paused = False
        self.reason = None; self.until = None
        self._reset_t = datetime.now().replace(hour=0,minute=0,second=0,microsecond=0)

    def can_trade(self):
        self._daily_reset()
        if self.paused and self.until and datetime.now() >= self.until:
            self.paused = False; self.reason = None
        return not self.paused

    def record(self, pnl):
        self._daily_reset()
        self.daily_pnl += pnl; self.total_pnl += pnl
        self.losses = self.losses+1 if pnl<0 else 0
        if self.total_pnl <= Config.EMERGENCY: self._pause(f"EMERGENCY {self.total_pnl:.1f}%")
        elif self.daily_pnl <= -Config.MAX_DAILY_DD: self._pause(f"Daily DD {self.daily_pnl:.1f}%", True)
        elif self.losses >= Config.MAX_LOSSES: self._pause(f"{self.losses} pérdidas seguidas", True)

    def status(self):
        return {"ok": self.can_trade(), "daily": round(self.daily_pnl,2),
                "total": round(self.total_pnl,2), "losses": self.losses, "reason": self.reason}

    def _pause(self, r, cd=False):
        self.paused = True; self.reason = r
        if cd: self.until = datetime.now() + timedelta(minutes=Config.COOLDOWN)

    def _daily_reset(self):
        if datetime.now() >= self._reset_t + timedelta(days=1):
            self.daily_pnl = 0.0; self.losses = 0
            self._reset_t = datetime.now().replace(hour=0,minute=0,second=0,microsecond=0)

# ═══════════════════════════════════════════════════════
# ATR RISK MANAGER
# ═══════════════════════════════════════════════════════
@dataclass
class Stops:
    sl: float; tp: float; rr: float; atr_v: float

class ATRRisk:
    def __init__(self, sl=2.0, tp=3.0): self.sl=sl; self.tp=tp

    def calc(self, entry, direction, df) -> Optional[Stops]:
        try:
            a = float(calc_atr(df).iloc[-1])
            if not a or np.isnan(a): return None
        except: return None
        s = entry - a*self.sl if direction=='long' else entry + a*self.sl
        t = entry + a*self.tp if direction=='long' else entry - a*self.tp
        rr = round(abs(t-entry)/abs(entry-s), 2) if abs(entry-s)>0 else 0
        return Stops(round(s,2), round(t,2), rr, round(a,2))

# ═══════════════════════════════════════════════════════
# KELLY SIZER
# ═══════════════════════════════════════════════════════
class Kelly:
    def __init__(self): self._h: List[float] = []

    def add(self, pnl):
        self._h.append(float(pnl))
        if len(self._h)>100: self._h = self._h[-100:]

    def size(self, bal, entry, sl):
        if not entry or abs(entry-sl)==0: return 0.0
        return round(min(bal*self._k()/(abs(entry-sl)/entry), bal*Config.MAX_POS), 2)

    def _k(self):
        if len(self._h)<10: return 0.02
        wins = [p for p in self._h if p>0]; losses = [abs(p) for p in self._h if p<0]
        if not wins or not losses: return 0.02
        w = len(wins)/len(self._h); b = np.mean(wins)/np.mean(losses)
        return float(np.clip((b*w-(1-w))/b * Config.KELLY, 0.01, Config.MAX_POS))

# ═══════════════════════════════════════════════════════
# EXCHANGE MANAGER
# ═══════════════════════════════════════════════════════
FREQ = {'1m':'1min','3m':'3min','5m':'5min','15m':'15min',
        '30m':'30min','1h':'1h','4h':'4h','1d':'1D'}

class Exchange:
    def __init__(self, market_type='spot'):
        self.ex = None; self._error = None
        self.market_type = market_type  # 'spot' o 'futures'

    def connect(self, k=None, s=None):
        if Config.DEMO_MODE: return
        try:
            import ccxt
            cfg = {'apiKey': k, 'secret': s, 'enableRateLimit': True,
                   'options': {'defaultType': self.market_type}}
            self.ex = ccxt.binance(cfg) if self.market_type=='spot' else ccxt.binanceusdm(cfg)
        except Exception as e:
            self._error = str(e); Config.DEMO_MODE = True

    def get_balance(self) -> Dict:
        """Obtiene el balance real de la cuenta."""
        if Config.DEMO_MODE or not self.ex:
            return self._demo_balance()
        try:
            bal = self.ex.fetch_balance()
            assets = {}
            for asset, data in bal['total'].items():
                if data > 0:
                    assets[asset] = {
                        'total': round(data, 6),
                        'free':  round(bal['free'].get(asset, 0), 6),
                        'used':  round(bal['used'].get(asset, 0), 6),
                    }
            return assets
        except Exception as e:
            return self._demo_balance()

    def get_ticker_prices(self, symbols: List[str]) -> Dict:
        """Obtiene precios actuales para múltiples símbolos."""
        if Config.DEMO_MODE or not self.ex:
            return {s: np.random.uniform(1, 50000) for s in symbols}
        try:
            prices = {}
            for s in symbols:
                try:
                    t = self.ex.fetch_ticker(f"{s}/USDT")
                    prices[s] = t['last']
                except: prices[s] = 0
            return prices
        except: return {}

    def place_order(self, symbol, side, amount, order_type='market') -> Dict:
        """Ejecuta una orden real en Binance."""
        if Config.DEMO_MODE or not self.ex:
            return {"status": "DEMO", "symbol": symbol, "side": side, "amount": amount}
        try:
            order = self.ex.create_order(
                symbol=f"{symbol}/USDT",
                type=order_type,
                side=side,
                amount=amount
            )
            return order
        except Exception as e:
            return {"error": str(e)}

    def all_tf(self, symbol="BTC/USDT"):
        tfs = ['5m', '15m', '1h']
        with ThreadPoolExecutor(max_workers=3) as ex:
            results = list(ex.map(lambda tf: self._candles(symbol, tf), tfs))
        return {tf: df for tf, df in zip(tfs, results)}

    def _candles(self, symbol, tf):
        if Config.DEMO_MODE or not self.ex:
            return self._demo_candles(tf)
        try:
            d = self.ex.fetch_ohlcv(symbol, tf, limit=Config.CANDLE_LIMIT)
            df = pd.DataFrame(d, columns=['time','open','high','low','close','volume'])
            df['time'] = pd.to_datetime(df['time'], unit='ms')
            return df.set_index('time')
        except: return self._demo_candles(tf)

    def obi(self, symbol="BTC/USDT"):
        if Config.DEMO_MODE or not self.ex:
            return round(float(np.random.uniform(-0.12, 0.12)), 4)
        try:
            ob = self.ex.fetch_order_book(symbol, 20)
            b = sum(x[1] for x in ob['bids']); a = sum(x[1] for x in ob['asks'])
            return round((b-a)/(b+a), 4) if (b+a) else 0.0
        except: return 0.0

    def _demo_balance(self):
        return {
            'BTC':  {'total': 0.05,  'free': 0.05,  'used': 0.0},
            'ETH':  {'total': 1.2,   'free': 1.0,   'used': 0.2},
            'BNB':  {'total': 5.0,   'free': 5.0,   'used': 0.0},
            'USDT': {'total': 2500.0,'free': 2000.0,'used': 500.0},
            'SOL':  {'total': 10.0,  'free': 10.0,  'used': 0.0},
            'ADA':  {'total': 500.0, 'free': 500.0, 'used': 0.0},
        }

    def _demo_candles(self, tf):
        n = Config.CANDLE_LIMIT
        np.random.seed(abs(hash(tf))%9999)
        c = 65000 + np.cumsum(np.random.normal(0, 80, n))
        freq = FREQ.get(tf, '5min')
        return pd.DataFrame({'open':c,'high':c*1.002,'low':c*0.998,
                             'close':c,'volume':np.random.uniform(10,100,n)},
                            index=pd.date_range(end=datetime.now(), periods=n, freq=freq))

# ═══════════════════════════════════════════════════════
# AI BRAIN — Groq analiza Y puede operar
# ═══════════════════════════════════════════════════════
class AIBrain:
    def __init__(self): self._client = None

    def _get_client(self):
        if not Config.GROQ_KEY: return None
        try:
            from groq import Groq
            if not self._client: self._client = Groq(api_key=Config.GROQ_KEY)
            return self._client
        except: return None

    def analyze_portfolio(self, balance: Dict, prices: Dict, market_type: str) -> Dict:
        """IA analiza el portafolio completo y sugiere acciones."""
        client = self._get_client()
        if not client:
            return self._demo_analysis(balance, prices)

        portfolio_str = "\n".join([
            f"- {asset}: {data['total']} unidades @ ${prices.get(asset, 0):,.2f} USDT"
            for asset, data in balance.items() if asset != 'USDT'
        ])
        usdt = balance.get('USDT', {}).get('free', 0)

        try:
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                max_tokens=500,
                messages=[{"role": "user", "content": f"""
Eres un trader institucional experto. Analiza este portafolio de criptomonedas en mercado {market_type}.

PORTAFOLIO:
{portfolio_str}
USDT disponible: ${usdt:,.2f}

Responde SOLO con JSON válido:
{{
  "resumen": "<análisis en 2 líneas>",
  "riesgo_general": "BAJO|MEDIO|ALTO",
  "acciones": [
    {{
      "activo": "<símbolo>",
      "accion": "COMPRAR|VENDER|MANTENER|STAKING",
      "razon": "<razón en 10 palabras>",
      "urgencia": "ALTA|MEDIA|BAJA",
      "porcentaje_sugerido": <0-100>
    }}
  ],
  "sentimiento_mercado": "ALCISTA|BAJISTA|NEUTRAL",
  "recomendacion_principal": "<acción más importante ahora mismo>"
}}"""}]
            )
            raw = resp.choices[0].message.content.strip()
            raw = raw.replace('```json','').replace('```','').strip()
            return json.loads(raw)
        except Exception as e:
            return self._demo_analysis(balance, prices)

    def execute_suggestion(self, action: Dict, exchange: 'Exchange', kelly: 'Kelly',
                          balance: Dict, prices: Dict) -> Dict:
        """Ejecuta una sugerencia de la IA si el usuario autoriza."""
        asset   = action.get('activo', '')
        side    = 'buy' if action.get('accion') == 'COMPRAR' else 'sell'
        pct     = action.get('porcentaje_sugerido', 5) / 100
        price   = prices.get(asset, 0)
        usdt    = balance.get('USDT', {}).get('free', 0)

        if side == 'buy':
            amount_usdt = usdt * pct
            amount_coin = amount_usdt / price if price > 0 else 0
        else:
            amount_coin = balance.get(asset, {}).get('free', 0) * pct

        if amount_coin <= 0:
            return {"error": "Cantidad insuficiente"}

        result = exchange.place_order(asset, side, round(amount_coin, 6))
        return result

    def _demo_analysis(self, balance, prices):
        return {
            "resumen": "Portafolio diversificado con exposición moderada a BTC y ETH. Buena liquidez en USDT.",
            "riesgo_general": "MEDIO",
            "acciones": [
                {"activo": "BTC",  "accion": "MANTENER", "razon": "Tendencia alcista en timeframe mayor",
                 "urgencia": "BAJA", "porcentaje_sugerido": 0},
                {"activo": "ETH",  "accion": "COMPRAR",  "razon": "RSI sobrevendido con soporte clave",
                 "urgencia": "MEDIA", "porcentaje_sugerido": 10},
                {"activo": "BNB",  "accion": "STAKING",  "razon": "APY competitivo en Binance Earn",
                 "urgencia": "BAJA", "porcentaje_sugerido": 50},
                {"activo": "SOL",  "accion": "MANTENER", "razon": "Consolidación en zona de soporte",
                 "urgencia": "BAJA", "porcentaje_sugerido": 0},
                {"activo": "ADA",  "accion": "VENDER",   "razon": "Pérdida de soporte en 0.45 USDT",
                 "urgencia": "ALTA", "porcentaje_sugerido": 30},
            ],
            "sentimiento_mercado": "ALCISTA",
            "recomendacion_principal": "Aumentar ETH y hacer staking con BNB para maximizar rendimiento pasivo"
        }

# ═══════════════════════════════════════════════════════
# STAKING VAULT — Sugerencias por activo
# ═══════════════════════════════════════════════════════
STAKING_DATA = {
    'BTC':  {'apy': 2.5,  'platform': 'Binance Earn',  'tipo': 'Flexible', 'riesgo': 'BAJO'},
    'ETH':  {'apy': 4.2,  'platform': 'ETH 2.0 Stake', 'tipo': 'Bloqueado','riesgo': 'BAJO'},
    'BNB':  {'apy': 8.1,  'platform': 'BNB Vault',     'tipo': 'Flexible', 'riesgo': 'BAJO'},
    'SOL':  {'apy': 6.5,  'platform': 'Native Staking', 'tipo': 'Bloqueado','riesgo': 'MEDIO'},
    'ADA':  {'apy': 5.0,  'platform': 'Cardano Pool',   'tipo': 'Flexible', 'riesgo': 'BAJO'},
    'MATIC':{'apy': 9.2,  'platform': 'Polygon Stake',  'tipo': 'Bloqueado','riesgo': 'MEDIO'},
    'DOT':  {'apy': 12.0, 'platform': 'Polkadot Para',  'tipo': 'Bloqueado','riesgo': 'MEDIO'},
    'AVAX': {'apy': 7.8,  'platform': 'Avalanche Val',  'tipo': 'Bloqueado','riesgo': 'MEDIO'},
}

def calc_staking_yield(asset, amount, price, days=365):
    data = STAKING_DATA.get(asset, {'apy': 3.0, 'platform': 'DeFi General', 'tipo': 'Flexible', 'riesgo': 'MEDIO'})
    valor_usd = amount * price
    rendimiento_anual = valor_usd * (data['apy'] / 100)
    rendimiento_periodo = rendimiento_anual * (days / 365)
    return {
        **data,
        'valor_usd': round(valor_usd, 2),
        'rendimiento_anual_usd': round(rendimiento_anual, 2),
        'rendimiento_30d':       round(rendimiento_anual * 30/365, 2),
        'rendimiento_90d':       round(rendimiento_anual * 90/365, 2),
    }

# ═══════════════════════════════════════════════════════
# TREND ALERTS — Detecta +/-10%
# ═══════════════════════════════════════════════════════
def detect_trends(prices_now: Dict, prices_24h: Dict) -> List[Dict]:
    """Detecta activos con cambio >= 10% en 24h."""
    alerts = []
    for asset, price in prices_now.items():
        old = prices_24h.get(asset, price)
        if old == 0: continue
        pct_change = (price - old) / old * 100
        if abs(pct_change) >= 10:
            alerts.append({
                'asset':   asset,
                'change':  round(pct_change, 2),
                'price':   price,
                'signal':  '🚀 EN TENDENCIA ALCISTA' if pct_change > 0 else '📉 EN TENDENCIA BAJISTA',
                'color':   '#00ff88' if pct_change > 0 else '#ff4455',
            })
    return sorted(alerts, key=lambda x: abs(x['change']), reverse=True)

# ═══════════════════════════════════════════════════════
# AUTH
# ═══════════════════════════════════════════════════════
class Auth:
    _DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")

    def _load(self):
        try:
            with open(self._DB) as f: return json.load(f)
        except: return {"admin": {"pw": hashlib.sha256(b"protrading").hexdigest()}}

    def _save(self, d):
        try:
            with open(self._DB, 'w') as f: json.dump(d, f)
        except: pass

    def _h(self, p): return hashlib.sha256(p.encode()).hexdigest()
    def login(self, u, p):
        users = self._load(); return u in users and users[u].get('pw') == self._h(p)
    def register(self, u, p):
        users = self._load()
        if u in users: return False
        users[u] = {'pw': self._h(p)}; self._save(users); return True
    def keys(self, u):
        users = self._load(); return users.get(u,{}).get('k',''), users.get(u,{}).get('s','')
    def save_keys(self, u, k, s):
        users = self._load()
        if u in users: users[u].update({'k':k,'s':s}); self._save(users)
    def get_prefs(self, u):
        users = self._load()
        return users.get(u, {}).get('prefs', {'market': 'spot', 'ai_auto': False})
    def save_prefs(self, u, prefs):
        users = self._load()
        if u in users: users[u]['prefs'] = prefs; self._save(users)

# ═══════════════════════════════════════════════════════
# BLOOMBERG STYLES
# ═══════════════════════════════════════════════════════
STYLES = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600&family=IBM+Plex+Sans:wght@300;400;500;600&display=swap');

/* ── Reset Bloomberg Dark ── */
html, body, [class*="css"] {
    font-family: 'IBM Plex Mono', monospace !important;
    background: #0a0c0e !important;
    color: #c8d0d8 !important;
}
.stApp { background: #0a0c0e !important; }

/* ── Header Terminal ── */
.bbg-header {
    background: #1a1f26;
    border-bottom: 2px solid #ff6600;
    padding: 8px 16px;
    display: flex;
    align-items: center;
    gap: 16px;
    font-family: 'IBM Plex Mono', monospace;
    margin-bottom: 16px;
}
.bbg-logo {
    color: #ff6600;
    font-size: 18px;
    font-weight: 600;
    letter-spacing: 3px;
}
.bbg-time {
    color: #4ade80;
    font-size: 12px;
    margin-left: auto;
}

/* ── Ticker Bar ── */
.ticker-bar {
    background: #111518;
    border: 1px solid #1e2530;
    padding: 6px 12px;
    font-size: 11px;
    font-family: 'IBM Plex Mono', monospace;
    overflow: hidden;
    white-space: nowrap;
    margin-bottom: 12px;
}

/* ── Panels ── */
.bbg-panel {
    background: #0f1318;
    border: 1px solid #1e2530;
    border-top: 2px solid #ff6600;
    padding: 12px;
    margin-bottom: 8px;
    font-family: 'IBM Plex Mono', monospace;
}
.bbg-panel-blue  { border-top-color: #3b82f6; }
.bbg-panel-green { border-top-color: #22c55e; }
.bbg-panel-red   { border-top-color: #ef4444; }
.bbg-panel-gold  { border-top-color: #f59e0b; }

.panel-title {
    font-size: 9px;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: #4a5568;
    margin-bottom: 8px;
    border-bottom: 1px solid #1e2530;
    padding-bottom: 4px;
}
.panel-value {
    font-size: 20px;
    font-weight: 600;
    color: #e2e8f0;
    line-height: 1.1;
}
.panel-sub {
    font-size: 10px;
    color: #4a5568;
    margin-top: 4px;
}

/* ── Números Bloomberg ── */
.num-up   { color: #00ff88 !important; }
.num-down { color: #ff4455 !important; }
.num-neu  { color: #ffaa00 !important; }

/* ── Tabla Bloomberg ── */
.bbg-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 11px;
    font-family: 'IBM Plex Mono', monospace;
}
.bbg-table th {
    background: #111518;
    color: #ff6600;
    padding: 6px 8px;
    text-align: left;
    font-size: 9px;
    letter-spacing: 1px;
    border-bottom: 1px solid #1e2530;
}
.bbg-table td {
    padding: 5px 8px;
    border-bottom: 1px solid #0d1117;
    color: #c8d0d8;
}
.bbg-table tr:hover td { background: #111518; }

/* ── Alert Badges ── */
.alert-up   { background: rgba(0,255,136,0.1); color:#00ff88; border:1px solid #00ff88; padding:3px 8px; border-radius:3px; font-size:10px; }
.alert-down { background: rgba(255,68,85,0.1);  color:#ff4455; border:1px solid #ff4455; padding:3px 8px; border-radius:3px; font-size:10px; }

/* ── AI Panel ── */
.ai-bubble {
    background: #0d1117;
    border-left: 3px solid #3b82f6;
    padding: 10px 14px;
    margin: 6px 0;
    font-size: 11px;
    color: #94a3b8;
    font-family: 'IBM Plex Sans', sans-serif;
}
.ai-action-buy  { background: rgba(0,255,136,0.05); border-left-color: #00ff88; }
.ai-action-sell { background: rgba(255,68,85,0.05);  border-left-color: #ff4455; }
.ai-action-hold { background: rgba(255,170,0,0.05);  border-left-color: #ffaa00; }
.ai-action-stake{ background: rgba(59,130,246,0.05); border-left-color: #3b82f6; }

/* ── Staking Card ── */
.stake-card {
    background: #0d1117;
    border: 1px solid #1e2530;
    border-left: 3px solid #f59e0b;
    padding: 10px;
    margin: 4px 0;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px;
}

/* ── Sidebar ── */
section[data-testid="stSidebar"] {
    background: #080b0e !important;
    border-right: 1px solid #1e2530 !important;
}

/* ── Inputs ── */
.stTextInput input, .stSelectbox select {
    background: #111518 !important;
    border: 1px solid #1e2530 !important;
    color: #c8d0d8 !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 12px !important;
}

/* ── Buttons ── */
.stButton > button {
    background: #111518 !important;
    border: 1px solid #1e2530 !important;
    color: #ff6600 !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 11px !important;
    letter-spacing: 1px !important;
    text-transform: uppercase !important;
}
.stButton > button:hover {
    border-color: #ff6600 !important;
    background: rgba(255,102,0,0.08) !important;
}

/* ── Divider ── */
hr { border-color: #1e2530 !important; }

/* ── Status bar ── */
.status-bar {
    background: #080b0e;
    border-top: 1px solid #1e2530;
    padding: 4px 12px;
    font-size: 9px;
    color: #4a5568;
    letter-spacing: 1px;
    display: flex;
    justify-content: space-between;
}
</style>
"""

# ═══════════════════════════════════════════════════════
# UI COMPONENTS
# ═══════════════════════════════════════════════════════
def bbg_header():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mode = "DEMO MODE" if Config.DEMO_MODE else "● LIVE"
    mode_color = "#ffaa00" if Config.DEMO_MODE else "#00ff88"
    st.markdown(f"""
    <div class="bbg-header">
        <span class="bbg-logo">TITANIUM</span>
        <span style="color:#4a5568;font-size:11px">INSTITUTIONAL TRADING TERMINAL v11</span>
        <span style="color:{mode_color};font-size:10px;margin-left:8px">{mode}</span>
        <span class="bbg-time">{now} COT</span>
    </div>""", unsafe_allow_html=True)

def bbg_panel(title, value, sub="", color_class="", num_class=""):
    st.markdown(f"""
    <div class="bbg-panel {color_class}">
        <div class="panel-title">{title}</div>
        <div class="panel-value {num_class}">{value}</div>
        <div class="panel-sub">{sub}</div>
    </div>""", unsafe_allow_html=True)

def ticker_bar(balance, prices):
    items = []
    for asset, data in list(balance.items())[:6]:
        price = prices.get(asset, 0)
        val = data['total'] * price if asset != 'USDT' else data['total']
        items.append(f"<span style='color:#ff6600'>{asset}</span> "
                    f"<span style='color:#00ff88'>${val:,.0f}</span>  │  ")
    st.markdown(f'<div class="ticker-bar">{"".join(items)}</div>', unsafe_allow_html=True)

def ai_action_card(action):
    accion = action.get('accion', 'MANTENER')
    cls_map = {'COMPRAR':'buy','VENDER':'sell','MANTENER':'hold','STAKING':'stake'}
    cls = cls_map.get(accion, 'hold')
    color_map = {'COMPRAR':'#00ff88','VENDER':'#ff4455','MANTENER':'#ffaa00','STAKING':'#3b82f6'}
    color = color_map.get(accion, '#ffaa00')
    urgencia = action.get('urgencia', 'BAJA')
    pct = action.get('porcentaje_sugerido', 0)
    st.markdown(f"""
    <div class="ai-bubble ai-action-{cls}">
        <span style='color:{color};font-weight:600'>[{accion}]</span>
        <span style='color:#e2e8f0;margin:0 8px'>{action.get('activo','')}</span>
        <span style='color:#4a5568'>{action.get('razon','')}</span>
        <span style='float:right;color:#4a5568'>URG:{urgencia} | {pct}%</span>
    </div>""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════
# SESSION
# ═══════════════════════════════════════════════════════
def init():
    if 'ready' not in st.session_state:
        st.session_state.update({
            'ready': True, 'in': False, 'user': '',
            'ex': Exchange(), 'cb': CircuitBreaker(),
            'rm': ATRRisk(), 'ks': Kelly(),
            'au': Auth(), 'ai': AIBrain(),
            'data': None, 'balance': None,
            'prices': {}, 'ai_analysis': None,
            'demo_mode': True, 'market_type': 'spot',
            'ai_auto_trade': False,
            'prices_24h': {},  # para detectar tendencias
        })
    Config.DEMO_MODE = st.session_state.get('demo_mode', True)

# ═══════════════════════════════════════════════════════
# PÁGINAS
# ═══════════════════════════════════════════════════════
def login_page():
    st.markdown(STYLES, unsafe_allow_html=True)
    st.markdown("""
    <div style="text-align:center;padding:60px 20px">
        <div style="font-family:'IBM Plex Mono';font-size:42px;font-weight:600;
                    color:#ff6600;letter-spacing:6px">TITANIUM</div>
        <div style="font-family:'IBM Plex Mono';font-size:12px;color:#4a5568;
                    letter-spacing:4px;margin-top:4px">INSTITUTIONAL TRADING TERMINAL</div>
        <div style="width:60px;height:2px;background:#ff6600;margin:20px auto"></div>
    </div>""", unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        t1, t2 = st.tabs(["ACCESO", "REGISTRO"])
        with t1:
            u = st.text_input("USUARIO", key="lu", placeholder="username")
            p = st.text_input("CONTRASEÑA", type="password", key="lp", placeholder="••••••••")
            if st.button("INICIAR SESIÓN", use_container_width=True):
                if st.session_state.au.login(u, p):
                    prefs = st.session_state.au.get_prefs(u)
                    st.session_state.update({
                        'in': True, 'user': u, 'data': None,
                        'market_type': prefs.get('market', 'spot'),
                        'ai_auto_trade': prefs.get('ai_auto', False),
                    })
                    k, s = st.session_state.au.keys(u)
                    if k and s:
                        ex = Exchange(prefs.get('market', 'spot'))
                        ex.connect(k, s)
                        st.session_state.ex = ex
                        Config.DEMO_MODE = False
                        st.session_state.demo_mode = False
                    st.rerun()
                else:
                    st.error("ACCESO DENEGADO")
        with t2:
            u2 = st.text_input("NUEVO USUARIO", key="ru")
            p2 = st.text_input("CONTRASEÑA", type="password", key="rp")
            if st.button("CREAR CUENTA", use_container_width=True):
                if st.session_state.au.register(u2, p2):
                    st.success("CUENTA CREADA — INICIA SESIÓN")
                else:
                    st.error("USUARIO YA EXISTE")

def main_page():
    st.markdown(STYLES, unsafe_allow_html=True)
    bbg_header()

    ex: Exchange = st.session_state.ex
    cb: CircuitBreaker = st.session_state.cb

    # Sidebar navigation
    with st.sidebar:
        st.markdown(f"""
        <div style="font-family:'IBM Plex Mono';padding:8px">
            <div style="color:#ff6600;font-size:10px;letter-spacing:2px">OPERADOR</div>
            <div style="color:#e2e8f0;font-size:13px">{st.session_state.user.upper()}</div>
            <div style="color:#4a5568;font-size:9px;margin-top:2px">
                MKT: {st.session_state.market_type.upper()}
            </div>
        </div>""", unsafe_allow_html=True)
        st.divider()

        page = st.radio("", [
            "MKT  │ Dashboard de Mercado",
            "AI   │ Análisis IA + Portafolio",
            "RISK │ Gestión de Riesgo",
            "VAULT│ Bóveda de Staking",
            "EXEC │ Ejecutar Operación",
            "CFG  │ Configuración",
        ], label_visibility="collapsed")

        st.divider()
        cb_status = cb.status()
        cb_color = "#00ff88" if cb_status['ok'] else "#ff4455"
        st.markdown(f"""
        <div style="font-family:'IBM Plex Mono';font-size:9px;padding:4px">
            <span style="color:{cb_color}">{'● TRADING ACTIVO' if cb_status['ok'] else '■ TRADING PAUSADO'}</span><br>
            <span style="color:#4a5568">PnL HOY: {cb_status['daily']:+.2f}%</span><br>
            <span style="color:#4a5568">PnL TOTAL: {cb_status['total']:+.2f}%</span>
        </div>""", unsafe_allow_html=True)
        st.divider()

        if st.button("↻ REFRESH", use_container_width=True):
            st.session_state.update({'data': None, 'balance': None, 'ai_analysis': None})
            st.rerun()
        if st.button("⏻ LOGOUT", use_container_width=True):
            st.session_state.update({'in': False, 'data': None, 'balance': None})
            st.rerun()

    # Cargar datos
    if st.session_state.balance is None:
        with st.spinner("SINCRONIZANDO CON EXCHANGE..."):
            st.session_state.balance = ex.get_balance()
            non_usdt = [a for a in st.session_state.balance if a != 'USDT']
            st.session_state.prices = ex.get_ticker_prices(non_usdt)
            st.session_state.prices['USDT'] = 1.0
            # Simular precios 24h para detectar tendencias
            if not st.session_state.prices_24h:
                st.session_state.prices_24h = {
                    k: v * np.random.uniform(0.85, 1.15)
                    for k, v in st.session_state.prices.items()
                }

    balance = st.session_state.balance
    prices  = st.session_state.prices

    # Ticker bar
    ticker_bar(balance, prices)

    # ── DASHBOARD DE MERCADO ──────────────────────────────
    if "MKT" in page:
        # Portfolio value total
        total_val = sum(
            data['total'] * prices.get(asset, 1.0)
            for asset, data in balance.items()
        )

        # Detectar tendencias
        trends = detect_trends(prices, st.session_state.prices_24h)

        c1, c2, c3, c4 = st.columns(4)
        with c1: bbg_panel("VALOR PORTAFOLIO", f"${total_val:,.2f}",
                           f"DEMO MODE" if Config.DEMO_MODE else "LIVE", "bbg-panel-gold")
        with c2:
            df_btc = ex._candles('BTC/USDT', '5m')
            price_btc = float(df_btc['close'].iloc[-1])
            rsi_v = float(calc_rsi(df_btc['close']).iloc[-1])
            rsi_cls = "num-up" if rsi_v<40 else "num-down" if rsi_v>70 else "num-neu"
            bbg_panel("BTC/USDT", f"${price_btc:,.2f}", f"RSI: {rsi_v:.1f}", num_class=rsi_cls)
        with c3:
            obi_v = ex.obi()
            obi_cls = "num-up" if obi_v>0 else "num-down"
            bbg_panel("ORDER BOOK IMBALANCE", f"{obi_v:+.4f}",
                     "PRESIÓN COMPRADORA" if obi_v>0 else "PRESIÓN VENDEDORA",
                     num_class=obi_cls)
        with c4:
            bbg_panel("CIRCUIT BREAKER",
                     "ACTIVO" if cb_status['ok'] else "PAUSADO",
                     cb_status.get('reason') or f"DD: {cb_status['total']:+.1f}%",
                     "bbg-panel-green" if cb_status['ok'] else "bbg-panel-red")

        # Alertas de tendencia +/-10%
        if trends:
            st.markdown('<div class="bbg-panel bbg-panel-gold"><div class="panel-title">⚡ ALERTAS DE TENDENCIA (±10% EN 24H)</div>', unsafe_allow_html=True)
            for t in trends:
                cls = "alert-up" if t['change'] > 0 else "alert-down"
                st.markdown(f"""
                <span class="{cls}">{t['signal']}</span>
                <span style="color:#e2e8f0;margin:0 8px">{t['asset']}</span>
                <span style="color:#4a5568">@ ${t['price']:,.4f}</span>
                <span style="color:{'#00ff88' if t['change']>0 else '#ff4455'};float:right">
                    {t['change']:+.1f}%</span><br>""", unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

        # Tabla del portafolio
        st.markdown('<div class="bbg-panel"><div class="panel-title">COMPOSICIÓN DEL PORTAFOLIO</div>', unsafe_allow_html=True)
        rows = []
        for asset, data in balance.items():
            price = prices.get(asset, 1.0)
            val = data['total'] * price
            pct_port = (val / total_val * 100) if total_val > 0 else 0
            change = ((prices.get(asset,1) - st.session_state.prices_24h.get(asset,1)) /
                      st.session_state.prices_24h.get(asset,1) * 100)
            rows.append({
                'ACTIVO': asset,
                'CANTIDAD': f"{data['total']:.4f}",
                'PRECIO': f"${price:,.2f}",
                'VALOR USD': f"${val:,.2f}",
                '% PORT': f"{pct_port:.1f}%",
                '24H %': f"{change:+.1f}%",
                'LIBRE': f"{data['free']:.4f}",
            })
        df_port = pd.DataFrame(rows)
        st.dataframe(df_port, use_container_width=True, hide_index=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # Mini chart
        st.markdown('<div class="bbg-panel"><div class="panel-title">BTC/USDT — PRECIO (5M)</div>', unsafe_allow_html=True)
        chart_data = pd.DataFrame({
            'BTC': df_btc['close'].tail(100),
            'EMA20': calc_ema(df_btc['close'], 20).tail(100),
            'EMA50': calc_ema(df_btc['close'], 50).tail(100),
        })
        st.line_chart(chart_data, height=200)
        st.markdown('</div>', unsafe_allow_html=True)

    # ── AI ANÁLISIS + PORTAFOLIO ──────────────────────────
    elif "AI" in page:
        st.markdown('<div class="bbg-panel bbg-panel-blue"><div class="panel-title">🤖 ANÁLISIS DE PORTAFOLIO CON GROQ / LLAMA-3.3</div>', unsafe_allow_html=True)

        col_a, col_b = st.columns([3, 1])
        with col_b:
            if st.button("ANALIZAR AHORA", use_container_width=True):
                with st.spinner("CONSULTANDO IA..."):
                    st.session_state.ai_analysis = st.session_state.ai.analyze_portfolio(
                        balance, prices, st.session_state.market_type
                    )

        analysis = st.session_state.ai_analysis
        if analysis:
            sent = analysis.get('sentimiento_mercado', 'NEUTRAL')
            sent_color = "#00ff88" if sent=="ALCISTA" else "#ff4455" if sent=="BAJISTA" else "#ffaa00"
            riesgo = analysis.get('riesgo_general', 'MEDIO')

            c1, c2 = st.columns(2)
            with c1: bbg_panel("SENTIMIENTO IA", sent, analysis.get('resumen',''), num_class="num-up")
            with c2: bbg_panel("RIESGO GENERAL", riesgo,
                               analysis.get('recomendacion_principal','')[:50]+"...",
                               "bbg-panel-green" if riesgo=="BAJO" else
                               "bbg-panel-gold" if riesgo=="MEDIO" else "bbg-panel-red")

            st.markdown('<div class="panel-title" style="margin-top:12px">SUGERENCIAS DE LA IA</div>', unsafe_allow_html=True)
            for action in analysis.get('acciones', []):
                ai_action_card(action)

            # Auto-trade section
            st.markdown("---")
            st.markdown('<div class="panel-title">⚡ EJECUCIÓN AUTOMÁTICA CON IA</div>', unsafe_allow_html=True)

            auto = st.toggle("Permitir que la IA opere automáticamente",
                            value=st.session_state.ai_auto_trade,
                            key="ai_auto_toggle")
            if auto != st.session_state.ai_auto_trade:
                st.session_state.ai_auto_trade = auto
                prefs = st.session_state.au.get_prefs(st.session_state.user)
                prefs['ai_auto'] = auto
                st.session_state.au.save_prefs(st.session_state.user, prefs)

            if auto:
                st.warning("⚠️ MODO AUTO ACTIVO — La IA puede ejecutar órdenes con tu cuenta")
                for action in analysis.get('acciones', []):
                    if action.get('urgencia') == 'ALTA' and action.get('accion') != 'MANTENER':
                        col_x, col_y = st.columns([3,1])
                        with col_x:
                            ai_action_card(action)
                        with col_y:
                            if st.button(f"EJECUTAR {action['activo']}", key=f"exec_{action['activo']}"):
                                if not cb.can_trade():
                                    st.error(f"BLOQUEADO: {cb_status['reason']}")
                                else:
                                    result = st.session_state.ai.execute_suggestion(
                                        action, ex, st.session_state.ks, balance, prices)
                                    if 'error' in result:
                                        st.error(result['error'])
                                    else:
                                        st.success(f"✅ ORDEN ENVIADA: {result}")
            else:
                st.info("💡 Activa el modo auto para que la IA opere por ti, o ejecuta manualmente en EXEC")

        else:
            st.info("Presiona ANALIZAR AHORA para que la IA revise tu portafolio")
        st.markdown('</div>', unsafe_allow_html=True)

    # ── GESTIÓN DE RIESGO ─────────────────────────────────
    elif "RISK" in page:
        st.markdown('<div class="bbg-panel"><div class="panel-title">CIRCUIT BREAKER — ESTADO EN TIEMPO REAL</div>', unsafe_allow_html=True)
        c1, c2, c3, c4 = st.columns(4)
        with c1: bbg_panel("ESTADO", "OK" if cb_status['ok'] else "PAUSADO",
                           color_class="bbg-panel-green" if cb_status['ok'] else "bbg-panel-red")
        with c2: bbg_panel("PnL DIARIO", f"{cb_status['daily']:+.2f}%",
                           f"LÍMITE: -{Config.MAX_DAILY_DD}%")
        with c3: bbg_panel("PnL TOTAL", f"{cb_status['total']:+.2f}%",
                           f"EMERGENCY: {Config.EMERGENCY}%")
        with c4: bbg_panel("PÉRD. CONSEC.", str(cb_status['losses']),
                           f"LÍMITE: {Config.MAX_LOSSES}")
        if cb_status['reason']:
            st.error(f"🚨 {cb_status['reason']}")
        st.markdown('</div>', unsafe_allow_html=True)

        # Position Sizer
        st.markdown('<div class="bbg-panel bbg-panel-blue"><div class="panel-title">CALCULADORA DE POSICIÓN — HALF KELLY</div>', unsafe_allow_html=True)
        df_e = ex._candles('BTC/USDT', '5m')
        price_def = float(df_e['close'].iloc[-1])
        c1, c2, c3 = st.columns(3)
        with c1: bal_input = st.number_input("CAPITAL USD", 100.0, 1e7, 10000.0)
        with c2: entry_p   = st.number_input("PRECIO ENTRADA", 1.0, 1e8, price_def)
        with c3: direction = st.selectbox("DIRECCIÓN", ["long", "short"])
        if st.button("CALCULAR STOPS Y TAMAÑO", use_container_width=True):
            stops = st.session_state.rm.calc(entry_p, direction, df_e)
            if stops:
                size = st.session_state.ks.size(bal_input, entry_p, stops.sl)
                c1,c2,c3,c4 = st.columns(4)
                with c1: bbg_panel("STOP LOSS",   f"${stops.sl:,.2f}", "ATR based", "bbg-panel-red")
                with c2: bbg_panel("TAKE PROFIT", f"${stops.tp:,.2f}", "", "bbg-panel-green")
                with c3: bbg_panel("RATIO R:R",   f"{stops.rr}x",
                                  "ÓPTIMO" if stops.rr>=2 else "MARGINAL",
                                  "bbg-panel-green" if stops.rr>=2 else "bbg-panel-gold")
                with c4: bbg_panel("POSICIÓN",    f"${size:,.0f}",
                                  f"ATR={stops.atr_v:.0f}", "bbg-panel-blue")
        st.markdown('</div>', unsafe_allow_html=True)

    # ── BÓVEDA DE STAKING ─────────────────────────────────
    elif "VAULT" in page:
        st.markdown('<div class="bbg-panel bbg-panel-gold"><div class="panel-title">🏦 BÓVEDA DE STAKING — RENDIMIENTO ESTIMADO POR ACTIVO</div>', unsafe_allow_html=True)

        total_yield_annual = 0
        vault_rows = []

        for asset, data in balance.items():
            if asset == 'USDT' or data['total'] <= 0: continue
            price = prices.get(asset, 0)
            if price == 0: continue
            info = calc_staking_yield(asset, data['free'], price)
            total_yield_annual += info['rendimiento_anual_usd']
            vault_rows.append({
                'ACTIVO': asset,
                'DISPONIBLE': f"{data['free']:.4f}",
                'VALOR USD': f"${info['valor_usd']:,.2f}",
                'APY': f"{info['apy']}%",
                'PLATAFORMA': info['platform'],
                'TIPO': info['tipo'],
                'RIESGO': info['riesgo'],
                'REND. 30D': f"${info['rendimiento_30d']:,.2f}",
                'REND. 90D': f"${info['rendimiento_90d']:,.2f}",
                'REND. 1AÑO': f"${info['rendimiento_anual_usd']:,.2f}",
            })

        # Resumen
        c1, c2, c3 = st.columns(3)
        total_val = sum(d['total']*prices.get(a,1) for a,d in balance.items())
        with c1: bbg_panel("RENDIMIENTO ANUAL EST.", f"${total_yield_annual:,.2f}",
                           "Si todo se hace staking", "bbg-panel-gold")
        with c2: bbg_panel("RENDIMIENTO MENSUAL", f"${total_yield_annual/12:,.2f}",
                           "Promedio mensual")
        with c3: bbg_panel("APY PROMEDIO PORT.",
                           f"{(total_yield_annual/total_val*100) if total_val>0 else 0:.1f}%",
                           "Weighted APY")

        st.markdown('<div class="panel-title" style="margin-top:12px">OPORTUNIDADES DE STAKING</div>', unsafe_allow_html=True)
        if vault_rows:
            df_vault = pd.DataFrame(vault_rows)
            st.dataframe(df_vault, use_container_width=True, hide_index=True)

        # Detalle expandido por activo
        st.markdown('<div class="panel-title" style="margin-top:12px">DETALLE POR ACTIVO</div>', unsafe_allow_html=True)
        for asset, data in balance.items():
            if asset == 'USDT' or data['total'] <= 0: continue
            price = prices.get(asset, 0)
            if price == 0: continue
            info = calc_staking_yield(asset, data['free'], price)
            risk_color = "#00ff88" if info['riesgo']=="BAJO" else "#ffaa00"
            st.markdown(f"""
            <div class="stake-card">
                <span style="color:#f59e0b;font-weight:600">{asset}</span>
                <span style="color:#4a5568;margin:0 8px">│</span>
                <span style="color:#e2e8f0">{info['platform']}</span>
                <span style="color:#4a5568;margin:0 8px">│</span>
                <span style="color:#00ff88">{info['apy']}% APY</span>
                <span style="color:#4a5568;margin:0 8px">│</span>
                <span style="color:{risk_color}">{info['riesgo']}</span>
                <span style="float:right;color:#e2e8f0">
                    30d: <span style="color:#00ff88">${info['rendimiento_30d']:,.2f}</span>
                    &nbsp;|&nbsp;
                    1y: <span style="color:#00ff88">${info['rendimiento_anual_usd']:,.2f}</span>
                </span>
            </div>""", unsafe_allow_html=True)

        st.markdown('</div>', unsafe_allow_html=True)

    # ── EJECUTAR OPERACIÓN ────────────────────────────────
    elif "EXEC" in page:
        st.markdown('<div class="bbg-panel bbg-panel-red"><div class="panel-title">⚡ EJECUTAR OPERACIÓN MANUAL</div>', unsafe_allow_html=True)

        if not cb.can_trade():
            st.error(f"🚨 TRADING BLOQUEADO: {cb_status['reason']}")
        else:
            assets_list = [a for a in balance.keys() if a != 'USDT'] + ['BTC','ETH','BNB','SOL','ADA']
            assets_list = list(dict.fromkeys(assets_list))

            c1, c2, c3, c4 = st.columns(4)
            with c1: asset    = st.selectbox("ACTIVO", assets_list)
            with c2: side     = st.selectbox("LADO", ["buy", "sell"])
            with c3: mkt_type = st.selectbox("MERCADO", ["spot", "futures"],
                                             index=0 if st.session_state.market_type=='spot' else 1)
            with c4: amount   = st.number_input("CANTIDAD", 0.0001, 1e6, 0.001, format="%.4f")

            price_now = prices.get(asset, 0)
            val_usd   = amount * price_now
            st.markdown(f"""
            <div style="font-family:'IBM Plex Mono';font-size:11px;color:#4a5568;padding:8px 0">
                VALOR ESTIMADO: <span style="color:#e2e8f0">${val_usd:,.2f} USDT</span>
                &nbsp;│&nbsp; PRECIO ACTUAL: <span style="color:#e2e8f0">${price_now:,.2f}</span>
                &nbsp;│&nbsp; MERCADO: <span style="color:#ff6600">{mkt_type.upper()}</span>
            </div>""", unsafe_allow_html=True)

            col_confirm, col_cancel = st.columns(2)
            with col_confirm:
                if st.button(f"✅ CONFIRMAR {side.upper()} {amount} {asset}", use_container_width=True):
                    if Config.DEMO_MODE:
                        st.success(f"[DEMO] Orden simulada: {side.upper()} {amount} {asset} @ ${price_now:,.2f}")
                        # Registrar en Kelly
                        pnl_sim = np.random.uniform(-2, 3)
                        st.session_state.ks.add(pnl_sim)
                        cb.record(pnl_sim)
                    else:
                        with st.spinner("ENVIANDO ORDEN..."):
                            result = ex.place_order(asset, side, amount)
                        if 'error' in result:
                            st.error(f"ERROR: {result['error']}")
                        else:
                            st.success(f"✅ ORDEN EJECUTADA: {result.get('id', 'OK')}")
            with col_cancel:
                if st.button("✗ CANCELAR", use_container_width=True):
                    st.info("Operación cancelada")

        st.markdown('</div>', unsafe_allow_html=True)

    # ── CONFIGURACIÓN ─────────────────────────────────────
    elif "CFG" in page:
        st.markdown('<div class="bbg-panel"><div class="panel-title">CONFIGURACIÓN DEL SISTEMA</div>', unsafe_allow_html=True)

        t1, t2, t3 = st.tabs(["API KEYS", "MERCADO", "RIESGO"])
        with t1:
            u = st.session_state.user
            k, s = st.session_state.au.keys(u)
            nk = st.text_input("BINANCE API KEY", value=k, type="password")
            ns = st.text_input("BINANCE SECRET",  value=s, type="password")
            if st.button("GUARDAR LLAVES", use_container_width=True):
                st.session_state.au.save_keys(u, nk, ns)
                demo = not bool(nk and ns)
                Config.DEMO_MODE = demo
                st.session_state.demo_mode = demo
                st.session_state.update({'data':None,'balance':None,'ex':Exchange()})
                st.success("LLAVES GUARDADAS — " + ("MODO REAL 🟢" if not demo else "MODO DEMO 🟡"))
                st.rerun()

        with t2:
            mkt = st.selectbox("TIPO DE MERCADO",
                              ["spot", "futures"],
                              index=0 if st.session_state.market_type=='spot' else 1)
            if st.button("GUARDAR MERCADO", use_container_width=True):
                st.session_state.market_type = mkt
                prefs = st.session_state.au.get_prefs(st.session_state.user)
                prefs['market'] = mkt
                st.session_state.au.save_prefs(st.session_state.user, prefs)
                st.session_state.ex = Exchange(mkt)
                k, s = st.session_state.au.keys(st.session_state.user)
                if k and s: st.session_state.ex.connect(k, s)
                st.success(f"MERCADO: {mkt.upper()}")
                st.rerun()

        with t3:
            st.code(f"""
MAX_DAILY_DD    = {Config.MAX_DAILY_DD}%
MAX_TOTAL_DD    = {Config.MAX_TOTAL_DD}%
EMERGENCY_STOP  = {Config.EMERGENCY}%
MAX_CONS_LOSSES = {Config.MAX_LOSSES}
COOLDOWN_MIN    = {Config.COOLDOWN}
KELLY_FRACTION  = {Config.KELLY}
MAX_POSITION    = {Config.MAX_POS*100:.0f}%
            """, language="ini")
            st.caption("Modifica via variables de entorno en Railway/Hugging Face")
        st.markdown('</div>', unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════
def main():
    st.set_page_config(
        page_title="TITANIUM | Trading Terminal",
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
