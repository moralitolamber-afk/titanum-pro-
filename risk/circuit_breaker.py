"""
Circuit Breaker — Protección de capital.
Detiene el trading automáticamente si se superan límites de riesgo:
- Drawdown diario excesivo
- Drawdown total excesivo
- Racha de pérdidas consecutivas
- Parada de emergencia permanente
"""
from datetime import datetime, timedelta
from typing import Optional

import config


class CircuitBreaker:
    def __init__(self):
        self.daily_pnl = 0.0
        self.total_pnl = 0.0
        self.consecutive_losses = 0
        self.cooldown_until: Optional[datetime] = None

        self.trading_paused = False
        self.pause_reason: Optional[str] = None
        self.daily_reset_time = datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        self.total_trades = 0
        self.total_wins = 0

    def reset_daily(self):
        """Reset automático al cambiar de día."""
        now = datetime.now()
        if now > self.daily_reset_time + timedelta(days=1):
            self.daily_pnl = 0.0
            self.daily_reset_time = now.replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            # No resetear consecutive_losses aquí, solo al ganar un trade

    def record_trade(self, pnl_pct: float):
        """Registra el resultado de un trade cerrado."""
        self.reset_daily()
        self.daily_pnl += pnl_pct
        self.total_pnl += pnl_pct
        self.total_trades += 1

        if pnl_pct < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
            self.total_wins += 1

        self._check_breakers()

    def _check_breakers(self):
        """Evaluar si algún umbral crítico fue cruzado."""
        # 1. Drawdown diario
        if self.daily_pnl <= -config.MAX_DAILY_DRAWDOWN_PCT:
            self._pause(f"Drawdown diario: {self.daily_pnl:.1f}%")
            return

        # 2. Drawdown total
        if self.total_pnl <= -config.MAX_TOTAL_DRAWDOWN_PCT:
            self._pause(f"Drawdown total: {self.total_pnl:.1f}%")
            return

        # 3. Racha de pérdidas
        if self.consecutive_losses >= config.MAX_CONSECUTIVE_LOSSES:
            self.cooldown_until = datetime.now() + timedelta(
                minutes=config.COOLDOWN_AFTER_LOSSES
            )
            self._pause(
                f"{self.consecutive_losses} pérdidas consecutivas → "
                f"cooldown {config.COOLDOWN_AFTER_LOSSES}min"
            )
            return

        # 4. Emergencia permanente
        if self.total_pnl <= config.EMERGENCY_STOP_PNL_PCT:
            self._pause(f"EMERGENCIA: {self.total_pnl:.1f}%", permanent=True)
            return

    def _pause(self, reason: str, permanent: bool = False):
        """Pausar el trading con razón."""
        self.trading_paused = True
        self.pause_reason = reason
        if permanent:
            self.cooldown_until = None  # Sin auto-recuperación

    def can_trade(self) -> bool:
        """Retorna True si el bot puede operar."""
        self.reset_daily()

        # Si hay cooldown activo, verificar si ya expiró
        if self.cooldown_until:
            if datetime.now() >= self.cooldown_until:
                self.trading_paused = False
                self.pause_reason = None
                self.cooldown_until = None
                return True

        return not self.trading_paused

    def get_status(self) -> dict:
        """Retorna estado actual del circuit breaker para el dashboard."""
        win_rate = (self.total_wins / self.total_trades * 100) if self.total_trades > 0 else 0
        return {
            'can_trade': self.can_trade(),
            'daily_pnl_pct': round(self.daily_pnl, 2),
            'total_pnl_pct': round(self.total_pnl, 2),
            'consecutive_losses': self.consecutive_losses,
            'total_trades': self.total_trades,
            'win_rate': round(win_rate, 1),
            'pause_reason': self.pause_reason,
            'cooldown_until': self.cooldown_until.isoformat() if self.cooldown_until else None,
        }
