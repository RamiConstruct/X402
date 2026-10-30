"""Chargement des scénarios et rapports JSON / Markdown (déterministes)."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from . import BANNER
from .arbitrage import Params, Result, evaluate
from .book import Market, to_decimal
from .replay import Event, Replay

SCENARIOS_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "lab"


class ScenarioError(ValueError):
    pass


def load_scenario(path: Path | str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"), parse_float=Decimal)
    if data.get("fictif") is not True:
        raise ScenarioError(f"{Path(path).name}: scénario non marqué « fictif »: refusé")
    return data


def run_scenario(data: dict[str, Any]) -> Result:
    markets = {m["venue"]: Market.from_dict(m) for m in data["markets"]}
    events = [Event.from_dict(e) for e in data["events"]]
    inventory = {v: {a: to_decimal(x, f"{v}.{a}") for a, x in assets.items()}
                 for v, assets in data["inventory"].items()}
    return evaluate(markets, Replay(markets, events), Params.from_dict(data["params"]), inventory)


def plain(value: Any) -> Any:
    if is_dataclass(value):
        return plain(asdict(value))
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    return value


def scenario_report(name: str, data: dict[str, Any], result: Result) -> dict[str, Any]:
    return plain({
        "avertissement": BANNER,
        "scenario": name,
        "description": data.get("description"),
        "hypotheses": {
            "marches": data["markets"],
            "parametres": data["params"],
            "inventaire_initial": data["inventory"],
            "note": "frais, latences, minimums et coût de rééquilibrage sont des HYPOTHÈSES de "
                    "scénario, pas des tarifs ni des performances vérifiés",
        },
        "resultat": result,
    })


def markdown(reports: list[dict[str, Any]]) -> str:
    lines = [f"# {BANNER}", "",
             "Carnets, frais, latences et soldes sont synthétiques. Aucun ordre réel, aucun "
             "compte, aucun réseau. Ce rapport illustre des mécanismes, pas une stratégie.", "",
             "| Scénario | Statut | Sens | Écart brut/unité | Qté | Brut | Frais | Rééquil. | Net planifié | P&L réalisé | Exposition |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for rep in reports:
        r = rep["resultat"]
        lines.append("| " + " | ".join(_c(x) for x in (
            rep["scenario"], r["status"], r["direction"], r["gross_spread_unit"], r["planned_qty"],
            r["planned_gross"], r["planned_fees"], r["planned_rebalance"], r["planned_net"],
            r["realized_pnl"], r["open_exposure_base"])) + " |")
    lines += ["", "## Motifs et remarques", ""]
    for rep in reports:
        r = rep["resultat"]
        lines.append(f"### {rep['scenario']}")
        if rep.get("description"):
            lines.append(f"_{rep['description']}_")
        for reason in r["reasons"] or ["aucun refus"]:
            lines.append(f"- {reason}")
        for note in r["notes"]:
            lines.append(f"- note : {note}")
        if r["exposure_note"]:
            lines.append(f"- **{r['exposure_note']}**")
        if r["checks"]:
            lines.append("- contrôles : " + ", ".join(f"{k}={v}" for k, v in r["checks"].items()))
        lines.append("")
    lines.append(f"> {BANNER}")
    return "\n".join(lines) + "\n"


def _c(value: Any) -> str:
    return "—" if value is None else str(value).replace("|", "/")
