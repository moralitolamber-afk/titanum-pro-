# core/secure_vault.py
import os
import json
from cryptography.fernet import Fernet
from typing import Tuple

class SecureVault:
    """
    Almacena API keys encriptadas en disco.
    La master key se lee de la variable de entorno VAULT_KEY.
    """
    def __init__(self, db_path: str = "data/secure_vault.json"):
        # Resolve path relative to project root
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.db_path = os.path.join(project_root, db_path)
        
        master = os.getenv("VAULT_KEY")
        if not master:
            # Fallback for dev if needed, but per request we should raise error
            raise RuntimeError("VAULT_KEY no definida en entorno. Genera una con Fernet.generate_key()")
            
        self.cipher = Fernet(master.encode())

    def _ensure_db(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        if not os.path.exists(self.db_path):
            with open(self.db_path, "w") as f:
                json.dump({}, f)

    def store(self, username: str, api_key: str, api_secret: str):
        self._ensure_db()
        with open(self.db_path, "r") as f:
            try:
                db = json.load(f)
            except:
                db = {}
        
        payload = {
            "key": self.cipher.encrypt(api_key.encode()).decode(),
            "secret": self.cipher.encrypt(api_secret.encode()).decode()
        }
        db[username] = payload
        
        with open(self.db_path, "w") as f:
            json.dump(db, f, indent=4)

    def retrieve(self, username: str) -> Tuple[str, str]:
        if not os.path.exists(self.db_path):
            return "", ""
            
        with open(self.db_path, "r") as f:
            try:
                db = json.load(f)
            except:
                return "", ""
                
        user = db.get(username)
        if not user:
            return "", ""
            
        try:
            key = self.cipher.decrypt(user["key"].encode()).decode()
            secret = self.cipher.decrypt(user["secret"].encode()).decode()
            return key, secret
        except Exception as e:
            print(f"Error decrypting keys for {username}: {e}")
            return "", ""
