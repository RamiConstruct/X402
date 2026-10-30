"""Exports : JSON complet et synthèse Markdown lisible."""

from __future__ import annotations

import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from .discovery.base import DiscoveryResult
from .models import ServiceRecord, utc_now_iso
from .redact import redact

AVERTISSEMENT = (
    "Données de découverte uniquement. Aucun service n'a été acheté ni appelé "
    "pour une prestation payante. « fictif » = donnée inventée pour l'atelier ; "
    "« declaration_commerciale » = affirmation d'un tiers, non vérifiée ; "
    "« teste_reellement » = jamais produit dans ce lot."
)


_COVERAGE_NOTES = {
    "complete": "toutes les sources lues sans erreur ni 402",
    "partielle": "des services ont été lus, mais des erreurs, des 402 ou des éléments "
                 "invalides limitent la couverture",
    "echec": "aucun service lu: erreurs ou 402 seulement",
    "vide": "aucune donnée et aucune erreur: ce n'est PAS une réussite",
}


def _plain(value: Any) -> Any:
    """Rend l'export sérialisable : Decimal -> texte exact (jamais de float)."""
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    return value


def coverage(result: DiscoveryResult) -> dict[str, Any]:
    invalid = sum(1 for r in result.records if not isinstance(r.raw, dict))
    problems = bool(result.errors or result.payment_required or invalid)
    if result.records:
        state = "partielle" if problems else "complete"
    else:
        state = "echec" if problems else "vide"
    return {
        "etat": state,
        "note": _COVERAGE_NOTES[state],
        "services": len(result.records),
        "elements_invalides": invalid,
        "erreurs": len(result.errors),
        "reponses_402": len(result.payment_required),
    }


def comparison_report(result: DiscoveryResult) -> dict[str, Any]:
    """Comparaison accompagnée de tout ce qui en limite la portée."""
    return _plain(redact({
        "couverture": coverage(result),
        "comparaison": compare(result.records),
        "erreurs": result.errors,
        "reponses_402_observees": [vars(o) for o in result.payment_required],
    }))


def result_to_dict(result: DiscoveryResult) -> dict[str, Any]:
    return _plain(redact({
        "genere_le_utc": utc_now_iso(),
        "avertissement": AVERTISSEMENT,
        "couverture": coverage(result),
        "services": [r.to_dict() for r in result.records],
        "reponses_402_observees": [vars(o) for o in result.payment_required],
        "erreurs": result.errors,
        "comparaison": compare(result.records),
    }))


def compare(records: list[ServiceRecord]) -> dict[str, Any]:
    """Classe les prix uniquement à devise ET unité identiques. Pas de conversion."""
    groups: dict[str, list[ServiceRecord]] = defaultdict(list)
    not_comparable: list[dict[str, Any]] = []
    for record in records:
        if not record.price.is_complete:
            not_comparable.append({"record_id": record.record_id,
                                   "service": record.service_name,
                                   "manque": [u for u in record.unknowns if u.startswith("price.")]})
            continue
        key = f"{record.capability.value}|{record.price.currency}|{record.price.unit.value}"
        groups[key].append(record)
    ranked = {}
    for key, items in sorted(groups.items()):
        items.sort(key=lambda r: r.price.amount)
        ranked[key] = [{"record_id": r.record_id, "fournisseur": r.provider,
                        "service": r.service_name, "prix": str(r.price.amount),
                        "provenance": r.provenance.value} for r in items]
    return {"groupes_comparables": ranked, "non_comparables": not_comparable}


def _cell(value: Any) -> str:
    return "inconnu" if value is None else str(value).replace("|", "/")


def summary_markdown(result: DiscoveryResult) -> str:
    cov = coverage(result)
    lines = ["# Synthèse de découverte", "", f"Généré le {utc_now_iso()} (UTC).", "",
             f"> {AVERTISSEMENT}", "",
             f"**Couverture : {cov['etat']}** — {cov['note']} "
             f"({cov['services']} services, {cov['elements_invalides']} éléments invalides, "
             f"{cov['erreurs']} erreurs, {cov['reponses_402']} réponses 402).", "",
             "| Fournisseur | Service | Capacité | Prix | Devise | Unité | Provenance | Vérification | Inconnues |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in result.records:
        lines.append("| " + " | ".join(_cell(v) for v in (
            r.provider, r.service_name, r.capability.value, r.price.amount, r.price.currency,
            None if r.price.unit is None else r.price.unit.value, r.provenance.value,
            r.verification_status.value, ", ".join(r.unknowns) or "aucune")) + " |")
    comparison = compare(result.records)
    lines += ["", "## Comparaison (même capacité, devise et unité ; aucune conversion)", ""]
    if not comparison["groupes_comparables"]:
        lines.append("Aucun groupe comparable.")
    for key, items in comparison["groupes_comparables"].items():
        lines.append(f"- **{key}** : " + " < ".join(
            f"{_cell(i['service'])} ({i['prix']}, {i['provenance']})" for i in items))
    if comparison["non_comparables"]:
        lines += ["", "Non comparables (prix incomplet) : " + ", ".join(
            _cell(i["service"]) for i in comparison["non_comparables"])]
    if result.payment_required:
        lines += ["", "## Réponses HTTP 402 observées (aucun paiement effectué)", ""]
        lines += [f"- {o.url} à {o.observed_at_utc}"
                  + (f" (corps non lu: {o.body_error})" if o.body_error else "")
                  for o in result.payment_required]
    warnings = [(r.service_name, w) for r in result.records for w in r.warnings]
    if warnings:
        lines += ["", "## Avertissements", ""]
        lines += [f"- {_cell(name)} : {w}" for name, w in warnings]
    if result.errors:
        lines += ["", "## Erreurs", ""] + [f"- {e}" for e in result.errors]
    return redact("\n".join(lines) + "\n")


def write_outputs(result: DiscoveryResult, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "decouverte.json"
    md_path = out_dir / "synthese.md"
    json_path.write_text(json.dumps(result_to_dict(result), ensure_ascii=False, indent=2,
                                    default=str) + "\n", encoding="utf-8")
    md_path.write_text(summary_markdown(result), encoding="utf-8")
    return json_path, md_path
