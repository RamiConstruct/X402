"""Simulation hors ligne d'un futur parcours x402.

Étapes : découverte -> réponse 402 -> vérification des conditions ->
autorisation -> paiement testnet -> résultat.

AUCUNE clé n'est générée, AUCUN portefeuille n'est créé, AUCUNE transaction
n'est construite, signée ni envoyée. L'étape « paiement testnet » n'est
jamais exécutée : au mieux elle est marquée « simulée, non exécutée ».

Les noms ``accepts``, ``scheme`` et ``network`` apparaissent dans le README de
github.com/x402-foundation/x402 (consulté le 2026-10-29) ; les autres champs
(``amount_atomic``, ``asset_symbol``, ``asset_decimals``, ``unit``) sont
propres à l'atelier. Aucune compatibilité avec une version du protocole n'est
revendiquée.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from ..costs import BudgetPolicy, CostEstimate, CostGuard
from ..discovery.fixtures import FIXTURES_DIR
from ..models import Category
from ..normalize import normalize_currency, normalize_unit
from ..providers import ProviderRequest, SimulatedProvider
from ..redact import redact

DEFAULT_SCENARIOS = FIXTURES_DIR / "x402_scenarios_fictifs.json"
SUPPORTED_SCHEMES = frozenset({"exact"})


@dataclass
class Step:
    name: str
    status: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class FlowReport:
    scenario: str
    steps: list[Step]
    simulation: bool = True
    paiement_reel_effectue: bool = False
    transaction: None = None
    rentabilite: str = "non évaluée"

    @property
    def outcome(self) -> str:
        return self.steps[-1].status if self.steps else "vide"

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "simulation": self.simulation,
            "paiement_reel_effectue": self.paiement_reel_effectue,
            "transaction": self.transaction,
            "rentabilite": self.rentabilite,
            "issue": self.outcome,
            "etapes": [{"etape": s.name, "statut": s.status, "details": s.details}
                       for s in self.steps],
        }


def load_scenarios(path: Path | str = DEFAULT_SCENARIOS) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("_meta", {}).get("fictif") is not True:
        raise ValueError("fichier de scénarios non marqué « fictif »: refusé")
    return data


def _amount(option: dict) -> tuple[Decimal | None, list[str]]:
    problems = []
    atomic, decimals = option.get("amount_atomic"), option.get("asset_decimals")
    if atomic is None:
        problems.append("montant atomique absent")
    if not isinstance(decimals, int) or isinstance(decimals, bool) or not 0 <= decimals <= 36:
        problems.append("décimales de l'actif inconnues: montant non interprétable")
    if problems:
        return None, problems
    try:
        value = Decimal(str(atomic))
    except InvalidOperation:
        return None, [f"montant atomique illisible: {atomic!r}"]
    if value < 0 or value != value.to_integral_value():
        return None, [f"montant atomique invalide: {atomic!r}"]
    return value.scaleb(-decimals), []


def check_terms(body: Any, testnets: frozenset[str]) -> tuple[Step, CostEstimate | None]:
    accepts = body.get("accepts") if isinstance(body, dict) else None
    if not isinstance(accepts, list) or not accepts:
        return Step("verification_conditions", "refus", {"raisons": ["aucune option « accepts »"]}), None
    option = accepts[0] if isinstance(accepts[0], dict) else {}
    reasons: list[str] = []
    if option.get("scheme") not in SUPPORTED_SCHEMES:
        reasons.append(f"schéma non pris en charge par la simulation: {option.get('scheme')!r}")
    if option.get("network") not in testnets:
        reasons.append(f"réseau hors liste testnet: {option.get('network')!r}")
    amount, problems = _amount(option)
    reasons.extend(problems)
    warnings: list[str] = []
    currency = normalize_currency(option.get("asset_symbol"), None, warnings)
    unit = normalize_unit(option.get("unit"))
    if currency is None:
        reasons.append("devise/actif inconnu")
    if unit is None:
        reasons.append("unité de facturation inconnue")
    estimate = CostEstimate(billable=True, amount=amount, currency=currency, unit=unit,
                            quantity=Decimal(1))
    details = {"option": redact(option), "montant": None if amount is None else str(amount),
               "devise": currency, "unite": None if unit is None else unit.value}
    if reasons:
        details["raisons"] = reasons
        return Step("verification_conditions", "refus", details), estimate
    return Step("verification_conditions", "ok", details), estimate


def simulate(scenario_name: str, data: dict[str, Any]) -> FlowReport:
    scenarios = data.get("scenarios", {})
    if scenario_name not in scenarios:
        raise KeyError(f"scénario inconnu: {scenario_name} (disponibles: {', '.join(scenarios)})")
    scenario = scenarios[scenario_name]
    testnets = frozenset(data.get("testnets_simules", []))
    hyp = data.get("budget_hypothetique", {})
    steps: list[Step] = []
    report = FlowReport(scenario=scenario_name, steps=steps)

    service = scenario.get("service", {})
    steps.append(Step("decouverte", "ok", {"service": redact(service),
                                           "provenance": "fictif"}))

    response = scenario.get("response", {})
    if response.get("status") != 402:
        steps.append(Step("reponse_402", "arret",
                          {"statut": response.get("status"), "note": "pas de 402: rien à payer"}))
        return report
    steps.append(Step("reponse_402", "observee", {
        "en_tetes": redact(response.get("headers", {})),
        "action": "arret et observation; aucun paiement automatique",
    }))

    terms_step, estimate = check_terms(response.get("body"), testnets)
    steps.append(terms_step)
    if terms_step.status != "ok" or estimate is None:
        return report

    real_guard = CostGuard(BudgetPolicy(session_cap=Decimal(17), currency=None))
    real = real_guard.authorize(estimate)
    hypo_guard = CostGuard(BudgetPolicy(
        session_cap=_dec(hyp.get("session_cap")),
        per_call_cap=_dec(hyp.get("per_call_cap")),
        currency=hyp.get("currency"),
    ))
    hypo = hypo_guard.evaluate_hypothetical(estimate)
    status = "hypothese_ok_reel_refuse" if hypo.allowed else "refus"
    steps.append(Step("autorisation", status, {
        "decision_reelle": {"autorise": real.allowed, "raisons": list(real.reasons)},
        "evaluation_hypothetique": {"autorise": hypo.allowed, "raisons": list(hypo.reasons),
                                    "budget": hyp},
        "note": "l'évaluation hypothétique n'autorise jamais une dépense réelle",
    }))
    if not hypo.allowed:
        return report

    steps.append(Step("paiement_testnet", "simule_non_execute", {
        "cle_generee": False, "portefeuille_cree": False, "transaction": None,
        "note": "aucune signature, aucun envoi; le lot testnet réel est séparé",
    }))
    output = SimulatedProvider()._run(ProviderRequest(Category.TEXTE, scenario_name))
    steps.append(Step("resultat", "simule", {
        "reponse": output,
        "attention": "simulation réussie ≠ paiement réussi ≠ rentabilité",
    }))
    return report


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None
