"""CLI de l'atelier. Hors ligne par défaut ; aucun paiement possible."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .costs import BudgetPolicy, CostEstimate, CostGuard
from .discovery import DiscoveryResult, FixtureDiscovery, HttpPolicy, PublicHttpDiscovery
from .discovery.fixtures import DEFAULT_FIXTURE
from .normalize import normalize_currency, normalize_unit
from .providers import default_registry
from .redact import install_log_redaction
from .report import compare, summary_markdown, write_outputs
from .x402 import load_scenarios, simulate
from .x402.flow import DEFAULT_SCENARIOS

# Bornes dures : les options CLI ne peuvent pas les dépasser.
MAX_TIMEOUT_S = 15.0
MAX_RESPONSE_BYTES = 1_000_000
MAX_PAGES = 5
MAX_SOURCES = 5


def _collect(args: argparse.Namespace) -> DiscoveryResult:
    result = FixtureDiscovery(args.fixture).discover()
    if args.enable_http:
        policy = HttpPolicy(
            allowed_hosts=frozenset(h.lower() for h in args.allow_host),
            max_sources=MAX_SOURCES,
            timeout_s=min(args.http_timeout, MAX_TIMEOUT_S),
            max_response_bytes=min(args.http_max_bytes, MAX_RESPONSE_BYTES),
            max_pages=max(1, min(args.http_max_pages, MAX_PAGES)),
        )
        http = PublicHttpDiscovery(sources=args.http_source, policy=policy, enabled=True)
        extra = http.discover()
        result.records += extra.records
        result.payment_required += extra.payment_required
        result.errors += extra.errors
    elif args.http_source:
        result.errors.append("sources HTTP ignorées: découverte HTTP désactivée (--enable-http)")
    return result


def cmd_discover(args: argparse.Namespace) -> int:
    result = _collect(args)
    json_path, md_path = write_outputs(result, Path(args.out))
    print(summary_markdown(result))
    print(f"Écrit: {json_path}\nÉcrit: {md_path}")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    print(json.dumps(compare(_collect(args).records), ensure_ascii=False, indent=2))
    return 0


def cmd_providers(_args: argparse.Namespace) -> int:
    for p in default_registry():
        state = "actif" if p.enabled else "désactivé"
        api = "oui" if p.has_api_access else "non"
        cats = ",".join(sorted(c.value for c in p.categories))
        print(f"{p.name:24} {state:10} accès={p.access_kind.value:16} api={api:3} [{cats}]")
    return 0


def cmd_simulate(args: argparse.Namespace) -> int:
    data = load_scenarios(args.scenarios)
    names = list(data["scenarios"]) if args.all else [args.scenario]
    reports = [simulate(name, data).to_dict() for name in names]
    text = json.dumps(reports if args.all else reports[0], ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    print("\nSIMULATION HORS LIGNE — aucun paiement, aucune transaction, rentabilité non évaluée.",
          file=sys.stderr)
    return 0


def cmd_check_cost(args: argparse.Namespace) -> int:
    def dec(value: str | None) -> Decimal | None:
        try:
            return None if value is None else Decimal(value)
        except InvalidOperation:
            return None

    estimate = CostEstimate(
        billable=True, amount=dec(args.price),
        currency=normalize_currency(args.currency, None, []),
        unit=normalize_unit(args.unit), quantity=dec(args.quantity),
    )
    guard = CostGuard(BudgetPolicy(session_cap=dec(args.session_cap),
                                   per_call_cap=dec(args.per_call_cap),
                                   currency=args.budget_currency))
    decision = guard.authorize(estimate)
    print(json.dumps({"autorise": decision.allowed, "raisons": list(decision.reasons)},
                     ensure_ascii=False, indent=2))
    return 0 if not decision.allowed else 1  # une autorisation serait une anomalie dans ce lot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="atelier_x402", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def discovery_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
        p.add_argument("--enable-http", action="store_true",
                       help="active la découverte HTTP publique (désactivée par défaut)")
        p.add_argument("--http-source", action="append", default=[], metavar="URL")
        p.add_argument("--allow-host", action="append", default=[], metavar="HÔTE")
        p.add_argument("--http-timeout", type=float, default=5.0)
        p.add_argument("--http-max-bytes", type=int, default=256_000)
        p.add_argument("--http-max-pages", type=int, default=3)

    p = sub.add_parser("discover", help="collecte, normalise et exporte JSON + synthèse")
    discovery_args(p)
    p.add_argument("--out", default="sorties")
    p.set_defaults(func=cmd_discover)

    p = sub.add_parser("compare", help="compare les prix (même devise et unité)")
    discovery_args(p)
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("providers", help="liste les fournisseurs IA et leur état")
    p.set_defaults(func=cmd_providers)

    p = sub.add_parser("simulate-x402", help="simulation hors ligne du parcours x402")
    p.add_argument("--scenarios", default=str(DEFAULT_SCENARIOS))
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--scenario")
    group.add_argument("--all", action="store_true")
    p.add_argument("--out")
    p.set_defaults(func=cmd_simulate)

    p = sub.add_parser("check-cost", help="évalue un coût avec CostGuard (toujours refusé ici)")
    p.add_argument("--price")
    p.add_argument("--currency")
    p.add_argument("--unit")
    p.add_argument("--quantity", default="1")
    p.add_argument("--per-call-cap")
    p.add_argument("--session-cap", default="17")
    p.add_argument("--budget-currency", default=None,
                   help="devise du budget (non confirmée par défaut)")
    p.set_defaults(func=cmd_check_cost)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    install_log_redaction()
    args = build_parser().parse_args(argv)
    return args.func(args)
