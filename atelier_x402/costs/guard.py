"""Contrôle des coûts.

Dans ce lot, tout appel facturable est bloqué par une constante de code
(``BILLABLE_CALLS_ALLOWED``) qu'aucune configuration ne peut lever. Les
plafonds par appel et par session sont déjà évalués pour préparer la suite,
mais ne suffisent jamais à autoriser une dépense.

Règles (une seule suffit à refuser ; toutes les raisons sont listées) :

1. caractère facturable inconnu => refus ;
2. prix, devise, unité ou estimation inconnus => refus ;
3. devise du budget non confirmée ou différente => refus (aucune conversion) ;
4. dépassement du plafond par appel ou du reste de session => refus ;
5. appels facturables bloqués dans ce lot => refus.

Un réessai payant n'est jamais autorisé automatiquement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ..models import BillingUnit

BILLABLE_CALLS_ALLOWED = False  # verrou du lot 1 : ne pas rendre configurable


@dataclass(frozen=True)
class CostEstimate:
    billable: bool | None
    amount: Decimal | None = None
    currency: str | None = None
    unit: BillingUnit | None = None
    quantity: Decimal | None = None  # nombre d'unités estimé pour cet appel

    @property
    def total(self) -> Decimal | None:
        if self.amount is None or self.quantity is None:
            return None
        return self.amount * self.quantity


NON_BILLABLE = CostEstimate(billable=False, amount=Decimal(0), currency=None,
                            unit=BillingUnit.PAR_REQUETE, quantity=Decimal(1))


@dataclass(frozen=True)
class BudgetPolicy:
    """Plafonds futurs. ``currency=None`` signifie devise non confirmée."""

    session_cap: Decimal | None = None
    per_call_cap: Decimal | None = None
    currency: str | None = None


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reasons: tuple[str, ...]
    billable: bool | None
    is_retry: bool = False


@dataclass
class CostGuard:
    policy: BudgetPolicy
    spent: Decimal = Decimal(0)
    journal: list[Decision] = field(default_factory=list)

    def authorize(self, estimate: CostEstimate, *, is_retry: bool = False) -> Decision:
        decision = self._evaluate(estimate, is_retry)
        self.journal.append(decision)
        return decision

    def evaluate_hypothetical(self, estimate: CostEstimate) -> Decision:
        """Évalue les règles 1 à 4 seulement, pour la simulation. N'autorise rien."""
        reasons = self._rules(estimate, is_retry=False, include_lock=False)
        return Decision(allowed=not reasons, reasons=tuple(reasons), billable=estimate.billable)

    def _evaluate(self, estimate: CostEstimate, is_retry: bool) -> Decision:
        if estimate.billable is False:
            if is_retry:
                return Decision(True, ("réessai non facturable",), False, True)
            return Decision(True, ("non facturable",), False, False)
        reasons = self._rules(estimate, is_retry, include_lock=True)
        return Decision(allowed=False, reasons=tuple(reasons), billable=estimate.billable,
                        is_retry=is_retry)

    def _rules(self, estimate: CostEstimate, is_retry: bool, include_lock: bool) -> list[str]:
        reasons: list[str] = []
        if estimate.billable is None:
            reasons.append("caractère facturable inconnu")
        if estimate.amount is None:
            reasons.append("prix inconnu")
        if estimate.currency is None:
            reasons.append("devise inconnue")
        if estimate.unit is None:
            reasons.append("unité de facturation inconnue")
        if estimate.quantity is None:
            reasons.append("estimation de consommation inconnue")
        if self.policy.currency is None:
            reasons.append("devise du budget non confirmée")
        elif estimate.currency is not None and estimate.currency != self.policy.currency:
            reasons.append(
                f"devise {estimate.currency} différente du budget {self.policy.currency} "
                "(aucune conversion)"
            )
        if self.policy.per_call_cap is None:
            reasons.append("plafond par appel non configuré")
        if self.policy.session_cap is None:
            reasons.append("plafond de session non configuré")
        total = estimate.total
        if total is not None and self.policy.per_call_cap is not None \
                and total > self.policy.per_call_cap:
            reasons.append(f"coût estimé {total} > plafond par appel {self.policy.per_call_cap}")
        if total is not None and self.policy.session_cap is not None \
                and self.spent + total > self.policy.session_cap:
            reasons.append(
                f"coût estimé {total} > reste de session {self.policy.session_cap - self.spent}"
            )
        if is_retry:
            reasons.append("réessai payant automatique interdit")
        if include_lock and not BILLABLE_CALLS_ALLOWED:
            reasons.append("appels facturables bloqués dans ce lot")
        return reasons
