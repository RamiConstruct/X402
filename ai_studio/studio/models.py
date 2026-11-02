"""Schéma de données. Montants : entiers (µUSD ou crédits, précisé dans le nom)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, BigInteger, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("usr"))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    is_admin: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuthToken(Base):
    __tablename__ = "auth_tokens"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LedgerAccount(Base):
    """Compte du grand livre. Le solde est un cache maintenu dans la même transaction que les écritures."""
    __tablename__ = "ledger_accounts"
    name: Mapped[str] = mapped_column(String(128), primary_key=True)  # ex. user:usr_x:available
    balance_credits: Mapped[int] = mapped_column(BigInteger, default=0)


class LedgerTransaction(Base):
    __tablename__ = "ledger_transactions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("txn"))
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    kind: Mapped[str] = mapped_column(String(32))  # grant, topup, reserve, capture, release
    user_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    memo: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transaction_id: Mapped[str] = mapped_column(ForeignKey("ledger_transactions.id"), index=True)
    account: Mapped[str] = mapped_column(ForeignKey("ledger_accounts.name"), index=True)
    amount_credits: Mapped[int] = mapped_column(BigInteger)  # + crédit / − débit ; somme par transaction = 0


class Asset(Base):
    """Fichier vidéo immuable. Une modification produit un NOUVEL asset (version)."""
    __tablename__ = "assets"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("ast"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    root_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)  # projet = asset racine
    parent_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    duration_s: Mapped[float] = mapped_column(Float)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    fps: Mapped[float] = mapped_column(Float, default=0.0)
    label: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Quote(Base):
    __tablename__ = "quotes"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("quo"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"))
    prompt: Mapped[str] = mapped_column(Text)
    range_start_s: Mapped[float] = mapped_column(Float)
    range_end_s: Mapped[float] = mapped_column(Float)
    plan: Mapped[dict] = mapped_column(JSON)       # étapes planifiées
    options: Mapped[list] = mapped_column(JSON)    # options chiffrées (économique / qualité)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_option: Mapped[str | None] = mapped_column(String(32), nullable=True)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("job"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    quote_id: Mapped[str] = mapped_column(ForeignKey("quotes.id"), unique=True)
    option_id: Mapped[str] = mapped_column(String(32))
    input_asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"))
    output_asset_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), index=True)  # queued, running, succeeded, failed, canceled
    steps: Mapped[list] = mapped_column(JSON)
    reserved_credits: Mapped[int] = mapped_column(BigInteger)
    charged_credits: Mapped[int] = mapped_column(BigInteger, default=0)
    estimated_cost_micro: Mapped[int] = mapped_column(BigInteger)
    actual_cost_micro: Mapped[int] = mapped_column(BigInteger, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    simulated: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class JobEvent(Base):
    __tablename__ = "job_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    level: Mapped[str] = mapped_column(String(8))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ProviderCall(Base):
    """Journal de chaque appel moteur : coût estimé vs réel, durée, erreur."""
    __tablename__ = "provider_calls"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("pcl"))
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    step_index: Mapped[int] = mapped_column(Integer)
    engine_id: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(16))
    estimated_cost_micro: Mapped[int] = mapped_column(BigInteger)
    actual_cost_micro: Mapped[int] = mapped_column(BigInteger, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    cache_hit: Mapped[bool] = mapped_column(default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RenderCache(Base):
    """Cache non destructif : même entrée + même moteur + mêmes paramètres = même résultat."""
    __tablename__ = "render_cache"
    __table_args__ = (UniqueConstraint("cache_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cache_key: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
