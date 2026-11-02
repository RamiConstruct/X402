"""Grand livre en partie double, en crédits entiers.

Comptes :
  user:<id>:available   crédits utilisables
  user:<id>:held        crédits réservés pour des jobs en cours
  platform:revenue      crédits consommés (chiffre d'affaires)
  platform:grants       contrepartie des crédits offerts (solde négatif)
  platform:payments     contrepartie des crédits achetés (solde négatif)

Invariants :
  * chaque transaction a une clé d'idempotence unique : rejouer = aucun effet ;
  * la somme des écritures d'une transaction vaut 0 ;
  * un compte utilisateur ne passe jamais en négatif.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import LedgerAccount, LedgerEntry, LedgerTransaction

_LOCK = threading.RLock()  # SQLite : sérialise les mouvements. Postgres : SELECT … FOR UPDATE suffit.


class InsufficientCredits(Exception):
    pass


class LedgerError(Exception):
    pass


def available(uid: str) -> str:
    return f"user:{uid}:available"


def held(uid: str) -> str:
    return f"user:{uid}:held"


REVENUE = "platform:revenue"
GRANTS = "platform:grants"
PAYMENTS = "platform:payments"
_PLATFORM = {REVENUE, GRANTS, PAYMENTS}


def _account(s: Session, name: str) -> LedgerAccount:
    acc = s.execute(select(LedgerAccount).where(LedgerAccount.name == name).with_for_update()).scalar_one_or_none()
    if acc is None:
        acc = LedgerAccount(name=name, balance_credits=0)
        s.add(acc)
        s.flush()
    return acc


def balance(s: Session, name: str) -> int:
    acc = s.get(LedgerAccount, name)
    return acc.balance_credits if acc else 0


def post(s: Session, *, key: str, kind: str, entries: list[tuple[str, int]], user_id: str | None = None,
         job_id: str | None = None, memo: str = "") -> LedgerTransaction:
    """Enregistre une transaction équilibrée. Idempotent sur `key`."""
    if sum(a for _, a in entries) != 0:
        raise LedgerError("transaction déséquilibrée")
    if any(not isinstance(a, int) for _, a in entries):
        raise LedgerError("montants entiers uniquement")
    with _LOCK:
        existing = s.execute(select(LedgerTransaction).where(LedgerTransaction.idempotency_key == key)).scalar_one_or_none()
        if existing is not None:
            return existing
        txn = LedgerTransaction(idempotency_key=key, kind=kind, user_id=user_id, job_id=job_id, memo=memo)
        s.add(txn)
        s.flush()
        for name, amount in entries:
            if amount == 0:
                continue
            acc = _account(s, name)
            new_balance = acc.balance_credits + amount
            if new_balance < 0 and name not in _PLATFORM:
                raise InsufficientCredits(f"solde insuffisant sur {name}")
            acc.balance_credits = new_balance
            s.add(LedgerEntry(transaction_id=txn.id, account=name, amount_credits=amount))
        s.flush()
        return txn


def grant(s: Session, uid: str, credits: int, key: str, memo: str = "crédits offerts") -> None:
    post(s, key=key, kind="grant", user_id=uid, memo=memo, entries=[(available(uid), credits), (GRANTS, -credits)])


def topup(s: Session, uid: str, credits: int, key: str, memo: str = "achat de crédits") -> None:
    post(s, key=key, kind="topup", user_id=uid, memo=memo, entries=[(available(uid), credits), (PAYMENTS, -credits)])


def reserve(s: Session, uid: str, job_id: str, credits: int) -> None:
    post(s, key=f"reserve:{job_id}", kind="reserve", user_id=uid, job_id=job_id, memo="réservation",
         entries=[(available(uid), -credits), (held(uid), credits)])


def settle(s: Session, uid: str, job_id: str, reserved: int, charged: int) -> None:
    """Capture `charged` (≤ réservé) et libère le reste. Idempotent."""
    if not 0 <= charged <= reserved:
        raise LedgerError("capture hors des bornes de la réservation")
    post(s, key=f"settle:{job_id}", kind="capture" if charged else "release", user_id=uid, job_id=job_id,
         memo=f"capture {charged} / réservé {reserved}",
         entries=[(held(uid), -reserved), (REVENUE, charged), (available(uid), reserved - charged)])


def spent_last_24h(s: Session, uid: str) -> int:
    """Crédits réservés ou consommés sur 24 h glissantes (plafond journalier)."""
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    q = (select(func.coalesce(func.sum(LedgerEntry.amount_credits), 0))
         .join(LedgerTransaction, LedgerEntry.transaction_id == LedgerTransaction.id)
         .where(LedgerTransaction.kind == "reserve", LedgerEntry.account == held(uid),
                LedgerTransaction.created_at >= since))
    return int(s.execute(q).scalar_one())


def check_invariants(s: Session) -> None:
    """Vérifie que chaque transaction est équilibrée et que les soldes en cache sont exacts."""
    bad = s.execute(select(LedgerEntry.transaction_id).group_by(LedgerEntry.transaction_id)
                    .having(func.sum(LedgerEntry.amount_credits) != 0)).all()
    if bad:
        raise LedgerError(f"transactions déséquilibrées : {bad}")
    sums = dict(s.execute(select(LedgerEntry.account, func.sum(LedgerEntry.amount_credits))
                          .group_by(LedgerEntry.account)).all())
    for acc in s.execute(select(LedgerAccount)).scalars():
        if acc.balance_credits != int(sums.get(acc.name, 0)):
            raise LedgerError(f"solde incohérent pour {acc.name}")
