"""Adaptateur optionnel de découverte HTTP publique — DÉSACTIVÉ par défaut.

Il lit uniquement des listes publiques au format de l'atelier
(``{"services": [...], "next": "https://..."}`` ou une liste). Ce format
n'est PAS le format d'une API de découverte x402 : aucune compatibilité n'est
revendiquée tant que https://docs.x402.org n'a pas été vérifiée.

Garde-fous :

* activation explicite + liste blanche d'hôtes, HTTPS seul, port 443 ;
* résolution DNS validée (adresses publiques uniquement) puis connexion
  épinglée sur l'adresse validée (limite la réutilisation DNS) ;
* redirections : même hôte uniquement par défaut, nombre limité, revalidées ;
* délai par requête, échéance globale, taille maximale, pages et éléments
  limités, tentatives limitées (erreurs réseau et 5xx seulement) ;
* HTTP 402 => arrêt de la source et observation. Jamais de paiement, jamais
  de réessai. Aucun en-tête d'authentification n'est envoyé.
"""

from __future__ import annotations

import http.client
import json
import logging
import socket
import ssl
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urljoin

from ..models import Provenance, Source, utc_now_iso
from ..normalize import normalize_item
from ..redact import redact
from .base import DiscoveryDisabled, DiscoveryResult, DiscoverySource, PaymentRequiredObservation
from .netguard import DestinationRefused, Resolver, ValidatedTarget, system_resolver, validate_url

log = logging.getLogger("atelier_x402.http")

USER_AGENT = "atelier-x402-decouverte/0.1 (lecture seule; aucun paiement)"
_REDIRECTS = {301, 302, 303, 307, 308}


class ResponseTooLarge(IOError):
    pass


@dataclass(frozen=True)
class HttpPolicy:
    allowed_hosts: frozenset[str] = frozenset()
    max_sources: int = 3
    timeout_s: float = 5.0
    total_deadline_s: float = 30.0
    max_response_bytes: int = 256_000
    max_pages: int = 3
    max_items: int = 200
    max_attempts: int = 2
    backoff_s: float = 0.5
    max_redirects: int = 1
    allow_cross_host_redirects: bool = False
    allowed_ports: frozenset[int] = frozenset({443})

    def __post_init__(self) -> None:
        if self.max_attempts < 1 or self.max_pages < 1 or self.max_sources < 1:
            raise ValueError("les limites doivent être >= 1")


@dataclass
class RawResponse:
    status: int
    headers: dict[str, str]
    body: bytes = b""


