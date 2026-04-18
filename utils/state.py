"""
Estado persistente del bot — Guardar y cargar estado en JSON.
Permite que el bot recuerde su estado si se reinicia.
"""
import json
import os
from datetime import datetime


STATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'bot_state.json'
)


def save_state(breaker_status: dict, sizer_status: dict, ai_status: dict):
    """Guardar estado actual a disco."""
    state = {
        'timestamp': datetime.now().isoformat(),
        'circuit_breaker': breaker_status,
        'position_sizer': sizer_status,
        'ai_brain': {
            'panic_mode': ai_status.get('panic_mode', False),
            'reason': ai_status.get('reason', ''),
            'score': ai_status.get('score', 50),
        },
    }
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2, ensure_ascii=False, default=str)
    except Exception:
        pass  # No crashear por problemas de disco


def load_state() -> dict:
    """Cargar estado previo desde disco."""
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}
