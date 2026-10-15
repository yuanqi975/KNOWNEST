import base64
import hashlib
from cryptography.fernet import Fernet
from app.core.config import get_settings


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(get_settings().secret_key.encode()).digest())
    return Fernet(key)


def encrypt(value: str | None) -> str | None:
    return _fernet().encrypt(value.encode()).decode() if value else None


def decrypt(value: str | None) -> str:
    return _fernet().decrypt(value.encode()).decode() if value else ""
