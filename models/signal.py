"""Modelo de datos para señales de trading."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional


@dataclass
class Signal:
    signal_id: str              # ID único para trailing stop
    direction: str              # 'LONG' o 'SHORT'
    score: int                  # 0-100 confluencia
    timestamp: datetime
    price: float
    entry: float
    stop_loss: float
    take_profit: float
    atr: float
    risk_reward: float
    breakdown: Dict[str, tuple]   # {factor: (score, max_score)}
    status: str = 'ACTIVE'        # ACTIVE, EXPIRED, HIT_TP, HIT_SL
    trailing_phase: str = 'INITIAL'  # INITIAL, BREAKEVEN, TIGHT
    pnl_pct: float = 0.0         # PnL % (calculado al cerrar)

    @property
    def is_strong(self):
        return self.score >= 80

    @property
    def emoji(self):
        return '🟢' if self.direction == 'LONG' else '🔴'

    @property
    def sl_distance(self):
        return abs(self.entry - self.stop_loss)

    @property
    def tp_distance(self):
        return abs(self.entry - self.take_profit)

    @property
    def age_seconds(self):
        return (datetime.now(timezone.utc) - self.timestamp).total_seconds()

    def calculate_pnl(self, exit_price: float) -> float:
        """Calcula PnL porcentual al cerrar."""
        if self.direction == 'LONG':
            self.pnl_pct = ((exit_price - self.entry) / self.entry) * 100
        else:
            self.pnl_pct = ((self.entry - exit_price) / self.entry) * 100
        return self.pnl_pct
