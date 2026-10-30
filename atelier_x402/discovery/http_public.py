"""Adaptateur optionnel de découverte HTTP publique — DÉSACTIVÉ par défaut.

Il lit uniquement des listes publiques au format de l'atelier
(``{"services": [...], "next": "https://..."}`` ou une liste). Ce format
n'est PAS le format d'une API de découverte x402 (Bazaar, MCP ou autre) :
aucune compatibilité n'est revendiquée.

Garde-fous :

* activation explicite + liste blanche d'hôtes, HTTPS seul, port 443 ;
* résolution DNS validée (adresses publiques uniquement) puis connexion
  épinglée sur l'adresse validée (limite la réutilisation DNS) ;
* redirections : même hôte uniquement par défaut, nombre limité, revalidées ;
* budget de temps (voir ``Deadline``), taille maximale, pages, éléments et
  tentatives limités ; tentatives seulement si aucun statut n'a été reçu ou
  sur 5xx avec corps complet ;
* HTTP 402 => arrêt de la source et observation. Jamais de paiement, jamais
  de nouvelle tentative, même si le corps de la 402 est illisible ou coupé.
  Aucun en-tête d'authentification n'est envoyé.

Budget de temps — ce qui est garanti et ce qui ne l'est pas :

* ``total_deadline_s`` couvre l'ensemble d'une découverte : DNS, connexion,
  TLS, en-têtes, corps et pauses entre tentatives ; ``timeout_s`` borne en plus
  chaque requête (connexion jusqu'à la fin du corps).
* Le corps est lu par blocs, avec un délai de socket recalculé avant chaque
  lecture, et un minuteur ferme la connexion à l'échéance.
* La résolution DNS (``getaddrinfo``) ne peut pas être interrompue en Python :
  l'atelier cesse d'ATTENDRE à l'échéance, mais le fil de résolution (démon)
  peut continuer en arrière-plan jusqu'au délai du système.
* Le retour peut dépasser l'échéance d'une marge de nettoyage (fermeture de
  socket, ordonnancement des fils), en pratique courte mais non garantie.
"""

from __future__ import annotations

import http.client
import json
import logging
import socket
import ssl
import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal
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


