"""
Position Sizer — Kelly Criterion (Half-Kelly).
Calcula dinámicamente cuánto arriesgar por trade basado en el rendimiento histórico.
Más ganás → más arriesgás (controladamente). Mala racha → reduce exposición.
"""
import numpy as np
from dataclasses import dataclass
from typing import List

import config


@dataclass
class TradeRecord:
    pnl_pct: float
    won: bool


class KellyPositionSizer:
    def __init__(self):
        self.trade_history: List[TradeRecord] = []

    def add_trade(self, pnl_pct: float):
        """Registra un trade cerrado."""
        self.trade_history.append(TradeRecord(
            pnl_pct=pnl_pct,
            won=pnl_pct > 0
        ))
        # Mantener solo lookback * 2 para eficiencia
        max_keep = config.KELLY_LOOKBACK * 2
        if len(self.trade_history) > max_keep:
            self.trade_history = self.trade_history[-config.KELLY_LOOKBACK:]

    def calculate_kelly(self) -> float:
        """Calcula el factor de Kelly basado en historial reciente."""
        if len(self.trade_history) < 20:
            return config.MIN_POSITION_PCT  # Conservador sin datos

        recent = self.trade_history[-config.KELLY_LOOKBACK:]
        wins = sum(1 for t in recent if t.won)
        win_rate = wins / len(recent)

        winning_trades = [t.pnl_pct for t in recent if t.won]
        losing_trades = [abs(t.pnl_pct) for t in recent if not t.won]

        if not winning_trades or not losing_trades:
            return config.MIN_POSITION_PCT

        avg_win = float(np.mean(winning_trades))
        avg_loss = float(np.mean(losing_trades))

        if avg_loss == 0:
            return config.MIN_POSITION_PCT

        # Fórmula Kelly: f* = (bp - q) / b
        b = avg_win / avg_loss   # Ratio de ganancias/pérdidas promedio
        p = win_rate             # Probabilidad de ganar
        q = 1 - p                # Probabilidad de perder

        kelly = (b * p - q) / b

        # Half-Kelly (o fracción configurada)
        position_size = kelly * config.KELLY_FRACTION

        # Clampear entre min y max
        position_size = float(np.clip(
            position_size, config.MIN_POSITION_PCT, config.MAX_POSITION_PCT
        ))

        return position_size

    def calculate_position(self, account_balance: float,
                           entry_price: float,
                           stop_loss_price: float) -> dict:
        """
        Calcula el tamaño de posición óptimo.
        Retorna dict con position_size_usd, position_size_coin, kelly_used_pct.
        """
        kelly_pct = self.calculate_kelly()
        risk_amount = account_balance * kelly_pct
        risk_per_unit = abs(entry_price - stop_loss_price)

        if risk_per_unit == 0:
            return {
                'position_size_usd': 0,
                'position_size_coin': 0,
                'kelly_used_pct': round(kelly_pct * 100, 2),
                'error': 'SL = Entry'
            }

        position_size_usd = risk_amount / (risk_per_unit / entry_price)
        position_size_coin = position_size_usd / entry_price

        return {
            'position_size_usd': round(position_size_usd, 2),
            'position_size_coin': round(position_size_coin, 6),
            'kelly_used_pct': round(kelly_pct * 100, 2),
            'risk_amount_usd': round(risk_amount, 2),
        }

    def get_status(self) -> dict:
        """Para mostrar en el dashboard."""
        kelly = self.calculate_kelly()
        total = len(self.trade_history)
        wins = sum(1 for t in self.trade_history if t.won)
        return {
            'kelly_pct': round(kelly * 100, 2),
            'total_trades': total,
            'win_rate': round(wins / total * 100, 1) if total > 0 else 0,
        }
