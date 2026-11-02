"""Interface commune des adaptateurs de moteurs."""
from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import httpx

from ..engines import EngineSpec


class ProviderError(RuntimeError):
    """Échec côté moteur : le job est remboursé automatiquement."""


@dataclass
class StepContext:
    engine: EngineSpec
    capability: str
    input_path: Path
    output_path: Path
    prompt: str
    duration_s: float
    idempotency_key: str
    api_key: str = ""
    input_url: str | None = None          # URL signée publique si STUDIO_PUBLIC_BASE_URL est défini
    log: Callable[[str, dict], None] = lambda msg, data: None


@dataclass
class StepResult:
    actual_cost_micro: int
    external_id: str | None = None


class Adapter:
    def run(self, ctx: StepContext) -> StepResult:  # pragma: no cover - interface
        raise NotImplementedError


def input_reference(ctx: StepContext, max_data_uri_mb: float) -> str:
    """URL publique signée si disponible, sinon data URI (petits fichiers uniquement)."""
    if ctx.input_url:
        return ctx.input_url
    size_mb = ctx.input_path.stat().st_size / (1 << 20)
    if size_mb > max_data_uri_mb:
        raise ProviderError(f"segment de {size_mb:.1f} Mo trop lourd pour un data URI : définir STUDIO_PUBLIC_BASE_URL")
    return "data:video/mp4;base64," + base64.b64encode(ctx.input_path.read_bytes()).decode()


def download(url: str, dst: Path, timeout: float = 300) -> None:
    with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as r:
        if r.status_code != 200:
            raise ProviderError(f"téléchargement du résultat impossible (HTTP {r.status_code})")
        with dst.open("wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)


def poll(fn: Callable[[], tuple[bool, object]], timeout_s: float, interval_s: float = 5.0,
         sleep: Callable[[float], None] = time.sleep) -> object:
    """Appelle `fn` jusqu'à ce qu'il renvoie (True, résultat) ; lève ProviderError au délai."""
    deadline = time.monotonic() + timeout_s
    while True:
        done, value = fn()
        if done:
            return value
        if time.monotonic() > deadline:
            raise ProviderError("délai d'attente du fournisseur dépassé")
        sleep(interval_s)