class Deadline:
    """Échéance absolue sur une horloge monotone, partagée entre les étapes."""

    def __init__(self, budget_s: float, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self.expires_at = clock() + budget_s

    def remaining(self) -> float:
        return self.expires_at - self._clock()

    def expired(self) -> bool:
        return self.remaining() <= 0

    def child(self, budget_s: float) -> "Deadline":
        """Sous-échéance qui ne dépasse jamais l'échéance parente."""
        sub = Deadline(0, self._clock)
        sub.expires_at = min(self.expires_at, sub.expires_at + budget_s)
        return sub


class PartialResponse(IOError):
    """Statut et en-têtes reçus, mais corps incomplet, trop long ou hors délai."""

    def __init__(self, status: int, headers: dict[str, str], reason: str):
        super().__init__(reason)
        self.status = status
        self.headers = headers
        self.reason = reason


class ResponseTooLarge(PartialResponse):
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
        if not (self.timeout_s > 0 and self.total_deadline_s > 0):
            raise ValueError("les délais doivent être > 0")


@dataclass
class RawResponse:
    status: int
    headers: dict[str, str]
    body: bytes = b""
    body_error: str | None = None


Transport = Callable[[ValidatedTarget, Deadline, int], RawResponse]


def resolve_within(resolver: Resolver, host: str, port: int, deadline: Deadline) -> list[str]:
    """Résolution DNS dont l'ATTENTE est bornée (voir la docstring du module)."""
    remaining = deadline.remaining()
    if remaining <= 0:
        raise TimeoutError("échéance dépassée avant la résolution DNS")
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = resolver(host, port)
        except BaseException as exc:  # transmis au fil appelant
            box["error"] = exc

    worker = threading.Thread(target=run, name="atelier-dns", daemon=True)
    worker.start()
    worker.join(remaining)
    if worker.is_alive():
        raise TimeoutError(
            f"résolution DNS de {host} non terminée à l'échéance (abandonnée, non interrompue)"
        )
    if "error" in box:
        raise box["error"]
    return box["value"]


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connexion TLS vers l'adresse déjà validée, avec SNI/vérification sur l'hôte.

    ``abort()`` (appelé par le minuteur depuis un autre fil) doit interrompre le
    socket réellement utilisé. ``SSLContext.wrap_socket`` DÉTACHE le socket brut
    (son descripteur passe au ``SSLSocket``) : un ``shutdown`` sur l'objet brut
    n'aurait plus d'effet. On enregistre donc le socket actif à chaque étape,
    sous verrou, et la négociation TLS est lancée seulement APRÈS
    l'enregistrement du ``SSLSocket`` (``do_handshake_on_connect=False``), pour
    qu'elle soit interruptible elle aussi.
    """

    def __init__(self, target: ValidatedTarget, timeout: float,
                 context: ssl.SSLContext | None = None):
        super().__init__(target.host, target.port, timeout=timeout,
                         context=context or ssl.create_default_context())
        self._address = target.address
        self._lock = threading.Lock()
        self._active: socket.socket | None = None
        self._aborted = False

    def _open_raw(self) -> socket.socket:
        return socket.create_connection((self._address, self.port), self.timeout)

    def _register(self, sock: socket.socket) -> None:
        """Enregistre le socket actif ; refuse si l'abandon a déjà eu lieu."""
        with self._lock:
            aborted = self._aborted
            if not aborted:
                self._active = sock
        if aborted:
            sock.close()
            raise TimeoutError("connexion abandonnée à l'échéance")

    def connect(self) -> None:
        if self._aborted:
            raise TimeoutError("connexion abandonnée à l'échéance")
        raw = self._open_raw()
        self._register(raw)
        tls = self._context.wrap_socket(raw, server_hostname=self.host,
                                        do_handshake_on_connect=False)
        self._register(tls)  # le socket brut est détaché à partir d'ici
        self.sock = tls
        tls.do_handshake()

    def set_timeout(self, seconds: float) -> None:
        self.timeout = seconds
        if self.sock is not None:
            self.sock.settimeout(seconds)

    def abort(self) -> None:
        """Appelé par le minuteur : interrompt le socket actif, TLS compris.

        ``socket.socket.shutdown`` agit sur le descripteur sans modifier l'état
        interne de ``SSLSocket`` utilisé par l'autre fil.
        """
        with self._lock:
            self._aborted = True
            active = self._active
        if active is not None:
            try:
                socket.socket.shutdown(active, socket.SHUT_RDWR)
            except OSError:
                pass


@dataclass
class HttpsTransport:
    """Transport GET réel. ``connection_factory`` est remplaçable pour les tests."""

    connection_factory: Callable[[ValidatedTarget, float], Any] = _PinnedHTTPSConnection
    chunk_size: int = 16_384

    def __call__(self, target: ValidatedTarget, deadline: Deadline, max_bytes: int) -> RawResponse:
        remaining = deadline.remaining()
        if remaining <= 0:
            raise TimeoutError("échéance dépassée avant la connexion")
        conn = self.connection_factory(target, remaining)
        watchdog = threading.Timer(remaining, conn.abort)
        watchdog.daemon = True
        watchdog.start()
        try:
            conn.request("GET", target.path, headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            })
            conn.set_timeout(max(deadline.remaining(), 0.001))
            resp = conn.getresponse()
            headers = {k.lower(): v for k, v in resp.getheaders()}
            body = self._read_body(conn, resp, resp.status, headers, deadline, max_bytes)
            return RawResponse(status=resp.status, headers=headers, body=body)
        finally:
            watchdog.cancel()
            conn.close()

    def _read_body(self, conn: Any, resp: Any, status: int, headers: dict[str, str],
                   deadline: Deadline, max_bytes: int) -> bytes:
        """Lit le corps. ``read1()`` peut renvoyer ``b""`` sur une fin prématurée
        sans lever d'exception : la longueur annoncée est donc vérifiée ici."""
        length = headers.get("content-length", "").strip()
        expected = int(length) if length.isdigit() else None
        if expected is not None and expected > max_bytes:
            raise ResponseTooLarge(status, headers, f"Content-Length {length} > {max_bytes} octets")
        read = getattr(resp, "read1", None) or resp.read
        chunks: list[bytes] = []
        total = 0
        while True:
            remaining = deadline.remaining()
            if remaining <= 0:
                raise PartialResponse(status, headers, "échéance atteinte pendant la lecture du corps")
            conn.set_timeout(remaining)
            try:
                chunk = read(min(self.chunk_size, max_bytes + 1 - total))
            except (OSError, http.client.HTTPException) as exc:
                cause = "échéance atteinte" if deadline.expired() else type(exc).__name__
                raise PartialResponse(status, headers, f"corps interrompu: {cause}") from exc
            if not chunk:
                if expected is not None and total != expected:
                    raise PartialResponse(
                        status, headers, f"corps tronqué: {total}/{expected} octets reçus"
                    )
                return b"".join(chunks)
            total += len(chunk)
            chunks.append(chunk)
            if total > max_bytes:
                raise ResponseTooLarge(status, headers, f"réponse > {max_bytes} octets")


