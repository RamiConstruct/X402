from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AuthToken, User

_ITER = 210_000
TOKEN_DAYS = 30


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITER).hex()
    return f"pbkdf2_sha256${_ITER}${salt}${dk}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, it, salt, dk = stored.split("$")
    except ValueError:
        return False
    cand = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(it)).hex()
    return hmac.compare_digest(cand, dk)


def issue_token(s: Session, user: User) -> str:
    raw = secrets.token_urlsafe(32)
    s.add(AuthToken(token_hash=hashlib.sha256(raw.encode()).hexdigest(), user_id=user.id,
                    expires_at=datetime.now(timezone.utc) + timedelta(days=TOKEN_DAYS)))
    return raw


def user_for_token(s: Session, raw: str) -> User | None:
    tok = s.get(AuthToken, hashlib.sha256(raw.encode()).hexdigest())
    if tok is None:
        return None
    exp = tok.expires_at if tok.expires_at.tzinfo else tok.expires_at.replace(tzinfo=timezone.utc)
    if exp < datetime.now(timezone.utc):
        return None
    return s.get(User, tok.user_id)


def find_user(s: Session, email: str) -> User | None:
    return s.execute(select(User).where(User.email == email.strip().lower())).scalar_one_or_none()
