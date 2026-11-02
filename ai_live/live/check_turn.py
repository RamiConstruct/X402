"""Vérifie qu'un relais TURN fonctionne : obtient une adresse relayée en UDP et en TCP.

    python -m live.check_turn --urls '["turn:1.2.3.4:3478?transport=udp","turn:1.2.3.4:3478?transport=tcp"]' --secret <secret>
    python -m live.check_turn --urls '[...]' --username u --password p      # identifiants statiques
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from urllib.parse import parse_qs, urlparse

from aioice import turn

from .turn import credentials


def parse(url: str) -> tuple[str, int, str, bool]:
    scheme, rest = url.split(":", 1)
    u = urlparse(f"//{rest}")
    transport = parse_qs(u.query).get("transport", ["udp"])[0]
    secure = scheme == "turns"
    return u.hostname, u.port or (5349 if secure else 3478), "tcp" if secure else transport, secure


def parse_urls(raw: str) -> list[str]:
    """Accepte du JSON ou une liste « [a,b] » / « a,b » dont le shell a retiré les guillemets."""
    try:
        v = json.loads(raw)
        return v if isinstance(v, list) else [v]
    except json.JSONDecodeError:
        return [u.strip().strip("'\"") for u in raw.strip("[] ").split(",") if u.strip()]


async def check(url: str, username: str, password: str, timeout: float = 8) -> tuple[bool, str]:
    host, port, transport, secure = parse(url)
    try:
        t, _ = await asyncio.wait_for(turn.create_turn_endpoint(
            asyncio.DatagramProtocol, server_addr=(host, port), username=username, password=password,
            transport=transport, ssl=secure or None), timeout)
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"
    relayed = t.get_extra_info("sockname")
    t.close()
    return True, f"adresse relayée {relayed[0]}:{relayed[1]}"


async def main_async(a) -> int:
    urls = parse_urls(a.urls)
    if a.secret:
        username, password = credentials(a.secret, "check", 600)
    else:
        username, password = a.username, a.password
    ok_all = True
    for url in urls:
        ok, msg = await check(url, username, password)
        ok_all &= ok
        print(f"{'✓' if ok else '✗'} {url} — {msg}")
    if not ok_all:
        print("\nPistes : pare-feu de l'hébergeur (3478 TCP/UDP, 49160-49800 UDP), secret incorrect, service arrêté "
              "(sudo systemctl status coturn).")
    return 0 if ok_all else 1


def main() -> None:
    ap = argparse.ArgumentParser(prog="live.check_turn")
    ap.add_argument("--urls", required=True, help="liste JSON d'URL turn:/turns:")
    ap.add_argument("--secret")
    ap.add_argument("--username")
    ap.add_argument("--password")
    a = ap.parse_args()
    if not a.secret and not (a.username and a.password):
        ap.error("--secret ou --username/--password requis")
    sys.exit(asyncio.run(main_async(a)))


if __name__ == "__main__":
    main()
