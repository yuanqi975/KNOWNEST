from datetime import datetime, timedelta, timezone
import hashlib
import bcrypt
import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi import Depends, HTTPException, status
from app.core.config import get_settings
from app.core.db import get_db
from app.models.models import User, Workspace

_PASSWORD_HASH_PREFIX = "weknora-sha256$"


def _bcrypt_secret(value: str) -> str:
    """Return a fixed-size bcrypt input without reducing password entropy."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_password(value: str) -> str:
    digest = _bcrypt_secret(value).encode("ascii")
    hashed = bcrypt.hashpw(digest, bcrypt.gensalt()).decode("ascii")
    return _PASSWORD_HASH_PREFIX + hashed


def verify_password(value: str, hashed: str) -> bool:
    if hashed.startswith(_PASSWORD_HASH_PREFIX):
        return bcrypt.checkpw(
            _bcrypt_secret(value).encode("ascii"),
            hashed[len(_PASSWORD_HASH_PREFIX):].encode("ascii"),
        )
    # Keep accounts created before the pre-hash change usable. Their bcrypt
    # hashes retain the historical 72-byte limitation.
    return bcrypt.checkpw(value.encode("utf-8"), hashed.encode("ascii"))


def token_for(user: User) -> str:
    settings = get_settings()
    return jwt.encode({"sub": user.id, "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_minutes)}, settings.secret_key, algorithm="HS256")


def current_user(db: Session = Depends(get_db)) -> User:
    from fastapi import Request
    # Dependency is replaced by get_current_user in the router where headers are available.
    raise HTTPException(status_code=500, detail="Use get_current_user(request, db)")


def get_current_user(request, db: Session) -> User:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    try:
        payload = jwt.decode(header[7:], get_settings().secret_key, algorithms=["HS256"])
        user = db.get(User, payload.get("sub"))
    except (jwt.PyJWTError, TypeError):
        user = None
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return user


def bootstrap_user(db: Session, username: str, password: str) -> tuple[User, Workspace]:
    if db.scalar(select(User)):
        raise ValueError("setup already completed")
    user = User(username=username, password_hash=hash_password(password))
    db.add(user)
    db.flush()
    workspace = Workspace(owner_id=user.id, name="Personal workspace", description="Your private knowledge workspace")
    db.add(workspace)
    db.commit()
    db.refresh(user)
    db.refresh(workspace)
    return user, workspace
