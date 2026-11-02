import pytest

from studio import ledger
from studio.money import micro_to_credits_ceil, usd_to_micro_exact
from studio.models import User


def test_conversions_explicit():
    assert usd_to_micro_exact("0.28") == 280_000
    with pytest.raises(ValueError):
        usd_to_micro_exact("0.0000001")
    assert micro_to_credits_ceil(0) == 0
    assert micro_to_credits_ceil(1) == 1          # arrondi au crédit supérieur
    assert micro_to_credits_ceil(10_000) == 1
    assert micro_to_credits_ceil(10_001) == 2


def _user(s, email="a@b.c"):
    u = User(email=email, password_hash="x")
    s.add(u)
    s.flush()
    return u


def test_reserve_settle_and_invariants(studio):
    with studio.db.session() as s:
        u = _user(s)
        ledger.grant(s, u.id, 100, key="g1")
        ledger.grant(s, u.id, 100, key="g1")  # idempotent
        assert ledger.balance(s, ledger.available(u.id)) == 100
        ledger.reserve(s, u.id, "job1", 60)
        assert ledger.balance(s, ledger.available(u.id)) == 40
        assert ledger.balance(s, ledger.held(u.id)) == 60
        ledger.settle(s, u.id, "job1", 60, 45)
        ledger.settle(s, u.id, "job1", 60, 45)  # idempotent
        assert ledger.balance(s, ledger.available(u.id)) == 55
        assert ledger.balance(s, ledger.held(u.id)) == 0
        assert ledger.balance(s, ledger.REVENUE) == 45
        ledger.check_invariants(s)


def test_no_negative_balance(studio):
    with studio.db.session() as s:
        u = _user(s)
        ledger.grant(s, u.id, 10, key="g")
        with pytest.raises(ledger.InsufficientCredits):
            ledger.reserve(s, u.id, "j", 11)


def test_capture_cannot_exceed_reservation(studio):
    with studio.db.session() as s:
        u = _user(s)
        ledger.grant(s, u.id, 10, key="g")
        ledger.reserve(s, u.id, "j", 5)
        with pytest.raises(ledger.LedgerError):
            ledger.settle(s, u.id, "j", 5, 6)


def test_unbalanced_rejected(studio):
    with studio.db.session() as s:
        with pytest.raises(ledger.LedgerError):
            ledger.post(s, key="k", kind="x", entries=[("a", 1)])
