"""Cycle de vie d'un GPU loué : devis → location → préparation → utilisation → libération.

Garde-fous (une facture qui court sans toi est le risque n°1) :
* une seule location à la fois (mode propriétaire) ;
* prix horaire maximal ;
* libération automatique après N minutes sans session active, et durée de vie maximale ;
* état enregistré sur disque : après un redémarrage, les locations en cours sont
  retrouvées et libérées si nécessaire (pas de machine orpheline facturée).
"""
from __future__ import annotations

import json
import secrets
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import httpx

from .catalog import MODELS, LiveModel
from .providers import Offer, Provider, ProviderError


class GpuError(RuntimeError):
    pass


@dataclass
class Rental:
    id: str
    provider: str
    instance_id: str
    offer_key: str
    gpu_name: str
    location: str
    model_key: str
    usd_per_hour: float
    markup: float
    token: str
    started_at: float
    state: str = "starting"          # starting → booting → warming → ready → released / failed
    detail: str = ""
    endpoint: str | None = None
    last_active: float = field(default_factory=time.time)
    released_at: float | None = None
    release_reason: str | None = None

    def hours(self, now: float | None = None) -> float:
        return (((self.released_at or now or time.time()) - self.started_at) / 3600)

    def cost_usd(self, now: float | None = None) -> float:
        return round(self.hours(now) * self.usd_per_hour, 4)

    def client_price_per_min(self) -> float:
        return round(self.usd_per_hour / 60 * self.markup, 4)


@dataclass
class Limits:
    max_usd_per_hour: float = 1.5
    idle_minutes: float = 10
    max_hours: float = 4
    owner_mode: bool = True          # toi : marge 1 (tu paies le prix coûtant)


