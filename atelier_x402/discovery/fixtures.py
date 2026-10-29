"""Découverte hors ligne à partir de fixtures JSON fictives."""

from __future__ import annotations

import json
from pathlib import Path

from ..models import Provenance, Source, utc_now_iso
from ..normalize import normalize_item
from .base import DiscoveryResult, DiscoverySource

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"
DEFAULT_FIXTURE = FIXTURES_DIR / "services_fictifs.json"


class FixtureDiscovery(DiscoverySource):
    name = "fixtures"

    def __init__(self, path: Path | str = DEFAULT_FIXTURE):
        self.path = Path(path)

    def discover(self) -> DiscoveryResult:
        result = DiscoveryResult()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        meta = data.get("_meta", {}) if isinstance(data, dict) else {}
        if meta.get("fictif") is not True:
            result.errors.append(
                f"{self.path.name}: fixture non marquée « fictif »: refusée"
            )
            return result
        source = Source(kind="fixture", uri=self.path.name, retrieved_at_utc=utc_now_iso())
        for item in data.get("services", []):
            result.records.append(normalize_item(item, source, Provenance.FICTIF))
        return result
