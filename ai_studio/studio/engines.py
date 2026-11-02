"""Registre des moteurs : un moteur = un manifeste YAML + un adaptateur.

Ajouter un modèle = ajouter un fichier dans engines/ (et, seulement si son API
est nouvelle, un adaptateur dans studio/providers/). Les prix sont des DONNÉES
datées (`pricing.verified_on`), jamais du code.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from .config import Settings
from .money import ceil_decimal_to_int, micro_to_credits_ceil, usd_to_micro_exact


@dataclass(frozen=True)
class Pricing:
    unit: str                    # "second" (seconde de vidéo produite, arrondie à la seconde supérieure) ou "job"
    usd_per_unit: Decimal
    min_charge_usd: Decimal
    markup: Decimal              # prix client = coût × markup, arrondi au crédit supérieur
    min_price_credits: int
    verified_on: str | None
    source: str | None

    def units_for(self, duration_s: float) -> int:
        if self.unit == "second":
            return max(1, math.ceil(duration_s - 1e-9))
        if self.unit == "job":
            return 1
        raise ValueError(f"unité de prix inconnue : {self.unit}")

    def cost_micro(self, duration_s: float) -> int:
        raw = ceil_decimal_to_int(self.usd_per_unit * self.units_for(duration_s) * 1_000_000)
        return max(raw, usd_to_micro_exact(self.min_charge_usd))

    def price_credits(self, cost_micro: int) -> int:
        return max(self.min_price_credits, micro_to_credits_ceil(ceil_decimal_to_int(Decimal(cost_micro) * self.markup)))


@dataclass(frozen=True)
class EngineSpec:
    id: str
    provider: str
    adapter: str
    display_name: str
    capabilities: tuple[str, ...]
    enabled: bool
    paid: bool
    simulated: bool
    quality: int
    max_duration_s: float
    speed_factor: float          # secondes de calcul par seconde de vidéo (estimation, à remplacer par télémétrie)
    pricing: Pricing
    params: dict[str, Any] = field(default_factory=dict)
    policy: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def unavailable_reason(self, settings: Settings) -> str | None:
        if not self.enabled:
            return "désactivé dans le manifeste"
        if self.simulated and settings.allow_paid_providers:
            return "simulateur désactivé quand les fournisseurs réels sont actifs"
        if self.paid and not settings.allow_paid_providers:
            return "fournisseurs payants désactivés (STUDIO_ALLOW_PAID_PROVIDERS=false)"
        if self.paid and not settings.provider_key(self.provider):
            return f"clé API {self.provider} absente"
        return None


def _parse(data: dict[str, Any], path: Path) -> EngineSpec:
    p = data["pricing"]
    try:
        return EngineSpec(
            id=data["id"], provider=data["provider"], adapter=data["adapter"],
            display_name=data.get("display_name", data["id"]),
            capabilities=tuple(data["capabilities"]), enabled=bool(data.get("enabled", True)),
            paid=bool(data.get("paid", True)), simulated=bool(data.get("simulated", False)),
            quality=int(data.get("quality", 50)),
            max_duration_s=float(data.get("limits", {}).get("max_duration_s", 60)),
            speed_factor=float(data.get("speed_factor", 1.0)),
            pricing=Pricing(unit=p["unit"], usd_per_unit=Decimal(str(p["usd_per_unit"])),
                            min_charge_usd=Decimal(str(p.get("min_charge_usd", "0"))),
                            markup=Decimal(str(p.get("markup", "1.8"))),
                            min_price_credits=int(p.get("min_price_credits", 1)),
                            verified_on=p.get("verified_on"), source=p.get("source")),
            params=data.get("params", {}) or {}, policy=data.get("policy", {}) or {},
            notes=data.get("notes", ""),
        )
    except (KeyError, ValueError, TypeError) as e:
        raise ValueError(f"manifeste invalide {path.name} : {e}") from e


class Registry:
    def __init__(self, engines: list[EngineSpec]) -> None:
        ids = [e.id for e in engines]
        if len(ids) != len(set(ids)):
            raise ValueError("identifiants de moteurs dupliqués")
        self.engines = {e.id: e for e in engines}

    @classmethod
    def load(cls, directory: Path) -> "Registry":
        specs = [_parse(yaml.safe_load(f.read_text(encoding="utf-8")), f) for f in sorted(directory.glob("*.yaml"))]
        return cls(specs)

    def get(self, engine_id: str) -> EngineSpec:
        return self.engines[engine_id]

    def candidates(self, capability: str, duration_s: float, settings: Settings) -> tuple[list[EngineSpec], list[dict]]:
        """Moteurs utilisables pour une capacité, + liste des exclus avec la raison (transparence)."""
        ok, excluded = [], []
        for e in self.engines.values():
            if capability not in e.capabilities:
                continue
            reason = e.unavailable_reason(settings)
            if reason is None and duration_s > e.max_duration_s:
                reason = f"durée {duration_s:.1f}s > limite {e.max_duration_s:.0f}s"
            if reason:
                excluded.append({"engine": e.id, "reason": reason})
            else:
                ok.append(e)
        return ok, excluded

    def describe(self, settings: Settings) -> list[dict]:
        out = []
        for e in self.engines.values():
            out.append({
                "id": e.id, "name": e.display_name, "provider": e.provider, "capabilities": list(e.capabilities),
                "paid": e.paid, "simulated": e.simulated, "quality": e.quality,
                "max_duration_s": e.max_duration_s, "available": e.unavailable_reason(settings) is None,
                "unavailable_reason": e.unavailable_reason(settings),
                "pricing": {"unit": e.pricing.unit, "usd_per_unit": str(e.pricing.usd_per_unit),
                            "min_charge_usd": str(e.pricing.min_charge_usd), "markup": str(e.pricing.markup),
                            "verified_on": e.pricing.verified_on, "source": e.pricing.source},
                "notes": e.notes,
            })
        return out