@dataclass
class PublicHttpDiscovery(DiscoverySource):
    sources: list[str]
    policy: HttpPolicy
    enabled: bool = False
    transport: Transport = field(default_factory=HttpsTransport)
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
        deadline = Deadline(self.policy.total_deadline_s, self.clock)
        for url in self.sources[: self.policy.max_sources]:
            self._discover_source(url, result, deadline)
        return result

    # -- une source, avec pagination ----------------------------------------
    def _discover_source(self, url: str, result: DiscoveryResult, deadline: Deadline) -> None:
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
            except (DestinationRefused, TimeoutError, OSError, http.client.HTTPException) as exc:
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
                payload = json.loads(response.body.decode("utf-8"), parse_float=Decimal)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                result.errors.append(f"{final_url}: JSON illisible: {exc}")
                return
            items, next_url, schema_error = _split_page(payload, final_url)
            source = Source(kind="http", uri=final_url, retrieved_at_utc=utc_now_iso())
            for item in items:
                if items_count >= self.policy.max_items:
                    result.errors.append(f"{url}: limite de {self.policy.max_items} éléments atteinte")
                    return
                result.records.append(
                    normalize_item(item, source, Provenance.DECLARATION_COMMERCIALE)
                )
                items_count += 1
            if schema_error:
                result.errors.append(f"{final_url}: {schema_error}")
                return
        if next_url is not None:
            result.errors.append(f"{url}: limite de {self.policy.max_pages} pages atteinte")

    # -- une requête, avec redirections et tentatives -------------------------
    def _validate(self, url: str, deadline: Deadline) -> ValidatedTarget:
        dns_deadline = deadline.child(self.policy.timeout_s)
        return validate_url(
            url, self.policy.allowed_hosts,
            lambda host, port: resolve_within(self.resolver, host, port, dns_deadline),
            self.policy.allowed_ports,
        )

    def _fetch(self, url: str, deadline: Deadline) -> tuple[str, RawResponse]:
        origin_host: str | None = None
        current = url
        for _hop in range(self.policy.max_redirects + 1):
            target = self._validate(current, deadline)
            origin_host = origin_host or target.host
            response = self._attempts(target, deadline)
            if response.status not in _REDIRECTS:
                return current, response
            location = response.headers.get("location")
            if not location:
                raise DestinationRefused(f"redirection {response.status} sans Location")
            nxt = urljoin(current, location)
            nxt_host = self._validate(nxt, deadline).host
            if nxt_host != origin_host and not self.policy.allow_cross_host_redirects:
                raise DestinationRefused(f"redirection inter-hôtes refusée: {current} -> {nxt}")
            current = nxt
        raise DestinationRefused(f"trop de redirections (> {self.policy.max_redirects})")

    def _attempts(self, target: ValidatedTarget, deadline: Deadline) -> RawResponse:
        last_exc: Exception | None = None
        last_response: RawResponse | None = None
        for attempt in range(1, self.policy.max_attempts + 1):
            if deadline.expired():
                raise TimeoutError("échéance globale de découverte dépassée")
            try:
                response = self.transport(target, deadline.child(self.policy.timeout_s),
                                          self.policy.max_response_bytes)
            except PartialResponse as exc:
                # Un statut a été reçu : jamais de nouvelle tentative.
                if exc.status == 402:
                    return RawResponse(402, exc.headers, b"", body_error=exc.reason)
                raise
            except (TimeoutError, OSError, http.client.HTTPException) as exc:
                last_exc, last_response = exc, None
            else:
                # 402 et autres statuts < 500 : jamais de nouvelle tentative.
                if response.status < 500:
                    return response
                last_exc, last_response = None, response
            if attempt == self.policy.max_attempts:
                break
            pause = self.policy.backoff_s * attempt
            if pause >= deadline.remaining():
                break
            self.sleep(pause)
        if last_response is not None:
            return last_response
        if last_exc is not None:
            raise last_exc
        raise TimeoutError("échéance globale de découverte dépassée")

    @staticmethod
    def _observe_402(url: str, response: RawResponse) -> PaymentRequiredObservation:
        body: Any
        if response.body_error:
            body = None
        elif not response.body:
            body = None
        else:
            try:
                body = json.loads(response.body.decode("utf-8"), parse_float=Decimal)
            except (UnicodeDecodeError, json.JSONDecodeError):
                body = {"non_json": True, "octets": len(response.body)}
        return PaymentRequiredObservation(
            url=url,
            observed_at_utc=utc_now_iso(),
            headers=redact(dict(response.headers)),
            body=redact(body),
            body_error=response.body_error,
        )


def _split_page(payload: Any, base_url: str) -> tuple[list[Any], str | None, str | None]:
    """Retourne (éléments, page suivante, erreur de schéma)."""
    if isinstance(payload, list):
        return payload, None, None
    if not isinstance(payload, dict):
        return [], None, f"schéma invalide: racine de type {type(payload).__name__}"
    items = payload.get("services")
    if not isinstance(items, list):
        return [], None, "schéma invalide: champ « services » absent ou non liste"
    nxt = payload.get("next")
    if nxt is None or nxt == "":
        return items, None, None
    if not isinstance(nxt, str):
        return items, None, "schéma invalide: « next » n'est pas une URL texte"
    return items, urljoin(base_url, nxt), None