class GpuManager:
    def __init__(self, providers: dict[str, Provider], store: Path, image: str, limits: Limits | None = None,
                 worker_env: dict[str, str] | Callable[[], dict[str, str]] | None = None, http: httpx.Client | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        self.providers, self.store, self.image = providers, store, image
        self.limits = limits or Limits()
        self.worker_env = worker_env or {}
        self.http = http or httpx.Client(timeout=5)
        self.clock = clock
        self.lock = threading.RLock()
        self.rental: Rental | None = None
        self.history: list[dict] = []
        self._offers: dict[str, Offer] = {}
        self._load()

    # ---------------------------------------------------------------- persistance
    def _load(self) -> None:
        if self.store.exists():
            data = json.loads(self.store.read_text(encoding="utf-8"))
            if data.get("rental"):
                self.rental = Rental(**data["rental"])
            self.history = data.get("history", [])

    def _save(self) -> None:
        self.store.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.store.with_suffix(".tmp")
        tmp.write_text(json.dumps({"rental": asdict(self.rental) if self.rental else None,
                                   "history": self.history[-200:]}, indent=2), encoding="utf-8")
        tmp.replace(self.store)

    # ---------------------------------------------------------------- devis
    def quote(self, model_key: str, limit_per_provider: int = 6) -> dict:
        model = self._model(model_key)
        offers, errors = [], []
        for name, p in self.providers.items():
            try:
                offers += p.search(model.min_vram_gb, self.limits.max_usd_per_hour, limit_per_provider)
            except (ProviderError, httpx.HTTPError) as e:
                errors.append({"provider": name, "error": str(e)[:300]})
        offers.sort(key=lambda o: o.usd_per_hour)
        markup = 1.0 if self.limits.owner_mode else model.markup
        self._offers = {o.key: o for o in offers}
        return {"model": asdict(model), "markup": markup, "errors": errors,
                "offers": [{"key": o.key, "provider": o.provider, "gpu": o.gpu_name, "vram_gb": o.vram_gb,
                            "location": o.location, "reliability": o.reliability, "usd_per_hour": o.usd_per_hour,
                            "price_per_min": round(o.usd_per_hour / 60 * markup, 4)} for o in offers]}

    def _model(self, key: str) -> LiveModel:
        if key not in MODELS:
            raise GpuError("modèle inconnu")
        return MODELS[key]

    # ---------------------------------------------------------------- location
    def rent(self, offer_key: str, model_key: str) -> Rental:
        with self.lock:
            if self.rental and self.rental.state not in ("released", "failed"):
                raise GpuError("un GPU est déjà loué : libère-le d'abord")
            offer = self._offers.get(offer_key)
            if offer is None:
                raise GpuError("offre expirée : redemande un devis")
            if offer.usd_per_hour > self.limits.max_usd_per_hour:
                raise GpuError("offre au-dessus du prix horaire maximal")
            model = self._model(model_key)
            token = secrets.token_urlsafe(24)  # jeton propre à cette machine
            extra = self.worker_env() if callable(self.worker_env) else self.worker_env
            env = {**extra, "WORKER_TOKEN": token, "WORKER_PROCESSOR": "streamdiffusion",
                   "WORKER_WARMUP_PARAMS": json.dumps({"model_id": model.model_id, "width": model.width,
                                                       "height": model.height, "prompt": "a person",
                                                       "t_index_list": [14]})}
            try:
                iid = self.providers[offer.provider].launch(offer, self.image, env, label="ai-live")
            except (ProviderError, httpx.HTTPError) as e:
                raise GpuError(f"location impossible : {e}") from e
            self.rental = Rental(id="gpu_" + secrets.token_hex(6), provider=offer.provider, instance_id=iid,
                                 offer_key=offer.key, gpu_name=offer.gpu_name, location=offer.location,
                                 model_key=model.key, usd_per_hour=offer.usd_per_hour,
                                 markup=1.0 if self.limits.owner_mode else model.markup, token=token,
                                 started_at=self.clock(), last_active=self.clock())
            self._save()
            return self.rental

    def refresh(self) -> Rental | None:
        """Interroge le fournisseur puis le worker ; applique les garde-fous."""
        with self.lock:
            r = self.rental
            if r is None or r.state in ("released", "failed"):
                return r
            now = self.clock()
            if r.state != "ready" and r.hours(now) * 60 > 30:
                self.release("la machine n'a pas démarré en 30 minutes")
                return self.rental
            if r.state != "ready":
                try:
                    st = self.providers[r.provider].status(r.instance_id)
                except (ProviderError, httpx.HTTPError) as e:
                    r.detail = f"état indisponible : {e}"
                    self._save()
                    return r
                r.detail = st.detail
                if st.usd_per_hour:
                    r.usd_per_hour = float(st.usd_per_hour)
                if st.running and st.endpoint:
                    r.endpoint, r.state = st.endpoint, "warming"
                    try:
                        h = self.http.get(f"{st.endpoint}/health", timeout=5).json()
                        if h.get("ready"):
                            r.state, r.last_active = "ready", now
                        else:
                            r.detail = h.get("warmup", "préparation du modèle")
                    except (httpx.HTTPError, ValueError):
                        r.detail = "démarrage du worker (téléchargement de l'image, compilation)"
                else:
                    r.state = "booting"
            self.reap(now)
            self._save()
            return self.rental

    def touch(self) -> None:
        with self.lock:
            if self.rental:
                self.rental.last_active = self.clock()

    def reap(self, now: float | None = None) -> None:
        r = self.rental
        if r is None or r.state in ("released", "failed"):
            return
        now = now or self.clock()
        if r.hours(now) > self.limits.max_hours:
            self.release(f"durée maximale atteinte ({self.limits.max_hours} h)")
        elif r.state == "ready" and (now - r.last_active) / 60 > self.limits.idle_minutes:
            self.release(f"inactif depuis {self.limits.idle_minutes:.0f} min")

    def release(self, reason: str = "libéré par l'utilisateur") -> Rental | None:
        with self.lock:
            r = self.rental
            if r is None or r.state in ("released", "failed"):
                return r
            try:
                self.providers[r.provider].destroy(r.instance_id)
            except (ProviderError, httpx.HTTPError) as e:
                r.detail = f"⚠ arrêt non confirmé — vérifie sur le site du fournisseur : {e}"
                self._save()
                raise GpuError(r.detail) from e
            r.state, r.released_at, r.release_reason = "released", self.clock(), reason
            self.history.append({"provider": r.provider, "gpu": r.gpu_name, "model": r.model_key,
                                 "hours": round(r.hours(), 4), "cost_usd": r.cost_usd(), "reason": reason})
            self._save()
            return r

    def view(self) -> dict | None:
        r = self.rental
        if r is None:
            return None
        d = asdict(r)
        d.pop("token")
        d.update(cost_usd=r.cost_usd(self.clock()), minutes=round(r.hours(self.clock()) * 60, 1),
                 price_per_min=r.client_price_per_min(), idle_minutes_limit=self.limits.idle_minutes)
        return d
