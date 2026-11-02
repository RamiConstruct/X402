"""Serveurs ICE / TURN pour la console, le navigateur, la page OBS et les GPU loués.

Deux relais possibles, cumulables (le navigateur choisit le meilleur) :

1. **Cloudflare Realtime TURN** (recommandé pour un streamer nomade) : réseau mondial anycast,
   ports 443 UDP/TCP/TLS (passe les Wi-Fi filtrés), 1 000 Go/mois gratuits puis 0,05 $/Go (doc
   Cloudflare, sept. 2026). Variables : LIVE_CF_TURN_KEY_ID, LIVE_CF_TURN_API_TOKEN.
   La console échange la clé contre des identifiants temporaires via
   POST https://rtc.live.cloudflare.com/v1/turn/keys/{id}/credentials/generate-ice-servers.

2. **coturn sur ton VPS** (secours, sous ton contrôle) : identifiants temporaires « REST » de coturn
   (use-auth-secret). Variables : LIVE_TURN_SECRET, LIVE_TURN_URLS.

Dans les deux cas, le secret reste sur la console ; les clients ne reçoivent que des identifiants qui expirent.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import threading
import time

import httpx

CF_ENDPOINT = "https://rtc.live.cloudflare.com/v1/turn/keys/{key_id}/credentials/generate-ice-servers"


def credentials(secret: str, label: str = "live", ttl_s: int = 6 * 3600, now: float | None = None) -> tuple[str, str]:
    username = f"{int((now or time.time()) + ttl_s)}:{label}"
    digest = hmac.new(secret.encode(), username.encode(), hashlib.sha1).digest()
    return username, base64.b64encode(digest).decode()


def ice_servers(secret: str | None, urls: list[str] | None, label: str = "live", ttl_s: int = 6 * 3600) -> list[dict]:
    if not secret or not urls:
        return []
    user, cred = credentials(secret, label, ttl_s)
    return [{"urls": urls, "username": user, "credential": cred}]


class CloudflareTurn:
    """Génère (et met en cache) des identifiants Cloudflare Realtime TURN temporaires."""

    def __init__(self, key_id: str, api_token: str, client: httpx.Client | None = None) -> None:
        self.key_id, self.api_token = key_id, api_token
        self.client = client or httpx.Client(timeout=10)
        self._cache: dict[int, tuple[float, list[dict]]] = {}
        self._lock = threading.Lock()

    def ice_servers(self, ttl_s: int = 6 * 3600) -> list[dict]:
        with self._lock:
            hit = self._cache.get(ttl_s)
            if hit and hit[0] - time.time() > ttl_s * 0.5:  # réutilisé tant qu'il reste plus de la moitié de la durée
                return hit[1]
        r = self.client.post(CF_ENDPOINT.format(key_id=self.key_id), json={"ttl": ttl_s},
                             headers={"Authorization": f"Bearer {self.api_token}"})
        if r.status_code >= 400:
            raise RuntimeError(f"Cloudflare TURN : HTTP {r.status_code} {r.text[:200]}")
        servers = []
        for s in r.json().get("iceServers", []):
            urls = s["urls"] if isinstance(s["urls"], list) else [s["urls"]]
            urls = [u for u in urls if ":53?" not in u and not u.endswith(":53")]  # port 53 bloqué par les navigateurs
            if urls:
                servers.append({**s, "urls": urls})
        with self._lock:
            self._cache[ttl_s] = (time.time() + ttl_s, servers)
        return servers


_cf: CloudflareTurn | None = None


def _cloudflare() -> CloudflareTurn | None:
    global _cf
    kid, tok = os.environ.get("LIVE_CF_TURN_KEY_ID"), os.environ.get("LIVE_CF_TURN_API_TOKEN")
    if not kid or not tok:
        return None
    if _cf is None or _cf.key_id != kid:
        _cf = CloudflareTurn(kid, tok)
    return _cf


def ice_from_env(label: str = "live", ttl_s: int = 6 * 3600) -> list[dict]:
    """Liste statique (LIVE_ICE_SERVERS) + Cloudflare TURN + coturn du VPS, selon ce qui est configuré."""
    out = json.loads(os.environ["LIVE_ICE_SERVERS"]) if os.environ.get("LIVE_ICE_SERVERS") else []
    cf = _cloudflare()
    if cf:
        try:
            out += cf.ice_servers(ttl_s)
        except (RuntimeError, httpx.HTTPError):
            pass  # le relais de secours (coturn) prend le relais s'il est configuré
    urls = json.loads(os.environ["LIVE_TURN_URLS"]) if os.environ.get("LIVE_TURN_URLS") else None
    return out + ice_servers(os.environ.get("LIVE_TURN_SECRET"), urls, label, ttl_s)
