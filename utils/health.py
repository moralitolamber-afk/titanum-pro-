"""
Health Checker — Monitoreo de salud del sistema.
Verifica que todos los componentes estén funcionando correctamente.
"""
import time
from datetime import datetime


class HealthChecker:
    def __init__(self):
        self.start_time = time.time()
        self.last_heartbeat = time.time()
        self.errors = []
        self.max_errors = 50

    def heartbeat(self):
        """Registrar que el sistema sigue vivo."""
        self.last_heartbeat = time.time()

    def log_error(self, component: str, error: str):
        """Registrar un error para tracking."""
        self.errors.append({
            'time': datetime.now().isoformat(),
            'component': component,
            'error': str(error)[:100],
        })
        if len(self.errors) > self.max_errors:
            self.errors = self.errors[-self.max_errors:]

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self.start_time

    @property
    def uptime_formatted(self) -> str:
        """Retorna uptime en formato legible."""
        secs = int(self.uptime_seconds)
        hours = secs // 3600
        mins = (secs % 3600) // 60
        secs = secs % 60
        return f"{hours:02d}h {mins:02d}m {secs:02d}s"

    def get_status(self) -> dict:
        """Status general para el dashboard."""
        recent_errors = len([
            e for e in self.errors
            if time.time() - self.start_time < 300  # Últimos 5 min
        ])
        return {
            'uptime': self.uptime_formatted,
            'uptime_seconds': round(self.uptime_seconds),
            'last_heartbeat': round(time.time() - self.last_heartbeat, 1),
            'total_errors': len(self.errors),
            'recent_errors': recent_errors,
            'healthy': recent_errors < 10,
        }
