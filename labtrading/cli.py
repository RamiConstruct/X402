"""CLI du laboratoire : rejoue des scénarios synthétiques, hors ligne."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import BANNER
from .report import SCENARIOS_DIR, ScenarioError, load_scenario, markdown, run_scenario, scenario_report


def _paths(args: argparse.Namespace) -> list[Path]:
    if args.all:
        return sorted(SCENARIOS_DIR.glob("scenario_*.json"))
    path = Path(args.scenario)
    if not path.exists():
        path = SCENARIOS_DIR / f"scenario_{args.scenario}.json"
    return [path]


def cmd_run(args: argparse.Namespace) -> int:
    reports = []
    for path in _paths(args):
        data = load_scenario(path)
        name = path.stem.removeprefix("scenario_")
        reports.append(scenario_report(name, data, run_scenario(data)))
    text = json.dumps(reports if args.all else reports[0], ensure_ascii=False, indent=2)
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "laboratoire.json").write_text(text + "\n", encoding="utf-8")
        (out / "laboratoire.md").write_text(markdown(reports), encoding="utf-8")
    print(text if args.json else markdown(reports))
    print(BANNER, file=sys.stderr)
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    for path in sorted(SCENARIOS_DIR.glob("scenario_*.json")):
        data = load_scenario(path)
        print(f"{path.stem.removeprefix('scenario_'):28} {data.get('description', '')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="labtrading", description=f"{BANNER}. {__doc__}")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("run", help="rejoue un scénario (ou tous)")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--scenario", help="nom (ex. net_positif_complet) ou chemin")
    group.add_argument("--all", action="store_true")
    p.add_argument("--json", action="store_true", help="sortie JSON au lieu de Markdown")
    p.add_argument("--out", help="dossier où écrire laboratoire.json et laboratoire.md")
    p.set_defaults(func=cmd_run)
    p = sub.add_parser("list", help="liste les scénarios")
    p.set_defaults(func=cmd_list)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ScenarioError, ValueError, KeyError, OSError) as exc:
        print(f"erreur: {exc}", file=sys.stderr)
        return 2
