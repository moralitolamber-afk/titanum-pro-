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

from core.secure_vault import SecureVault

vault = None
try:
    vault = SecureVault()
except Exception as e:
    print(f"Warning: SecureVault not initialized: {e}")

def update_api_keys(username: str, api_key: str, api_secret: str) -> bool:
    if not vault:
        return False
    try:
        vault.store(username, api_key, api_secret)
        return True
    except:
        return False

def get_keys(username: str) -> tuple[str, str]:
    if not vault:
        return "", ""
    return vault.retrieve(username)

def get_user_data(username: str) -> dict:
    db = _load_db()
    if username in db["users"]:
        return db["users"][username]
    return {}
