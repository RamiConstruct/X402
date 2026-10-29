"""Exports : JSON complet et synthèse Markdown lisible."""

from __future__ import annotations

import json
from collections import defaultdict
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


def result_to_dict(result: DiscoveryResult) -> dict[str, Any]:
    return redact({
        "genere_le_utc": utc_now_iso(),
        "avertissement": AVERTISSEMENT,
        "services": [r.to_dict() for r in result.records],
        "reponses_402_observees": [vars(o) for o in result.payment_required],
        "erreurs": result.errors,
        "comparaison": compare(result.records),
    })


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
    lines = ["# Synthèse de découverte", "", f"Généré le {utc_now_iso()} (UTC).", "",
             f"> {AVERTISSEMENT}", "",
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
        lines += [f"- {o.url} à {o.observed_at_utc}" for o in result.payment_required]
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
