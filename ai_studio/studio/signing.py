"""URLs signées à durée limitée (téléchargement, lecture, et récupération par un fournisseur)."""
from __future__ import annotations

import hashlib
import hmac
import time


def sign(secret: str, asset_id: str, ttl_s: int = 3600, now: float | None = None) -> tuple[int, str]:
    exp = int((now if now is not None else time.time()) + ttl_s)
    mac = hmac.new(secret.encode(), f"{asset_id}:{exp}".encode(), hashlib.sha256).hexdigest()
    return exp, mac


def verify(secret: str, asset_id: str, exp: int, sig: str, now: float | None = None) -> bool:
    if exp < (now if now is not None else time.time()):
        return False
    expected = hmac.new(secret.encode(), f"{asset_id}:{exp}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)