Transport = Callable[[ValidatedTarget, float, int], RawResponse]


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connexion TLS vers l'adresse déjà validée, avec SNI/vérification sur l'hôte."""

    def __init__(self, target: ValidatedTarget, timeout: float):
        super().__init__(target.host, target.port, timeout=timeout,
                         context=ssl.create_default_context())
        self._address = target.address

    def connect(self) -> None:
        sock = socket.create_connection((self._address, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def default_transport(target: ValidatedTarget, timeout: float, max_bytes: int) -> RawResponse:
    conn = _PinnedHTTPSConnection(target, timeout)
    try:
        conn.request("GET", target.path, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        })
        resp = conn.getresponse()
        headers = {k.lower(): v for k, v in resp.getheaders()}
        length = headers.get("content-length")
        if length and length.isdigit() and int(length) > max_bytes:
            raise ResponseTooLarge(f"Content-Length {length} > {max_bytes}")
        body = resp.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise ResponseTooLarge(f"réponse > {max_bytes} octets")
        return RawResponse(status=resp.status, headers=headers, body=body)
    finally:
        conn.close()


@dataclass
class PublicHttpDiscovery(DiscoverySource):
    sources: list[str]
    policy: HttpPolicy
    enabled: bool = False
    transport: Transport = default_transport
    resolver: Resolver = system_resolver
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    name: str = field(default="http_public", init=False)

    def discover(self) -> DiscoveryResult:
        if not self.enabled:
            raise DiscoveryDisabled(
                "découverte HTTP désactivée: activation explicite requise (--enable-http)"
            )
        result = DiscoveryResult()
        if len(self.sources) > self.policy.max_sources:
            result.errors.append(
                f"{len(self.sources)} sources demandées, limite {self.policy.max_sources}: "
                "sources excédentaires ignorées"
            )
        deadline = self.clock() + self.policy.total_deadline_s
        for url in self.sources[: self.policy.max_sources]:
            self._discover_source(url, result, deadline)
        return result

    # -- une source, avec pagination ----------------------------------------
    def _discover_source(self, url: str, result: DiscoveryResult, deadline: float) -> None:
        next_url: str | None = url
        seen: set[str] = set()
        items_count = 0
        for _page in range(self.policy.max_pages):
            if next_url is None:
                return
            if next_url in seen:
                result.errors.append(f"{next_url}: boucle de pagination détectée")
                return
            seen.add(next_url)
            try:
                final_url, response = self._fetch(next_url, deadline)
            except (DestinationRefused, ResponseTooLarge, TimeoutError, OSError,
                    http.client.HTTPException) as exc:
                result.errors.append(f"{next_url}: {type(exc).__name__}: {exc}")
                return
            if response.status == 402:
                result.payment_required.append(self._observe_402(final_url, response))
                log.info("HTTP 402 sur %s: arrêt et observation, aucun paiement", final_url)
                return
            if response.status != 200:
                result.errors.append(f"{final_url}: statut HTTP {response.status}")
                return
            try:
                payload = json.loads(response.body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                result.errors.append(f"{final_url}: JSON illisible: {exc}")
                return
            items, next_url = _split_page(payload, final_url)
            source = Source(kind="http", uri=final_url, retrieved_at_utc=utc_now_iso())
            for item in items:
                if items_count >= self.policy.max_items:
                    result.errors.append(f"{url}: limite de {self.policy.max_items} éléments atteinte")
                    return
                result.records.append(
                    normalize_item(item, source, Provenance.DECLARATION_COMMERCIALE)
                )
                items_count += 1
        if next_url is not None:
            result.errors.append(f"{url}: limite de {self.policy.max_pages} pages atteinte")

    # -- une requête, avec redirections et tentatives -------------------------
    def _fetch(self, url: str, deadline: float) -> tuple[str, RawResponse]:
        origin_host: str | None = None
        current = url
        for _hop in range(self.policy.max_redirects + 1):
            target = validate_url(current, self.policy.allowed_hosts, self.resolver,
                                  self.policy.allowed_ports)
            origin_host = origin_host or target.host
            response = self._attempts(target, deadline)
            if response.status not in _REDIRECTS:
                return current, response
            location = response.headers.get("location")
            if not location:
                raise DestinationRefused(f"redirection {response.status} sans Location")
            nxt = urljoin(current, location)
            nxt_host = validate_url(nxt, self.policy.allowed_hosts, self.resolver,
                                    self.policy.allowed_ports).host
            if nxt_host != origin_host and not self.policy.allow_cross_host_redirects:
                raise DestinationRefused(f"redirection inter-hôtes refusée: {current} -> {nxt}")
            current = nxt
        raise DestinationRefused(f"trop de redirections (> {self.policy.max_redirects})")

    def _attempts(self, target: ValidatedTarget, deadline: float) -> RawResponse:
        last_exc: Exception | None = None
        for attempt in range(1, self.policy.max_attempts + 1):
            remaining = deadline - self.clock()
            if remaining <= 0:
                raise TimeoutError("échéance globale de découverte dépassée")
            timeout = min(self.policy.timeout_s, remaining)
            try:
                response = self.transport(target, timeout, self.policy.max_response_bytes)
            except ResponseTooLarge:
                raise
            except (TimeoutError, OSError, http.client.HTTPException) as exc:
                last_exc = exc
            else:
                # 402 et 4xx : jamais de nouvelle tentative.
                if response.status < 500 or attempt == self.policy.max_attempts:
                    return response
            if attempt < self.policy.max_attempts:
                self.sleep(self.policy.backoff_s * attempt)
        assert last_exc is not None
        raise last_exc

    @staticmethod
    def _observe_402(url: str, response: RawResponse) -> PaymentRequiredObservation:
        try:
            body: Any = json.loads(response.body.decode("utf-8")) if response.body else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = {"non_json": True, "octets": len(response.body)}
        return PaymentRequiredObservation(
            url=url,
            observed_at_utc=utc_now_iso(),
            headers=redact(dict(response.headers)),
            body=redact(body),
        )


def _split_page(payload: Any, base_url: str) -> tuple[list[Any], str | None]:
    if isinstance(payload, list):
        return payload, None
    if not isinstance(payload, dict):
        return [], None
    items = payload.get("services")
    items = items if isinstance(items, list) else []
    nxt = payload.get("next")
    return items, urljoin(base_url, nxt) if isinstance(nxt, str) and nxt else None
