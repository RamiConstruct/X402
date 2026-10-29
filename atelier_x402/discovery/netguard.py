"""Validation des destinations HTTP : refuse tout ce qui n'est pas public."""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit


class DestinationRefused(ValueError):
    pass


Resolver = Callable[[str, int], list[str]]

_LOCAL_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
_LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa", ".corp")


def system_resolver(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    return sorted({info[4][0] for info in infos})


def is_public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


@dataclass(frozen=True)
class ValidatedTarget:
    url: str
    host: str
    port: int
    path: str
    address: str  # adresse IP publique épinglée pour la connexion


def validate_url(
    url: str,
    allowed_hosts: frozenset[str],
    resolver: Resolver = system_resolver,
    allowed_ports: frozenset[int] = frozenset({443}),
) -> ValidatedTarget:
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise DestinationRefused(f"schéma refusé (HTTPS uniquement): {url}")
    if parts.username or parts.password:
        raise DestinationRefused("identifiants dans l'URL refusés")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise DestinationRefused(f"hôte manquant: {url}")
    if host in _LOCAL_NAMES or host.endswith(_LOCAL_SUFFIXES):
        raise DestinationRefused(f"hôte local refusé: {host}")
    if host not in allowed_hosts:
        raise DestinationRefused(f"hôte hors liste blanche: {host}")
    port = parts.port or 443
    if port not in allowed_ports:
        raise DestinationRefused(f"port refusé: {port}")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        raise DestinationRefused(f"adresse IP littérale refusée: {host}")
    try:
        addresses = resolver(host, port)
    except OSError as exc:
        raise DestinationRefused(f"résolution DNS impossible pour {host}: {exc}") from exc
    if not addresses:
        raise DestinationRefused(f"aucune adresse pour {host}")
    for address in addresses:
        if not is_public_ip(address):
            raise DestinationRefused(f"{host} résout vers une adresse non publique: {address}")
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    return ValidatedTarget(url=url, host=host, port=port, path=path, address=addresses[0])
