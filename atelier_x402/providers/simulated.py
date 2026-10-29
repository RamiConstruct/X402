"""Fournisseur simulé : sorties déterministes, aucun réseau, coût nul."""

from __future__ import annotations

import hashlib

from ..costs import NON_BILLABLE, CostEstimate
from ..models import Category
from .base import AccessKind, AIProvider, ProviderRequest


class SimulatedProvider(AIProvider):
    name = "simule"
    access_kind = AccessKind.SIMULE
    categories = frozenset(c for c in Category if c is not Category.INCONNUE)
    enabled = True

    def estimate(self, request: ProviderRequest) -> CostEstimate:
        return NON_BILLABLE

    def _run(self, request: ProviderRequest) -> str:
        digest = hashlib.sha256(request.prompt.encode()).hexdigest()[:8]
        return f"[SIMULATION {request.category.value}] réponse fictive #{digest}"
