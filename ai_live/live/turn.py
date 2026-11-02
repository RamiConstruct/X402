"""Identifiants TURN temporaires (mécanisme « REST API » de coturn : use-auth-secret).

username   = "<expiration_unix>:<étiquette>"
credential = base64( HMAC-SHA1(secret, username) )

Le secret reste sur la console ; le navigateur, la page OBS et le worker ne reçoivent
que des identifiants qui expirent.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time


def credentials(secret: str, label: str = "live", ttl_s: int = 6 * 3600, now: float | None = None) -> tuple[str, str]:
    username = f"{int((now or time.time()) + ttl_s)}:{label}"
    digest = hmac.new(secret.encode(), username.encode(), hashlib.sha1).digest()
    return username, base64.b64encode(digest).decode()


def ice_servers(secret: str | None, urls: list[str] | None, label: str = "live", ttl_s: int = 6 * 3600) -> list[dict]:
    if not secret or not urls:
        return []
    user, cred = credentials(secret, label, ttl_s)
    return [{"urls": urls, "username": user, "credential": cred}]


def ice_from_env(label: str = "live", ttl_s: int = 6 * 3600) -> list[dict]:
    """Serveurs ICE pour la console : TURN temporaire (LIVE_TURN_SECRET + LIVE_TURN_URLS)
    et/ou liste statique (LIVE_ICE_SERVERS)."""
    out = json.loads(os.environ["LIVE_ICE_SERVERS"]) if os.environ.get("LIVE_ICE_SERVERS") else []
    urls = json.loads(os.environ["LIVE_TURN_URLS"]) if os.environ.get("LIVE_TURN_URLS") else None
    return out + ice_servers(os.environ.get("LIVE_TURN_SECRET"), urls, label, ttl_s)
