"""Registre des fournisseurs. Seul le fournisseur simulé est actif.

Les adaptateurs réels sont des emplacements réservés : aucun point d'accès,
aucun prix, aucune clé. Ils restent désactivés et leur estimation de coût est
inconnue, donc tout appel serait refusé par ``CostGuard`` de toute façon.
"""

from __future__ import annotations

from ..costs import CostEstimate
from ..models import Category
from .base import AccessKind, AIProvider, ProviderDisabled, ProviderRequest
from .simulated import SimulatedProvider


class DisabledProvider(AIProvider):
    enabled = False

    def __init__(self, name: str, access_kind: AccessKind, categories: set[Category], note: str):
        self.name = name
        self.access_kind = access_kind
        self.categories = frozenset(categories)
        self.note = note

    def estimate(self, request: ProviderRequest) -> CostEstimate:
        return CostEstimate(billable=None)

    def _run(self, request: ProviderRequest) -> str:
        raise ProviderDisabled(f"« {self.name} » non implémenté dans ce lot")


def default_registry() -> list[AIProvider]:
    every = {c for c in Category if c is not Category.INCONNUE}
    return [
        SimulatedProvider(),
        DisabledProvider("api_generique_payante", AccessKind.API_PAYANTE, every,
                         "emplacement pour une API IA payante (clé requise, non fournie)"),
        DisabledProvider("service_x402", AccessKind.X402, every,
                         "emplacement pour un service payé via x402 (lot testnet séparé)"),
        DisabledProvider("abonnement_chat", AccessKind.ABONNEMENT_CHAT, every,
                         "abonnement de chat: pas d'accès API, jamais considéré gratuit"),
    ]
