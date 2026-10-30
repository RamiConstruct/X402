"""Schéma d'événements officiels « point dans le temps » (spécification, lot LAB-001).

Aucun collecteur : ce module ne télécharge rien. Il fixe le schéma et les règles
de disponibilité pour de futurs lots (sources prévues : BLS, Fed, RBA, SEC).

Champs : ``id``, ``source``, ``kind`` (calendrier | publication | revision),
``url``, ``sha256`` (empreinte du contenu archivé, ou null si rien n'a été
archivé), ``period`` (période décrite), ``indicator`` (série), ``published_at`` (publication
officielle), ``first_seen_at`` (première observation par le système),
``available_at`` (instant à partir duquel le système peut l'utiliser),
``version``, ``corrects`` (id de la version corrigée), ``value`` (null pour un
calendrier).

Règles :
* ``available_at >= max(published_at, first_seen_at)`` : on ne peut pas utiliser
  une donnée avant de l'avoir vue ;
* un calendrier annonce une date, il ne contient PAS la publication future ;
* une révision n'est pas disponible rétroactivement : à l'instant t, on ne voit
  que la dernière version dont ``available_at <= t`` ;
* pas de « surprise » sans consensus historique horodaté et disponible à t.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

KINDS = ("calendrier", "publication", "revision")


class EventError(ValueError):
    pass


def _ts(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise EventError(f"{name}: horodatage texte ISO 8601 exigé")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise EventError(f"{name}: horodatage illisible {value!r}") from None
    if parsed.tzinfo is None:
        raise EventError(f"{name}: fuseau horaire exigé")
    return parsed


@dataclass(frozen=True)
class OfficialEvent:
    id: str
    source: str
    kind: str
    url: str | None
    sha256: str | None
    period: str | None
    indicator: str | None
    published_at: datetime
    first_seen_at: datetime
    available_at: datetime
    version: int
    corrects: str | None
    value: Any

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OfficialEvent":
        kind = data.get("kind")
        if kind not in KINDS:
            raise EventError(f"kind inconnu: {kind!r}")
        event = cls(
            id=str(data["id"]), source=str(data["source"]), kind=kind, url=data.get("url"),
            sha256=data.get("sha256"), period=data.get("period"), indicator=data.get("indicator"),
            published_at=_ts(data.get("published_at"), "published_at"),
            first_seen_at=_ts(data.get("first_seen_at"), "first_seen_at"),
            available_at=_ts(data.get("available_at"), "available_at"),
            version=int(data.get("version", 1)), corrects=data.get("corrects"),
            value=data.get("value"),
        )
        if event.available_at < max(event.published_at, event.first_seen_at):
            raise EventError(f"{event.id}: available_at antérieur à la publication ou à l'observation")
        if kind == "calendrier" and event.value is not None:
            raise EventError(f"{event.id}: un calendrier ne contient pas la publication future")
        if kind == "revision" and not event.corrects:
            raise EventError(f"{event.id}: une révision doit indiquer « corrects »")
        return event


def load_events(items: list[dict[str, Any]]) -> list[OfficialEvent]:
    """Charge et valide le graphe des révisions AVANT tout calcul.

    Rejette : identifiants en double, référence inconnue, auto-référence,
    cycle, et toute révision incohérente avec ce qu'elle corrige (version non
    croissante, autre source, période ou indicateur, ou disponibilité
    antérieure à la version corrigée : une correction n'est jamais rétroactive).
    """
    events = [OfficialEvent.from_dict(item) for item in items]
    by_id: dict[str, OfficialEvent] = {}
    for e in events:
        if e.id in by_id:
            raise EventError(f"identifiant d'événement en double: {e.id!r}")
        by_id[e.id] = e
    for e in events:
        if not e.corrects:
            continue
        if e.corrects == e.id:
            raise EventError(f"{e.id}: se corrige lui-même")
        target = by_id.get(e.corrects)
        if target is None:
            raise EventError(f"{e.id}: corrige un événement inconnu {e.corrects!r}")
        if target.kind == "calendrier":
            raise EventError(f"{e.id}: un calendrier ne se corrige pas par une révision de valeur")
        if e.version <= target.version:
            raise EventError(f"{e.id}: version {e.version} <= version corrigée {target.version}")
        for name in ("source", "period", "indicator"):
            if getattr(e, name) != getattr(target, name):
                raise EventError(f"{e.id}: {name} différent de l'événement corrigé")
        if e.available_at < target.available_at or e.published_at < target.published_at:
            raise EventError(f"{e.id}: disponible ou publié avant l'événement qu'il corrige")
    for e in events:
        _root(e, by_id)  # détecte les cycles (A -> B -> A) avec un parcours borné
    return events


def _root(event: OfficialEvent, by_id: dict[str, OfficialEvent]) -> str:
    seen = {event.id}
    for _ in range(len(by_id)):
        if not event.corrects:
            return event.id
        event = by_id[event.corrects]
        if event.id in seen:
            raise EventError(f"cycle de révisions passant par {event.id!r}")
        seen.add(event.id)
    raise EventError("chaîne de révisions trop longue (cycle probable)")


def available_at(events: list[OfficialEvent], t: datetime) -> list[OfficialEvent]:
    """Vue « point dans le temps » : dernière version disponible de chaque série."""
    by_id = {e.id: e for e in events}
    latest: dict[str, OfficialEvent] = {}
    for e in events:
        if e.available_at > t:
            continue
        root = _root(e, by_id)
        if root not in latest or e.version > latest[root].version:
            latest[root] = e
    return sorted(latest.values(), key=lambda e: (e.available_at, e.id))


CONSENSUS_FIELDS = ("value", "source", "indicator", "period", "cutoff_at", "available_at")


def _finite(value: Any, name: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise EventError(f"{name}: valeur manquante ou invalide")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise EventError(f"{name}: valeur illisible {value!r}") from None
    if not number.is_finite():
        raise EventError(f"{name}: valeur non finie")
    return number


def surprise(event: OfficialEvent, consensus: dict[str, Any] | None, t: datetime) -> Decimal:
    """Surprise INITIALE = publication - consensus ex ante, à l'instant de décision t.

    Le consensus doit avoir une provenance (``source``), concerner le même
    indicateur et la même période, et être figé (``cutoff_at``) puis disponible
    (``available_at``) STRICTEMENT avant ``published_at`` de la publication.
    Convention d'égalité : un consensus daté exactement de l'instant de
    publication est refusé, faute de pouvoir prouver qu'il le précède. Un
    consensus obtenu après l'annonce n'est pas un consensus, même s'il est
    disponible avant t. Une révision n'a pas de surprise initiale : voir
    ``revision_delta``. Aucun consensus n'est jamais inventé.
    """
    if event.kind != "publication":
        raise EventError(f"surprise initiale définie seulement pour une publication, pas « {event.kind} »")
    if event.available_at > t:
        raise EventError("publication pas encore disponible à cet instant")
    if not consensus or any(k not in consensus for k in CONSENSUS_FIELDS):
        raise EventError("pas de surprise sans consensus horodaté et sourcé "
                         f"(champs requis: {', '.join(CONSENSUS_FIELDS)})")
    if not consensus["source"]:
        raise EventError("consensus sans provenance")
    if consensus["indicator"] != event.indicator or consensus["period"] != event.period:
        raise EventError("consensus d'un autre indicateur ou d'une autre période")
    cutoff = _ts(consensus["cutoff_at"], "consensus.cutoff_at")
    published = _ts(consensus["available_at"], "consensus.available_at")
    if cutoff > published:
        raise EventError("consensus figé après sa propre disponibilité")
    if published >= event.published_at or cutoff >= event.published_at:
        raise EventError("consensus non antérieur à la publication (ex post ou simultané)")
    if published > t:
        raise EventError("consensus pas encore disponible à cet instant")
    return _finite(event.value, "publication") - _finite(consensus["value"], "consensus")


def revision_delta(revision: OfficialEvent, events: list[OfficialEvent], t: datetime) -> Decimal:
    """Écart révision - version corrigée, seulement si les deux sont disponibles à t."""
    if revision.kind != "revision" or not revision.corrects:
        raise EventError("revision_delta exige une révision")
    if revision.available_at > t:
        raise EventError("révision pas encore disponible à cet instant")
    target = next((e for e in events if e.id == revision.corrects), None)
    if target is None or target.available_at > t:
        raise EventError("version corrigée inconnue ou indisponible")
    return _finite(revision.value, "révision") - _finite(target.value, "version corrigée")
