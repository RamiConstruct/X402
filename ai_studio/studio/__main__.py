"""Ligne de commande.

  python -m studio serve [--host 127.0.0.1] [--port 8000]
  python -m studio grant --email x@y.z --credits 500      (administration : crédits offerts)
  python -m studio engines                                  (état des moteurs)
  python -m studio report                                   (coûts, revenus, marges par moteur)
  python -m studio check-ledger                             (vérifie les invariants du grand livre)
"""
from __future__ import annotations

import argparse
import time

from sqlalchemy import func, select

from . import ledger
from .config import Settings
from .service import Studio


def main() -> None:
    ap = argparse.ArgumentParser(prog="studio")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sv = sub.add_parser("serve")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    g = sub.add_parser("grant")
    g.add_argument("--email", required=True)
    g.add_argument("--credits", type=int, required=True)
    sub.add_parser("engines")
    sub.add_parser("report")
    sub.add_parser("check-ledger")
    args = ap.parse_args()
    settings = Settings()

    if args.cmd == "serve":
        import uvicorn
        from .api import create_app
        uvicorn.run(create_app(settings), host=args.host, port=args.port)
        return

    studio = Studio(settings)
    if args.cmd == "grant":
        from .auth import find_user
        with studio.db.session() as s:
            user = find_user(s, args.email)
            if not user:
                raise SystemExit("utilisateur introuvable")
            ledger.grant(s, user.id, args.credits, key=f"admin:{user.id}:{time.time_ns()}", memo="crédits administrateur")
            print(f"{args.credits} crédits ajoutés ; solde = {ledger.balance(s, ledger.available(user.id))}")
    elif args.cmd == "engines":
        for e in studio.registry.describe(settings):
            state = "OK" if e["available"] else f"indisponible ({e['unavailable_reason']})"
            print(f"{e['id']:<18} {state:<70} {e['pricing']['usd_per_unit']} USD/{e['pricing']['unit']}  vérifié: {e['pricing']['verified_on']}")
    elif args.cmd == "report":
        from .models import Job, ProviderCall
        with studio.db.session() as s:
            rows = s.execute(select(ProviderCall.engine_id, ProviderCall.status, func.count(),
                                    func.sum(ProviderCall.estimated_cost_micro), func.sum(ProviderCall.actual_cost_micro))
                             .group_by(ProviderCall.engine_id, ProviderCall.status)).all()
            print("moteur             statut     appels  coût estimé µUSD  coût réel µUSD")
            for r in rows:
                print(f"{r[0]:<18} {r[1]:<10} {r[2]:>6}  {r[3] or 0:>16}  {r[4] or 0:>14}")
            jobs = s.execute(select(Job.status, func.count(), func.sum(Job.charged_credits), func.sum(Job.actual_cost_micro))
                             .group_by(Job.status)).all()
            print("\ntâches : statut / nombre / crédits facturés / coût réel µUSD")
            for r in jobs:
                print(f"  {r[0]:<10} {r[1]:>5} {r[2] or 0:>8} {r[3] or 0:>12}")
            print(f"\nrevenu cumulé (crédits) : {ledger.balance(s, ledger.REVENUE)}")
    elif args.cmd == "check-ledger":
        with studio.db.session() as s:
            ledger.check_invariants(s)
        print("grand livre cohérent")


if __name__ == "__main__":
    main()
