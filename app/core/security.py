from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import User


def hash_password(password: str) -> str:
    """Genera un hash seguro utilizando PBKDF2-HMAC-SHA256 con sal aleatoria."""
    salt = secrets.token_hex(16)
    iterations = 100_000
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    return f"pbkdf2:sha256:{iterations}${salt}${key.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica si una contraseña en texto plano coincide con el hash almacenado."""
    try:
        parts = hashed_password.split("$")
        if len(parts) != 3:
            return False
        header, salt, expected_hex = parts
        _, _, iterations_str = header.split(":")
        iterations = int(iterations_str)
        calculated = hashlib.pbkdf2_hmac(
            "sha256", plain_password.encode("utf-8"), salt.encode("utf-8"), iterations
        )
        return hmac.compare_digest(calculated.hex(), expected_hex)
    except Exception:
        return False


def create_access_token(user_id: int, username: str, expires_in_seconds: Optional[int] = None) -> str:
    """Crea un token de sesión firmado criptográficamente con HMAC-SHA256."""
    settings = get_settings()
    exp_seconds = expires_in_seconds or settings.session_max_age_seconds
    exp_timestamp = int(time.time()) + exp_seconds

    payload = {
        "user_id": user_id,
        "username": username,
        "exp": exp_timestamp,
    }
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8").rstrip("=")
    signature = hmac.new(settings.secret_key.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{signature}"


def verify_access_token(token: str) -> Optional[dict]:
    """Verifica y decodifica un token de sesión firmado. Retorna None si es inválido o expiró."""
    if not token or "." not in token:
        return None
    try:
        payload_b64, signature = token.split(".", 1)
        settings = get_settings()
        expected_sig = hmac.new(
            settings.secret_key.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(signature, expected_sig):
            return None

        # Rellenar padding base64
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload_json = base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
        payload = json.loads(payload_json)

        if payload.get("exp", 0) < time.time():
            return None  # Expirado

        return payload
    except Exception:
        return None


def init_admin_user(session: Session) -> User:
    """Crea o actualiza el usuario administrador configurado en .env."""
    settings = get_settings()
    admin = session.scalar(select(User).where(User.username == settings.admin_username.strip()).limit(1))
    
    if admin is None:
        admin = User(
            username=settings.admin_username.strip(),
            password_hash=hash_password(settings.admin_password),
            full_name="Administrador del Sistema",
            email="admin@local.host",
            is_admin=True,
            active=True,
        )
        session.add(admin)
        session.commit()
        session.refresh(admin)
    else:
        # Sincronizar contraseña con la indicada en el archivo .env actual
        admin.password_hash = hash_password(settings.admin_password)
        admin.active = True
        session.commit()
        session.refresh(admin)
        
    return admin
