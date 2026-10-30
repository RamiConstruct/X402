"""Schéma d'événements officiels « point dans le temps » (spécification, lot LAB-001).

Aucun collecteur : ce module ne télécharge rien. Il fixe le schéma et les règles
de disponibilité pour de futurs lots (sources prévues : BLS, Fed, RBA, SEC).

Champs : ``id``, ``source``, ``kind`` (calendrier | publication | revision),
``url``, ``sha256`` (empreinte du contenu archivé, ou null si rien n'a été
archivé), ``period`` (période décrite), ``published_at`` (publication
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
            sha256=data.get("sha256"), period=data.get("period"),
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
    events = [OfficialEvent.from_dict(item) for item in items]
    ids = [e.id for e in events]
    if len(ids) != len(set(ids)):
        raise EventError("identifiants d'événements en double")
    known = set(ids)
    for e in events:
        if e.corrects and e.corrects not in known:
            raise EventError(f"{e.id}: corrige un événement inconnu {e.corrects!r}")
    return events


def _root(event: OfficialEvent, by_id: dict[str, OfficialEvent]) -> str:
    while event.corrects:
        event = by_id[event.corrects]
    return event.id


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


def surprise(event: OfficialEvent, consensus: dict[str, Any] | None, t: datetime) -> Any:
    """Écart publication - consensus, refusé sans consensus horodaté disponible à t."""
    if event.available_at > t:
        raise EventError("publication pas encore disponible à cet instant")
    if not consensus or "available_at" not in consensus or "value" not in consensus:
        raise EventError("pas de surprise calculable sans consensus historique horodaté")
    if _ts(consensus["available_at"], "consensus.available_at") > t:
        raise EventError("consensus pas encore disponible à cet instant")
    if event.value is None or consensus["value"] is None:
        raise EventError("valeur manquante")
    return event.value - consensus["value"]
