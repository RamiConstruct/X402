"""Location de GPU à la demande : Vast.ai et RunPod.

Contrats repris des clients officiels :
* Vast.ai (`vast-ai/vast-cli`) — base https://console.vast.ai/api/v0, en-tête Authorization: Bearer
    POST   /bundles/                 recherche d'offres (filtres {"champ": {"gte": …}}, gpu_ram en Mo)
    PUT    /asks/{offer_id}/         création → {"success": true, "new_contract": <id instance>}
    GET    /instances/{id}/?owner=me → {"instances": {actual_status, public_ipaddr, ports{"8890/tcp": [{HostPort}]}, dph_total}}
    DELETE /instances/{id}/
* RunPod (`runpod/runpod-python`, API REST v2) — base https://api.runpod.io
    GET    /v2/catalog/gpus          {gpus: [{id, name, memory, price{secure, community}, availability}]}
    POST   /v2/pods                  {name, image, gpu{id, count}, cloud, ports ["8890/http"], env, disk}
    GET    /v2/pods/{id}             {status: "RUNNING", cost, …} ; URL publique https://{id}-8890.proxy.runpod.net
    DELETE /v2/pods/{id}

Aucun appel réel n'a été testé : clés absentes dans l'environnement de développement.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import httpx

WORKER_PORT = 8890


class ProviderError(RuntimeError):
    pass


@dataclass
class Offer:
    provider: str
    offer_id: str
    gpu_name: str
    vram_gb: float
    usd_per_hour: float
    location: str = ""
    reliability: float | None = None
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.offer_id}"


@dataclass
class InstanceStatus:
    running: bool
    endpoint: str | None
    detail: str
    usd_per_hour: float | None = None


class Provider:
    name = "?"

    def search(self, min_vram_gb: int, max_usd_per_hour: float, limit: int = 10) -> list[Offer]:
        raise NotImplementedError

    def launch(self, offer: Offer, image: str, env: dict[str, str], label: str) -> str:
        raise NotImplementedError

    def status(self, instance_id: str) -> InstanceStatus:
        raise NotImplementedError

    def destroy(self, instance_id: str) -> None:
        raise NotImplementedError


def _check(r: httpx.Response, what: str) -> dict:
    if r.status_code >= 400:
        raise ProviderError(f"{what} : HTTP {r.status_code} {r.text[:300]}")
    try:
        return r.json()
    except ValueError:
        return {}


class VastProvider(Provider):
    name = "vast"

    def __init__(self, api_key: str, client: httpx.Client | None = None, base: str = "https://console.vast.ai/api/v0") -> None:
        if not api_key:
            raise ProviderError("VAST_API_KEY manquante")
        self.base = base
        self.client = client or httpx.Client(timeout=30)
        self.h = {"Authorization": f"Bearer {api_key}"}

    def search(self, min_vram_gb: int, max_usd_per_hour: float, limit: int = 10) -> list[Offer]:
        q = {
            "verified": {"eq": True}, "external": {"eq": False}, "rentable": {"eq": True}, "rented": {"eq": False},
            "num_gpus": {"eq": 1}, "gpu_ram": {"gte": min_vram_gb * 1000}, "reliability": {"gte": 0.97},
            "inet_down": {"gte": 200}, "inet_up": {"gte": 100}, "direct_port_count": {"gte": 2},
            "cuda_max_good": {"gte": 12.4}, "dph_total": {"lte": max_usd_per_hour},
            "order": [["dph_total", "asc"]], "type": "on-demand", "limit": limit, "allocated_storage": 40,
        }
        data = _check(self.client.post(f"{self.base}/bundles/", json=q, headers=self.h), "recherche Vast.ai")
        return [Offer(provider=self.name, offer_id=str(o["id"]), gpu_name=o.get("gpu_name", "?"),
                      vram_gb=round(float(o.get("gpu_ram", 0)) / 1000, 1), usd_per_hour=float(o.get("dph_total", 0)),
                      location=o.get("geolocation") or "", reliability=o.get("reliability2", o.get("reliability")), raw=o)
                for o in data.get("offers", [])]

    def launch(self, offer: Offer, image: str, env: dict[str, str], label: str) -> str:
        body = {"client_id": "me", "image": image, "disk": 40, "label": label, "runtype": "args",
                "env": {f"-p {WORKER_PORT}:{WORKER_PORT}": "1", **env}}
        data = _check(self.client.put(f"{self.base}/asks/{offer.offer_id}/", json=body, headers=self.h), "location Vast.ai")
        if not data.get("success") or not data.get("new_contract"):
            raise ProviderError(f"location Vast.ai refusée : {data}")
        return str(data["new_contract"])

    def status(self, instance_id: str) -> InstanceStatus:
        data = _check(self.client.get(f"{self.base}/instances/{instance_id}/", params={"owner": "me"}, headers=self.h),
                      "état Vast.ai")
        inst = data.get("instances") or {}
        state = inst.get("actual_status") or "inconnu"
        mapping = (inst.get("ports") or {}).get(f"{WORKER_PORT}/tcp") or []
        endpoint = None
        if state == "running" and inst.get("public_ipaddr") and mapping:
            endpoint = f"http://{inst['public_ipaddr']}:{mapping[0]['HostPort']}"
        return InstanceStatus(running=endpoint is not None, endpoint=endpoint, detail=state,
                              usd_per_hour=inst.get("dph_total"))

    def destroy(self, instance_id: str) -> None:
        _check(self.client.request("DELETE", f"{self.base}/instances/{instance_id}/", json={}, headers=self.h),
               "arrêt Vast.ai")


class RunPodProvider(Provider):
    name = "runpod"

    def __init__(self, api_key: str, client: httpx.Client | None = None, base: str = "https://api.runpod.io",
                 cloud: str = "COMMUNITY") -> None:
        if not api_key:
            raise ProviderError("RUNPOD_API_KEY manquante")
        self.base, self.cloud = base, cloud
        self.client = client or httpx.Client(timeout=30)
        self.h = {"Authorization": f"Bearer {api_key}"}

    def search(self, min_vram_gb: int, max_usd_per_hour: float, limit: int = 10) -> list[Offer]:
        data = _check(self.client.get(f"{self.base}/v2/catalog/gpus", headers=self.h,
                                      params={"include": "AVAILABILITY", "product": "POD"}), "catalogue RunPod")
        price_key = "community" if self.cloud == "COMMUNITY" else "secure"
        offers = []
        for g in data.get("gpus", []):
            price = float((g.get("price") or {}).get(price_key) or 0)
            if (g.get("memory") or 0) < min_vram_gb or price <= 0 or price > max_usd_per_hour:
                continue
            if g.get("availability") in (None, "NONE"):
                continue
            offers.append(Offer(provider=self.name, offer_id=g["id"], gpu_name=g.get("name", g["id"]),
                                vram_gb=float(g["memory"]), usd_per_hour=price,
                                location=",".join(d["id"] for d in g.get("dataCenters", [])[:3]), raw=g))
        return sorted(offers, key=lambda o: o.usd_per_hour)[:limit]

    def launch(self, offer: Offer, image: str, env: dict[str, str], label: str) -> str:
        body = {"name": label, "image": image, "gpu": {"id": offer.offer_id, "count": 1}, "cloud": self.cloud,
                "ports": [f"{WORKER_PORT}/http"], "env": {k: str(v) for k, v in env.items()}, "disk": 40, "startSsh": False}
        data = _check(self.client.post(f"{self.base}/v2/pods", json=body, headers=self.h), "location RunPod")
        if not data.get("id"):
            raise ProviderError(f"location RunPod refusée : {data}")
        return str(data["id"])

    def status(self, instance_id: str) -> InstanceStatus:
        data = _check(self.client.get(f"{self.base}/v2/pods/{instance_id}", headers=self.h), "état RunPod")
        state = data.get("status") or "inconnu"
        running = state == "RUNNING"
        return InstanceStatus(running=running, detail=state, usd_per_hour=data.get("cost"),
                              endpoint=f"https://{instance_id}-{WORKER_PORT}.proxy.runpod.net" if running else None)

    def destroy(self, instance_id: str) -> None:
        _check(self.client.delete(f"{self.base}/v2/pods/{instance_id}", headers=self.h), "arrêt RunPod")
