"""Flotte de GPU automatique : des centaines d'utilisateurs simultanés, sans Daydream.

Principe :
* chaque GPU loué (« nœud ») accueille quelques utilisateurs (places par gamme : Standard 3, Ultra 1…) ;
* un nouvel utilisateur va sur le nœud prêt le plus rempli qui a une place (on remplit avant d'étaler,
  pour pouvoir rendre les nœuds vides) ;
* s'il n'y a plus de place, un nœud est loué automatiquement ; on garde toujours un nœud d'avance par
  gamme, car un GPU met 1 à 3 minutes à démarrer ;
* les nœuds vides au-delà de cette réserve sont rendus après quelques minutes ;
* garde-fous : plafond de dépense horaire TOTAL, nombre maximal de nœuds, délai de démarrage, et état
  enregistré sur disque (après un redémarrage, aucune machine n'est oubliée en train de facturer).

La gamme « Ultra » vise les grosses cartes (H100…) pour l'objectif 1440p / 90 i/s ; « Standard » les RTX
4090/5090. Les places par GPU sont des ESTIMATIONS à remplacer par les mesures du banc d'essai.
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

from .catalog import MODELS
from .providers import Offer, Provider, ProviderError


@dataclass(frozen=True)
class Tier:
    key: str
    label: str
    model_key: str
    min_vram_gb: int
    slots: int                 # utilisateurs simultanés par GPU [HYP : à mesurer]
    max_usd_per_hour: float    # prix maximal d'un GPU de cette gamme


TIERS: dict[str, Tier] = {t.key: t for t in [
    Tier("standard", "Standard — RTX 4090/5090", "sd-turbo", 24, 3, 1.0),
    Tier("qualite", "Qualité — 24 Go et plus", "sdxl-turbo", 24, 2, 1.2),
    Tier("ultra", "Ultra — H100 / grosses cartes", "sdxl-turbo", 80, 1, 4.0),
]}


@dataclass
class FleetLimits:
    max_usd_per_hour: float = 20.0   # plafond TOTAL de la flotte
    max_nodes: int = 10
    spare_nodes: int = 1             # nœuds d'avance par gamme utilisée récemment
    idle_minutes: float = 5          # un nœud vide au-delà de la réserve est rendu après ce délai
    boot_minutes: float = 30         # un nœud qui n'est pas prêt après ce délai est rendu
    demand_minutes: float = 30       # une gamme demandée récemment garde sa réserve pendant ce délai
    wait_minutes: float = 10         # un utilisateur en attente qui ne revient pas est oublié après ce délai
    regions: tuple[str, ...] = ()    # préférences de lieu (ex. « Singapore », « SG », « Japan »), dans l'ordre


@dataclass
class Node:
    id: str
    tier: str
    provider: str
    instance_id: str
    gpu_name: str
    location: str
    usd_per_hour: float
    token: str
    started_at: float
    state: str = "starting"          # starting → booting → warming → ready → released / failed
    endpoint: str | None = None
    detail: str = ""
    sessions: list[str] = field(default_factory=list)
    empty_since: float | None = None
    released_at: float | None = None
    release_reason: str | None = None

    @property
    def active(self) -> bool:
        return self.state not in ("released", "failed")

    def cost_usd(self, now: float) -> float:
        return round(((self.released_at or now) - self.started_at) / 3600 * self.usd_per_hour, 4)


class FleetError(RuntimeError):
    pass


def region_rank(location: str, regions: tuple[str, ...]) -> int:
    """0 = lieu préféré n°1 ; len(regions) = aucun lieu préféré trouvé."""
    loc = (location or "").lower()
    for i, r in enumerate(regions):
        if r.lower() in loc:
            return i
    return len(regions)


class GpuFleet:
    def __init__(self, providers: dict[str, Provider], store: Path, image: str, limits: FleetLimits | None = None,
                 tiers: dict[str, Tier] | None = None,
                 worker_env: dict[str, str] | Callable[[], dict[str, str]] | None = None,
                 http: httpx.Client | None = None, clock: Callable[[], float] = time.time) -> None:
        self.providers, self.store, self.image = providers, store, image
        self.limits = limits or FleetLimits()
        self.tiers = tiers or TIERS
        self.worker_env = worker_env or {}
        self.http = http or httpx.Client(timeout=5)
        self.clock = clock
        self.lock = threading.RLock()
        self.nodes: dict[str, Node] = {}
        self.waiting: dict[str, dict[str, float]] = {}   # gamme → {session : heure d'arrivée} en attente
        self.last_demand: dict[str, float] = {}
        self.history: list[dict] = []
        self.events: list[str] = []
        self._load()

    # ---------------------------------------------------------------- persistance
    def _load(self) -> None:
        if self.store.exists():
            d = json.loads(self.store.read_text(encoding="utf-8"))
            self.nodes = {n["id"]: Node(**n) for n in d.get("nodes", [])}
            self.history = d.get("history", [])
            self.last_demand = d.get("last_demand", {})

    def _save(self) -> None:
        self.store.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.store.with_suffix(".tmp")
        active = [asdict(n) for n in self.nodes.values() if n.active]
        tmp.write_text(json.dumps({"nodes": active, "history": self.history[-500:], "last_demand": self.last_demand},
                                  indent=2), encoding="utf-8")
        tmp.replace(self.store)

    def _event(self, msg: str) -> None:
        self.events.append(time.strftime("%H:%M:%S ") + msg)
        del self.events[:-100]

    # ---------------------------------------------------------------- places
    def tier(self, key: str) -> Tier:
        if key not in self.tiers:
            raise FleetError("gamme inconnue")
        return self.tiers[key]

    def assign(self, session_id: str, tier_key: str) -> Node | None:
        """Place l'utilisateur sur un GPU prêt. None = aucune place libre : un GPU est en préparation."""
        t = self.tier(tier_key)
        with self.lock:
            self.last_demand[t.key] = self.clock()
            free = [n for n in self.nodes.values()
                    if n.tier == t.key and n.state == "ready" and len(n.sessions) < t.slots]
            if not free:
                self.waiting.setdefault(t.key, {}).setdefault(session_id, self.clock())
                self._scale(t)
                self._save()
                return None
            node = max(free, key=lambda n: (len(n.sessions), -n.usd_per_hour))   # remplir avant d'étaler
            node.sessions.append(session_id)
            node.empty_since = None
            self.waiting.get(t.key, {}).pop(session_id, None)
            self._scale(t)                      # garder la réserve après cette arrivée
            self._save()
            return node

    def release_session(self, session_id: str) -> None:
        with self.lock:
            for w in self.waiting.values():
                w.pop(session_id, None)
            for n in self.nodes.values():
                if session_id in n.sessions:
                    n.sessions.remove(session_id)
                    if not n.sessions:
                        n.empty_since = self.clock()
            self._save()

    def node_of(self, session_id: str) -> Node | None:
        return next((n for n in self.nodes.values() if session_id in n.sessions), None)

    # ---------------------------------------------------------------- montée / descente en charge
    def cost_per_hour(self) -> float:
        return round(sum(n.usd_per_hour for n in self.nodes.values() if n.active), 4)

    def _free_capacity(self, t: Tier) -> tuple[int, int]:
        """(places libres sur les nœuds prêts, places à venir sur les nœuds en démarrage)."""
        ready = sum(t.slots - len(n.sessions) for n in self.nodes.values() if n.tier == t.key and n.state == "ready")
        coming = sum(t.slots for n in self.nodes.values()
                     if n.tier == t.key and n.state in ("starting", "booting", "warming"))
        return ready, coming

    def _scale(self, t: Tier) -> None:
        recently = self.clock() - self.last_demand.get(t.key, -1e18) < self.limits.demand_minutes * 60
        want_free = len(self.waiting.get(t.key, {})) + (self.limits.spare_nodes * t.slots if recently else 0)
        ready, coming = self._free_capacity(t)
        missing = want_free - ready - coming
        while missing > 0:
            if not self._launch(t):
                break
            missing -= t.slots

    def _offers(self, t: Tier) -> list[Offer]:
        offers: list[Offer] = []
        for name, p in self.providers.items():
            try:
                offers += p.search(t.min_vram_gb, t.max_usd_per_hour, 8)
            except (ProviderError, httpx.HTTPError) as e:
                self._event(f"{name} : recherche impossible ({str(e)[:120]})")
        offers.sort(key=lambda o: (region_rank(o.location, self.limits.regions), o.usd_per_hour,
                                   -(o.reliability or 0)))
        return offers

    def _launch(self, t: Tier) -> bool:
        active = [n for n in self.nodes.values() if n.active]
        if len(active) >= self.limits.max_nodes:
            self._event(f"{t.label} : nombre maximal de GPU atteint ({self.limits.max_nodes})")
            return False
        budget = self.limits.max_usd_per_hour - self.cost_per_hour()
        for offer in self._offers(t):
            if offer.usd_per_hour > budget:
                continue
            model = MODELS[t.model_key]
            token = secrets.token_urlsafe(24)
            extra = self.worker_env() if callable(self.worker_env) else self.worker_env
            env = {**extra, "WORKER_TOKEN": token, "WORKER_PROCESSOR": "streamdiffusion",
                   "WORKER_WARMUP_PARAMS": json.dumps({"model_id": model.model_id, "width": model.width,
                                                       "height": model.height, "prompt": "a person",
                                                       "t_index_list": [14]})}
            try:
                iid = self.providers[offer.provider].launch(offer, self.image, env, label=f"ai-live-{t.key}")
            except (ProviderError, httpx.HTTPError) as e:
                self._event(f"{offer.provider} {offer.gpu_name} : location refusée ({str(e)[:120]})")
                continue
            n = Node(id="node_" + secrets.token_hex(5), tier=t.key, provider=offer.provider, instance_id=iid,
                     gpu_name=offer.gpu_name, location=offer.location, usd_per_hour=offer.usd_per_hour,
                     token=token, started_at=self.clock())
            self.nodes[n.id] = n
            self._event(f"location {n.id} : {offer.gpu_name} ({offer.location or offer.provider}) "
                        f"{offer.usd_per_hour:.2f} $/h pour {t.label}")
            return True
        self._event(f"{t.label} : aucune offre dans le budget (reste {budget:.2f} $/h)")
        return False

    def _release(self, n: Node, reason: str) -> None:
        try:
            self.providers[n.provider].destroy(n.instance_id)
        except (ProviderError, httpx.HTTPError) as e:
            n.detail = f"⚠ arrêt non confirmé — vérifier chez le fournisseur : {e}"
            self._event(f"{n.id} : {n.detail}")
            return                                   # on réessaiera au prochain passage
        now = self.clock()
        n.state, n.released_at, n.release_reason = "released", now, reason
        self.history.append({"node": n.id, "tier": n.tier, "gpu": n.gpu_name, "location": n.location,
                             "cost_usd": n.cost_usd(now), "reason": reason})
        self._event(f"rendu {n.id} ({n.gpu_name}) : {reason}")

    def _refresh_node(self, n: Node, now: float) -> None:
        if (now - n.started_at) / 60 > self.limits.boot_minutes:
            self._release(n, f"pas prêt après {self.limits.boot_minutes:.0f} min")
            return
        try:
            st = self.providers[n.provider].status(n.instance_id)
        except (ProviderError, httpx.HTTPError) as e:
            n.detail = f"état indisponible : {str(e)[:120]}"
            return
        n.detail = st.detail
        if st.usd_per_hour:
            n.usd_per_hour = float(st.usd_per_hour)
        if not (st.running and st.endpoint):
            n.state = "booting"
            return
        n.endpoint, n.state = st.endpoint, "warming"
        try:
            h = self.http.get(f"{st.endpoint}/health", timeout=5).json()
        except (httpx.HTTPError, ValueError):
            n.detail = "démarrage du programme IA"
            return
        if h.get("ready"):
            n.state, n.empty_since = "ready", now
            self._event(f"{n.id} prêt ({n.gpu_name})")
        else:
            n.detail = h.get("warmup", "préparation du modèle")

    def tick(self) -> None:
        """À appeler régulièrement (toutes les 15–30 s) : états, réserve, nœuds vides, garde-fous."""
        with self.lock:
            now = self.clock()
            for w in self.waiting.values():
                for sid in [k for k, t0 in w.items() if (now - t0) / 60 > self.limits.wait_minutes]:
                    del w[sid]
            for n in list(self.nodes.values()):
                if n.active and n.state != "ready":
                    self._refresh_node(n, now)
            # Nœuds vides au-delà de la réserve : rendus après idle_minutes (les plus chers d'abord).
            for t in self.tiers.values():
                recently = now - self.last_demand.get(t.key, -1e18) < self.limits.demand_minutes * 60
                keep = self.limits.spare_nodes if recently else 0
                empty = sorted((n for n in self.nodes.values() if n.tier == t.key and n.state == "ready"
                                and not n.sessions and n.empty_since is not None),
                               key=lambda n: -n.usd_per_hour)
                for n in empty[keep:] if len(empty) > keep else []:
                    if (now - n.empty_since) / 60 >= self.limits.idle_minutes:
                        self._release(n, f"vide depuis {self.limits.idle_minutes:.0f} min")
                self._scale(t)
            # Plafond dépassé (prix réels plus hauts que prévus) : rendre des nœuds vides.
            for n in sorted((n for n in self.nodes.values() if n.active and not n.sessions), key=lambda n: -n.usd_per_hour):
                if self.cost_per_hour() <= self.limits.max_usd_per_hour:
                    break
                self._release(n, "plafond de dépense horaire")
            self.nodes = {k: n for k, n in self.nodes.items() if n.active}
            self._save()

    def shutdown(self, reason: str = "arrêt de la flotte") -> None:
        with self.lock:
            for n in list(self.nodes.values()):
                if n.active:
                    self._release(n, reason)
            self.nodes = {k: n for k, n in self.nodes.items() if n.active}
            self._save()

    # ---------------------------------------------------------------- affichage
    def view(self) -> dict:
        now = self.clock()
        with self.lock:
            nodes = [{k: v for k, v in asdict(n).items() if k != "token"} | {
                "cost_usd": n.cost_usd(now), "users": len(n.sessions), "slots": self.tiers[n.tier].slots}
                for n in self.nodes.values() if n.active]
            return {"nodes": nodes, "usd_per_hour": self.cost_per_hour(),
                    "limits": asdict(self.limits), "waiting": {k: len(v) for k, v in self.waiting.items()},
                    "tiers": [asdict(t) for t in self.tiers.values()],
                    "spent_usd": round(sum(h["cost_usd"] for h in self.history) + sum(n["cost_usd"] for n in nodes), 4),
                    "events": self.events[-20:]}
