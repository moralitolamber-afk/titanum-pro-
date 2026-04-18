"""
ATR Trailing Stop Dinámico.
Reemplaza el SL fijo: a medida que el precio avanza a favor,
el stop se "arrastra" protegiendo ganancias sin cortarlas prematuramente.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class TrailingStopConfig:
    atr_multiplier: float = 2.0       # Distancia inicial = ATR * multiplier
    tighten_after_rr: float = 1.0     # Apretar trailing después de alcanzar 1R de ganancia
    tighten_multiplier: float = 1.2   # Nuevo multiplicador una vez apretado
    breakeven_at_rr: float = 0.5      # Mover a breakeven después de 0.5R


class TrailingStop:
    """
    Gestiona un trailing stop dinámico basado en ATR.
    
    Flujo:
    1. Se inicia con SL = entry ± (ATR * multiplier)
    2. Cuando ganancia >= 0.5R: mueve SL a breakeven (entry price)
    3. Cuando ganancia >= 1.0R: aprieta el trailing (menor multiplicador)
    4. En cada tick: actualiza SL si el precio se mueve a favor
    """
    def __init__(self, config: Optional[TrailingStopConfig] = None):
        self.config = config or TrailingStopConfig()
        self.active_stops = {}  # signal_id -> stop state

    def initialize(self, signal_id: str, direction: str,
                   entry_price: float, atr: float) -> float:
        """Crea el trailing stop inicial para una señal."""
        multiplier = self.config.atr_multiplier
        
        if direction == 'LONG':
            initial_sl = entry_price - (atr * multiplier)
        else:
            initial_sl = entry_price + (atr * multiplier)

        self.active_stops[signal_id] = {
            'direction': direction,
            'entry': entry_price,
            'atr': atr,
            'current_sl': initial_sl,
            'highest_price': entry_price,    # Para LONG
            'lowest_price': entry_price,     # Para SHORT
            'phase': 'INITIAL',              # INITIAL -> BREAKEVEN -> TIGHT
            'initial_risk': atr * multiplier,
        }
        return initial_sl

    def update(self, signal_id: str, current_price: float) -> dict:
        """
        Actualiza el trailing stop con el precio actual.
        Retorna: {'sl': float, 'phase': str, 'hit': bool}
        """
        if signal_id not in self.active_stops:
            return {'sl': 0, 'phase': 'NONE', 'hit': False}

        state = self.active_stops[signal_id]
        direction = state['direction']
        entry = state['entry']
        atr = state['atr']
        risk = state['initial_risk']
        cfg = self.config

        # Actualizar extremos
        if direction == 'LONG':
            state['highest_price'] = max(state['highest_price'], current_price)
            profit_distance = state['highest_price'] - entry
        else:
            state['lowest_price'] = min(state['lowest_price'], current_price)
            profit_distance = entry - state['lowest_price']

        # Calcular R-múltiplo actual
        r_multiple = profit_distance / risk if risk > 0 else 0

        # Fase: Breakeven
        if r_multiple >= cfg.breakeven_at_rr and state['phase'] == 'INITIAL':
            state['phase'] = 'BREAKEVEN'
            if direction == 'LONG':
                state['current_sl'] = max(state['current_sl'], entry)
            else:
                state['current_sl'] = min(state['current_sl'], entry)

        # Fase: Tighten (apretar)
        if r_multiple >= cfg.tighten_after_rr and state['phase'] != 'TIGHT':
            state['phase'] = 'TIGHT'

        # Calcular nuevo SL candidato
        mult = cfg.tighten_multiplier if state['phase'] == 'TIGHT' else cfg.atr_multiplier

        if direction == 'LONG':
            candidate_sl = state['highest_price'] - (atr * mult)
            # El SL solo puede subir, nunca bajar
            new_sl = max(state['current_sl'], candidate_sl)
            hit = current_price <= new_sl
        else:
            candidate_sl = state['lowest_price'] + (atr * mult)
            # El SL solo puede bajar, nunca subir
            new_sl = min(state['current_sl'], candidate_sl)
            hit = current_price >= new_sl

        state['current_sl'] = new_sl

        return {
            'sl': round(new_sl, 2),
            'phase': state['phase'],
            'hit': hit,
            'r_multiple': round(r_multiple, 2),
        }

    def remove(self, signal_id: str):
        """Eliminar un trailing stop cuando la señal se cierra."""
        self.active_stops.pop(signal_id, None)

    def get_status(self, signal_id: str) -> dict:
        """Obtener estado actual de un trailing stop."""
        state = self.active_stops.get(signal_id)
        if not state:
            return {}
        return {
            'current_sl': round(state['current_sl'], 2),
            'phase': state['phase'],
            'entry': state['entry'],
            'direction': state['direction'],
        }
