"""
Gestión de conexión al exchange y fetching de datos.
Soporta Binance Spot/Futures y modo demo para pruebas.
FASE 3: Retry con backoff exponencial para resiliencia.
"""
import time
import random
import math
import ccxt
import pandas as pd
import numpy as np
from collections import deque
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

import config


MAX_RETRIES = 3
BASE_DELAY = 1.0  # segundos


class ExchangeManager:
    def __init__(self):
        self.exchange = None
        self.obi_history = deque(maxlen=config.OBI_SMOOTHING)
        self._cache = {}
        self._last_fetch = {}
        self._consecutive_errors = 0
        self._demo_price = 84500.0
        self._demo_tick = 0
        self._executor = ThreadPoolExecutor(max_workers=5)

    def connect(self, api_key: str = None, api_secret: str = None):
        if config.DEMO_MODE:
            return

        exchange_config = {'enableRateLimit': True}
        if api_key and api_secret:
            exchange_config['apiKey'] = api_key
            exchange_config['secret'] = api_secret

        if config.USE_SPOT:
            self.exchange = ccxt.binance(exchange_config)
        else:
            exchange_config['options'] = {'defaultType': 'future'}
            self.exchange = ccxt.binanceusdm(exchange_config)

    def fetch_obi(self):
        if config.DEMO_MODE:
            return self._demo_obi()

        for attempt in range(MAX_RETRIES):
            try:
                ob = self.exchange.fetch_order_book(
                    config.SYMBOL, limit=config.ORDERBOOK_DEPTH
                )
                bid_vol = sum(b[1] for b in ob['bids'])
                ask_vol = sum(a[1] for a in ob['asks'])
                total = bid_vol + ask_vol
                raw = (bid_vol - ask_vol) / total if total > 0 else 0
                self.obi_history.append(raw)

                best_bid = ob['bids'][0][0] if ob['bids'] else 0
                best_ask = ob['asks'][0][0] if ob['asks'] else 0

                self._consecutive_errors = 0
                return {
                    'obi':      float(np.mean(self.obi_history)),
                    'raw_obi':  raw,
                    'bid_vol':  bid_vol,
                    'ask_vol':  ask_vol,
                    'spread':   best_ask - best_bid,
                    'best_bid': best_bid,
                    'best_ask': best_ask,
                }
            except Exception as e:
                self._consecutive_errors += 1
                if attempt < MAX_RETRIES - 1:
                    delay = BASE_DELAY * (2 ** attempt) + random.uniform(0, 0.5)
                    time.sleep(delay)
                else:
                    return self._fallback_obi()

    def fetch_candles(self, timeframe, force=False):
        if config.DEMO_MODE:
            return self._demo_candles(timeframe)

        now = time.time()
        ttl = {'5m': 3, '15m': 30, '1h': 60}.get(timeframe, 10)
        last = self._last_fetch.get(timeframe, 0)

        if not force and (now - last) < ttl and timeframe in self._cache:
            return self._cache[timeframe].copy()

        try:
            ohlcv = self.exchange.fetch_ohlcv(
                config.SYMBOL, timeframe, limit=config.CANDLE_LIMIT
            )
            df = pd.DataFrame(
                ohlcv, columns=['time', 'open', 'high', 'low', 'close', 'volume']
            )
            df['time'] = pd.to_datetime(df['time'], unit='ms')
            
            self._cache[timeframe] = df
            self._last_fetch[timeframe] = now
            return df.copy()
        except Exception as e:
            self._consecutive_errors += 1
            if timeframe in self._cache:
                return self._cache[timeframe].copy()
            else:
                # Return empty generic dataframe to avoid downstream crashes
                return pd.DataFrame(columns=['time', 'open', 'high', 'low', 'close', 'volume'])

    def fetch_all_timeframes(self):
        timeframes = [config.TF_ENTRY, config.TF_CONFIRM, config.TF_TREND]
        
        # Parallel fetch to boost startup and refresh speed
        with ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(self.fetch_candles, timeframes))
            
        return dict(zip(timeframes, results))

    def close(self):
        # ccxt síncrono no requiere close explícito forzoso, pero podemos limpiar
        self.exchange = None

    def _fallback_obi(self):
        """Datos fallback cuando el exchange no responde."""
        smooth = float(np.mean(self.obi_history)) if self.obi_history else 0
        return {
            'obi': smooth, 'raw_obi': 0,
            'bid_vol': 0, 'ask_vol': 0,
            'spread': 0, 'best_bid': 0, 'best_ask': 0,
        }

    @property
    def health_status(self) -> dict:
        """Retorna estado de salud de la conexión."""
        return {
            'connected': self.exchange is not None or config.DEMO_MODE,
            'consecutive_errors': self._consecutive_errors,
            'cache_entries': len(self._cache),
            'demo_mode': config.DEMO_MODE,
        }

    # ── DEMO MODE ─────────────────────────────────────────

    def _demo_obi(self):
        self._demo_tick += 1
        # Simular OBI oscilante con tendencia
        base = 0.15 * math.sin(self._demo_tick * 0.05)
        noise = random.uniform(-0.1, 0.1)
        raw = max(-0.6, min(0.6, base + noise))
        self.obi_history.append(raw)
        smooth = float(np.mean(self.obi_history))
        price = self._demo_price

        return {
            'obi': smooth, 'raw_obi': raw,
            'bid_vol': 150 + raw * 50, 'ask_vol': 150 - raw * 50,
            'spread': random.uniform(0.1, 0.5),
            'best_bid': price - 0.1, 'best_ask': price + 0.1,
        }

    def _demo_candles(self, timeframe):
        n = config.CANDLE_LIMIT
        # Precio con tendencia + ruido
        self._demo_price += random.uniform(-30, 35)
        base = self._demo_price

        closes = []
        p = base - n * 5
        for i in range(n):
            p += random.uniform(-40, 42)
            p = max(p, 60000)
            closes.append(p)

        self._demo_price = closes[-1]

        data = []
        for i, c in enumerate(closes):
            h = c + random.uniform(10, 80)
            l = c - random.uniform(10, 80)
            o = c + random.uniform(-30, 30)
            v = random.uniform(100, 500)
            t = datetime.now(timezone.utc).timestamp() * 1000 - (n - i) * 300000
            data.append([t, o, h, l, c, v])

        df = pd.DataFrame(data, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
        df['time'] = pd.to_datetime(df['time'], unit='ms')
        return df
