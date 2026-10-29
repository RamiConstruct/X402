"""Interface commune des adaptateurs de découverte."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..models import ServiceRecord


class DiscoveryDisabled(RuntimeError):
    """L'adaptateur n'a pas été explicitement activé."""


@dataclass
class PaymentRequiredObservation:
    """Une réponse HTTP 402 observée : arrêt, aucune tentative de paiement."""

    url: str
    observed_at_utc: str
    headers: dict[str, str]
    body: Any
    action: str = "arret_observation_sans_paiement"


@dataclass
class DiscoveryResult:
    records: list[ServiceRecord] = field(default_factory=list)
    payment_required: list[PaymentRequiredObservation] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class DiscoverySource(ABC):
    name: str

    @abstractmethod
    def discover(self) -> DiscoveryResult:
        """Collecte des descriptions. Ne doit jamais payer ni appeler un service payant."""
