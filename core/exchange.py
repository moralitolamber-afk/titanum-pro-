"""
Gestión de datos optimizada para Vercel Serverless (stateless, sin ThreadPoolExecutor persistente).
"""
import time
import ccxt
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
import config

class ExchangeManager:
    def __init__(self):
        self.exchange = None
        # ⚠️ Cache en memoria — solo vive durante el request en Vercel
        self._cache = {}

    def connect(self, api_key=None, api_secret=None):
        """Conexión liviana, reutiliza instancia si ya existe."""
        if config.DEMO_MODE:
            return
        if self.exchange:  # Evita reconectar innecesariamente
            return

        cfg = {
            'enableRateLimit': True,
            'options': {'defaultType': 'future' if not config.USE_SPOT else 'spot'},
        }
        if api_key:
            cfg['apiKey'] = api_key
            cfg['secret'] = api_secret

        self.exchange = (
            ccxt.binance(cfg) if config.USE_SPOT
            else ccxt.binanceusdm(cfg)
        )

    def fetch_candles(self, tf: str) -> pd.DataFrame:
        """Fetch con caché en memoria y manejo explícito de errores."""
        if not self.exchange:
            # En modo demo, podemos usar los métodos de demo_candles si existieran.
            # Pero el código proporcionado no los incluye. Asumimos DEMO_MODE manejado arriba.
            return pd.DataFrame()
            
        try:
            ohlcv = self.exchange.fetch_ohlcv(
                config.SYMBOL, tf, limit=config.CANDLE_LIMIT
            )
            if not ohlcv:
                return self._cache.get(tf, pd.DataFrame())

            df = pd.DataFrame(
                ohlcv,
                columns=['time', 'open', 'high', 'low', 'close', 'volume']
            )
            df['time'] = pd.to_datetime(df['time'], unit='ms')
            df = df.set_index('time')  # Índice temporal para operaciones más rápidas
            self._cache[tf] = df
            return df

        except ccxt.NetworkError as e:
            print(f"[ExchangeManager] NetworkError en {tf}: {e}")
            return self._cache.get(tf, pd.DataFrame())
        except ccxt.ExchangeError as e:
            print(f"[ExchangeManager] ExchangeError en {tf}: {e}")
            return self._cache.get(tf, pd.DataFrame())
        except Exception as e:
            print(f"[ExchangeManager] Error inesperado en {tf}: {e}")
            return self._cache.get(tf, pd.DataFrame())

    def fetch_all_timeframes(self) -> dict:
        """
        Fetch paralelo — funciona en Vercel SOLO si el timeout no se excede.
        Vercel tiene límite de 10s (plan free) o 60s (pro).
        """
        timeframes = [config.TF_ENTRY, config.TF_CONFIRM, config.TF_TREND]

        with ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(self.fetch_candles, timeframes))

        return {
            tf: df for tf, df in zip(timeframes, results)
            if not df.empty  # Solo retorna timeframes con datos
        }

    def get_cached(self, tf: str) -> pd.DataFrame:
        """Acceso directo al caché sin fetch (útil para tests)."""
        return self._cache.get(tf, pd.DataFrame())
