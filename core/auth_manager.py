import json
import os
import hashlib
import uuid
import config

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'users_db.json')
INVITE_CODE = config.ADMIN_PASSKEY  # Código secreto dinámico

def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def _load_db() -> dict:
    if not os.path.exists(DB_PATH):
        return {"users": {}}
    with open(DB_PATH, 'r') as f:
        try:
            return json.load(f)
        except:
            return {"users": {}}

def _save_db(data: dict):
    with open(DB_PATH, 'w') as f:
        json.dump(data, f, indent=4)

def register_user(username: str, password: str, invite_code: str) -> tuple[bool, str]:
    if invite_code != INVITE_CODE:
        return False, "❌ Código de invitación inválido. Contacta al admin."
    
    if len(username) < 3 or len(password) < 6:
        return False, "❌ El usuario debe tener 3+ letras y la contraseña 6+."

    db = _load_db()
    
    if username in db["users"]:
        return False, "❌ Ese nombre de Trader ya está en uso."
        
    db["users"][username] = {
        "password": _hash_password(password),
        "role": "trader",
        "created_at": str(uuid.uuid4())[:8] # just a mock id
    }
    _save_db(db)
    return True, "✅ ¡Registro exitoso! Ya puedes ingresar al motor."

def authenticate_user(username: str, password: str) -> tuple[bool, str]:
    db = _load_db()
    if username not in db["users"]:
        return False, "❌ Credenciales incorrectas."
        
    if db["users"][username]["password"] != _hash_password(password):
        return False, "❌ Credenciales incorrectas."
        
    return True, "✅ Acceso concedido."

def update_api_keys(username: str, api_key: str, api_secret: str) -> bool:
    db = _load_db()
    if username in db["users"]:
        db["users"][username]["binance_api_key"] = api_key
        db["users"][username]["binance_secret"] = api_secret
        _save_db(db)
        return True
    return False

def get_user_data(username: str) -> dict:
    db = _load_db()
    if username in db["users"]:
        return db["users"][username]
    return {}
