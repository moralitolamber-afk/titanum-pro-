# portfolio/analyzer.py
import ccxt
import pandas as pd
from typing import Dict, List, Optional

class PortfolioAnalyzer:
    """
    Obtiene balances reales del usuario desde Binance y calcula
    métricas de exposición, concentración y correlación.
    """

    def __init__(self, api_key: str, api_secret: str, sandbox: bool = True):
        self.exchange = ccxt.binance({
            'apiKey': api_key,
            'secret': api_secret,
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'},
        })
        if sandbox:
            self.exchange.set_sandbox_mode(True)

    def get_balances(self, min_usd: float = 10.0) -> pd.DataFrame:
        """Retorna DataFrame con activos que valen más que min_usd."""
        try:
            balance = self.exchange.fetch_balance()
            tickers = self.exchange.fetch_tickers()
            
            rows = []
            for asset, data in balance['total'].items():
                if data <= 0 or asset == 'USDT':
                    continue
                
                pair = f"{asset}/USDT"
                price = tickers.get(pair, {}).get('last', 0)
                usd_val = data * price
                
                if usd_val >= min_usd:
                    rows.append({
                        'asset': asset,
                        'balance': data,
                        'price_usdt': price,
                        'usd_value': usd_val,
                        'pct_of_portfolio': 0.0  # Se calcula después
                    })
            
            df = pd.DataFrame(rows)
            if not df.empty:
                total = df['usd_value'].sum()
                df['pct_of_portfolio'] = (df['usd_value'] / total * 100).round(2)
                df = df.sort_values('usd_value', ascending=False)
            return df
        except Exception as e:
            print(f"Error fetching balances: {e}")
            return pd.DataFrame()

    def get_24h_changes(self, assets: List[str]) -> Dict[str, float]:
        """Obtiene cambios porcentuales 24h para una lista de activos."""
        changes = {}
        for asset in assets:
            try:
                ticker = self.exchange.fetch_ticker(f"{asset}/USDT")
                changes[asset] = ticker.get('percentage', 0)
            except Exception:
                changes[asset] = 0.0
        return changes

    def get_portfolio_metrics(self, df: pd.DataFrame) -> Dict:
        """Calcula métricas de riesgo del portafolio."""
        if df.empty:
            return {"error": "Portafolio vacío", "total_usd": 0, "num_assets": 0}
        
        total = df['usd_value'].sum()
        concentration = df['pct_of_portfolio'].iloc[0]  # Mayor posición
        
        return {
            "total_usd": round(total, 2),
            "num_assets": len(df),
            "concentration_pct": round(concentration, 2),
            "diversification_score": max(0, 100 - concentration),
            "largest_position": df.iloc[0]['asset'],
            "needs_rebalance": concentration > 40
        }
