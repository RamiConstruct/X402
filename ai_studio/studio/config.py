"""Configuration lue depuis l'environnement (préfixe STUDIO_).

Principe de prudence : aucun fournisseur payant n'est appelé tant que
STUDIO_ALLOW_PAID_PROVIDERS n'est pas explicitement à "true" ET que la clé
du fournisseur n'est pas définie.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    v = os.environ.get(name)
    return int(v) if v not in (None, "") else default


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("STUDIO_DATA_DIR", ROOT / "data")))
    database_url: str = ""
    engines_dir: Path = field(default_factory=lambda: Path(os.environ.get("STUDIO_ENGINES_DIR", ROOT / "engines")))
    secret_key: str = field(default_factory=lambda: os.environ.get("STUDIO_SECRET_KEY", ""))
    public_base_url: str = field(default_factory=lambda: os.environ.get("STUDIO_PUBLIC_BASE_URL", "").rstrip("/"))
    allow_paid_providers: bool = field(default_factory=lambda: _bool("STUDIO_ALLOW_PAID_PROVIDERS", False))
    dev_mode: bool = field(default_factory=lambda: _bool("STUDIO_DEV_MODE", True))
    signup_credits: int = field(default_factory=lambda: _int("STUDIO_SIGNUP_CREDITS", 100))
    max_upload_mb: int = field(default_factory=lambda: _int("STUDIO_MAX_UPLOAD_MB", 200))
    max_duration_s: int = field(default_factory=lambda: _int("STUDIO_MAX_DURATION_S", 60))
    max_job_credits: int = field(default_factory=lambda: _int("STUDIO_MAX_JOB_CREDITS", 3000))
    daily_credit_cap: int = field(default_factory=lambda: _int("STUDIO_DAILY_CREDIT_CAP", 10000))
    quote_ttl_s: int = field(default_factory=lambda: _int("STUDIO_QUOTE_TTL_S", 600))
    run_worker: bool = field(default_factory=lambda: _bool("STUDIO_RUN_WORKER", True))
    runway_api_key: str = field(default_factory=lambda: os.environ.get("RUNWAYML_API_SECRET", ""))
    fal_api_key: str = field(default_factory=lambda: os.environ.get("FAL_KEY", ""))

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)
        self.engines_dir = Path(self.engines_dir)
        if not self.database_url:
            self.database_url = os.environ.get("STUDIO_DATABASE_URL", f"sqlite:///{self.data_dir / 'studio.db'}")
        if not self.secret_key:
            if not self.dev_mode:
                raise RuntimeError("STUDIO_SECRET_KEY est obligatoire hors mode développement")
            self.secret_key = secrets.token_hex(32)

    @property
    def storage_dir(self) -> Path:
        return self.data_dir / "files"

    def provider_key(self, provider: str) -> str:
        return {"runway": self.runway_api_key, "fal": self.fal_api_key}.get(provider, "")
