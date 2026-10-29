"""Interface des fournisseurs d'IA, séparée de la découverte et des coûts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from ..costs import CostEstimate, CostGuard, Decision
from ..models import Category


class AccessKind(str, Enum):
    SIMULE = "simule"
    API_PAYANTE = "api_payante"
    X402 = "x402"
    # Un abonnement de chat (interface web) n'est PAS un accès API : il ne
    # permet aucun appel programmatique et n'est jamais traité comme gratuit.
    ABONNEMENT_CHAT = "abonnement_chat"


class ProviderDisabled(RuntimeError):
    pass


class CallRefused(RuntimeError):
    def __init__(self, decision: Decision):
        super().__init__("; ".join(decision.reasons))
        self.decision = decision


@dataclass(frozen=True)
class ProviderRequest:
    category: Category
    prompt: str


@dataclass(frozen=True)
class ProviderResponse:
    provider: str
    category: Category
    output: str
    simulated: bool
    cost_decision: Decision


class AIProvider(ABC):
    name: str
    access_kind: AccessKind
    categories: frozenset[Category]
    enabled: bool = False

    @property
    def has_api_access(self) -> bool:
        return self.access_kind in (AccessKind.SIMULE, AccessKind.API_PAYANTE, AccessKind.X402)

    @abstractmethod
    def estimate(self, request: ProviderRequest) -> CostEstimate:
        ...

    @abstractmethod
    def _run(self, request: ProviderRequest) -> str:
        ...

    def invoke(self, request: ProviderRequest, guard: CostGuard) -> ProviderResponse:
        if not self.has_api_access:
            raise ProviderDisabled(
                f"« {self.name} »: un abonnement de chat ne donne pas d'accès API"
            )
        if not self.enabled:
            raise ProviderDisabled(f"fournisseur « {self.name} » désactivé")
        if request.category not in self.categories:
            raise ValueError(f"catégorie {request.category.value} non prise en charge")
        decision = guard.authorize(self.estimate(request))
        if not decision.allowed:
            raise CallRefused(decision)
        return ProviderResponse(
            provider=self.name,
            category=request.category,
            output=self._run(request),
            simulated=self.access_kind is AccessKind.SIMULE,
            cost_decision=decision,
        )
