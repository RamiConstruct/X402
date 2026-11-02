import json

import httpx
import pytest

from live.gpu.manager import GpuError, GpuManager, Limits
from live.gpu.providers import InstanceStatus, Offer, Provider, RunPodProvider, VastProvider


# ------------------------------------------------------------------ contrats fournisseurs
def test_vast_search_create_status_destroy():
    seen = []

    def handler(req: httpx.Request):
        seen.append((req.method, req.url.path, json.loads(req.content) if req.content else None, dict(req.url.params)))
        assert req.headers["authorization"] == "Bearer VK"
        if req.url.path == "/api/v0/bundles/":
            return httpx.Response(200, json={"offers": [
                {"id": 11, "gpu_name": "RTX 4090", "gpu_ram": 24564, "dph_total": 0.41, "geolocation": "France, FR", "reliability2": 0.99}]})
        if req.url.path == "/api/v0/asks/11/":
            return httpx.Response(200, json={"success": True, "new_contract": 777})
        if req.method == "GET":
            return httpx.Response(200, json={"instances": {"actual_status": "running", "public_ipaddr": "1.2.3.4",
                                                           "ports": {"8890/tcp": [{"HostIp": "0.0.0.0", "HostPort": "41890"}]},
                                                           "dph_total": 0.42}})
        return httpx.Response(200, json={"success": True})

    p = VastProvider("VK", client=httpx.Client(transport=httpx.MockTransport(handler)))
    offers = p.search(min_vram_gb=24, max_usd_per_hour=1.0)
    q = seen[0][2]
    assert q["gpu_ram"] == {"gte": 24000} and q["num_gpus"] == {"eq": 1} and q["dph_total"] == {"lte": 1.0}
    assert q["order"] == [["dph_total", "asc"]] and q["type"] == "on-demand"
    assert offers[0].vram_gb == 24.6 and offers[0].usd_per_hour == 0.41 and offers[0].key == "vast:11"

    iid = p.launch(offers[0], "ghcr.io/moi/worker:1", {"WORKER_TOKEN": "t"}, "ai-live")
    body = seen[1][2]
    assert seen[1][0] == "PUT" and iid == "777"
    assert body["image"] == "ghcr.io/moi/worker:1" and body["runtype"] == "args" and body["label"] == "ai-live"
    assert body["env"]["-p 8890:8890"] == "1" and body["env"]["WORKER_TOKEN"] == "t"

    st = p.status("777")
    assert seen[2][3] == {"owner": "me"}
    assert st.running and st.endpoint == "http://1.2.3.4:41890" and st.usd_per_hour == 0.42
    p.destroy("777")
    assert seen[3][:2] == ("DELETE", "/api/v0/instances/777/")


def test_runpod_search_create_status():
    seen = []

    def handler(req):
        seen.append((req.method, req.url.path, json.loads(req.content) if req.content else None))
        if req.url.path == "/v2/catalog/gpus":
            return httpx.Response(200, json={"gpus": [
                {"id": "NVIDIA GeForce RTX 4090", "name": "RTX 4090", "memory": 24, "price": {"community": 0.34, "secure": 0.69}, "availability": "HIGH", "dataCenters": [{"id": "EU-RO-1"}]},
                {"id": "NVIDIA GeForce RTX 3070", "name": "RTX 3070", "memory": 8, "price": {"community": 0.13}, "availability": "HIGH"},
                {"id": "NVIDIA H100", "name": "H100", "memory": 80, "price": {"community": 2.69}, "availability": "LOW"},
                {"id": "NVIDIA L40S", "name": "L40S", "memory": 48, "price": {"community": 0.79}, "availability": "NONE"}]})
        if req.url.path == "/v2/pods":
            return httpx.Response(200, json={"id": "pod123"})
        return httpx.Response(200, json={"id": "pod123", "status": "RUNNING", "cost": 0.34})

    p = RunPodProvider("RK", client=httpx.Client(transport=httpx.MockTransport(handler)))
    offers = p.search(min_vram_gb=24, max_usd_per_hour=1.0)
    assert [o.gpu_name for o in offers] == ["RTX 4090"]  # 8 Go trop petit, H100 trop cher, L40S indisponible
    iid = p.launch(offers[0], "img", {"A": "1"}, "ai-live")
    body = seen[1][2]
    assert body["gpu"] == {"id": "NVIDIA GeForce RTX 4090", "count": 1} and body["ports"] == ["8890/http"]
    assert body["cloud"] == "COMMUNITY" and iid == "pod123"
    st = p.status("pod123")
    assert st.running and st.endpoint == "https://pod123-8890.proxy.runpod.net"


# ------------------------------------------------------------------ garde-fous
class FakeProvider(Provider):
    name = "fake"

    def __init__(self, endpoint="http://w", price=0.5):
        self.endpoint, self.price, self.launched, self.destroyed, self.running = endpoint, price, [], [], True

    def search(self, min_vram_gb, max_usd_per_hour, limit=10):
        offers = [Offer("fake", "a", "RTX 5090", 32, self.price), Offer("fake", "b", "H100", 80, 2.5)]
        return [o for o in offers if o.usd_per_hour <= max_usd_per_hour and o.vram_gb >= min_vram_gb]

    def launch(self, offer, image, env, label):
        self.launched.append((offer.offer_id, image, env))
        return "i1"

    def status(self, iid):
        return InstanceStatus(self.running, self.endpoint if self.running else None, "running" if self.running else "loading")

    def destroy(self, iid):
        self.destroyed.append(iid)


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


def health_ok(ready=True):
    return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"ready": ready, "warmup": "prêt"})))


def manager(tmp_path, clock, **kw):
    fp = FakeProvider()
    m = GpuManager({"fake": fp}, tmp_path / "s.json", image="img", limits=Limits(**kw), http=health_ok(), clock=clock)
    return m, fp


def test_quote_filters_price_and_owner_markup(tmp_path):
    m, _ = manager(tmp_path, Clock(), max_usd_per_hour=1.0)
    q = m.quote("sdxl-turbo")
    assert [o["gpu"] for o in q["offers"]] == ["RTX 5090"] and q["markup"] == 1.0
    assert q["offers"][0]["price_per_min"] == round(0.5 / 60, 4)
    m.limits.owner_mode = False
    assert m.quote("sdxl-turbo")["offers"][0]["price_per_min"] == round(0.5 / 60 * 2.0, 4)


def test_rent_ready_idle_release_and_persistence(tmp_path):
    clock = Clock()
    m, fp = manager(tmp_path, clock, idle_minutes=10)
    m.quote("sd-turbo")
    r = m.rent("fake:a", "sd-turbo")
    env = fp.launched[0][2]
    assert env["WORKER_PROCESSOR"] == "streamdiffusion" and len(env["WORKER_TOKEN"]) > 20
    assert json.loads(env["WORKER_WARMUP_PARAMS"])["model_id"] == "stabilityai/sd-turbo"
    with pytest.raises(GpuError):
        m.rent("fake:a", "sd-turbo")  # une seule location à la fois
    assert m.refresh().state == "ready" and r.endpoint == "http://w"
    assert "token" not in m.view()

    # reprise après redémarrage : la location est retrouvée sur disque
    m2 = GpuManager({"fake": fp}, tmp_path / "s.json", image="img", limits=Limits(idle_minutes=10), http=health_ok(), clock=clock)
    assert m2.rental.instance_id == "i1" and m2.rental.state == "ready"

    clock.t += 9 * 60
    m2.touch()
    clock.t += 9 * 60
    assert m2.refresh().state == "ready"           # actif il y a 9 min : on garde
    clock.t += 2 * 60
    assert m2.refresh().state == "released"        # 11 min sans activité : libéré
    assert fp.destroyed == ["i1"] and "inactif" in m2.rental.release_reason
    assert m2.history[-1]["cost_usd"] == pytest.approx(0.5 * 20 / 60, abs=1e-3)


def test_boot_timeout_and_max_hours(tmp_path):
    clock = Clock()
    m, fp = manager(tmp_path, clock, max_hours=1)
    fp.running = False
    m.quote("sd-turbo")
    m.rent("fake:a", "sd-turbo")
    clock.t += 31 * 60
    assert m.refresh().state == "released" and "30 minutes" in m.rental.release_reason

    fp.running = True
    m.quote("sd-turbo")
    m.rent("fake:a", "sd-turbo")
    m.refresh()
    clock.t += 61 * 60
    m.touch()
    assert m.refresh().state == "released" and "durée maximale" in m.rental.release_reason


def test_release_failure_is_reported(tmp_path):
    m, fp = manager(tmp_path, Clock())
    m.quote("sd-turbo")
    m.rent("fake:a", "sd-turbo")

    def boom(iid):
        raise httpx.ConnectError("réseau")
    fp.destroy = boom
    with pytest.raises(GpuError, match="vérifie sur le site"):
        m.release()
    assert m.rental.state != "released"  # jamais marqué libéré sans confirmation


def test_worker_warmup_and_reuse(monkeypatch):
    monkeypatch.setenv("WORKER_PROCESSOR", "demo")
    from fastapi.testclient import TestClient
    from live.worker.app import create_worker_app
    app = create_worker_app(token="t", warmup={"model_id": "stabilityai/sd-turbo", "width": 512, "height": 512, "prompt": "x"})
    with TestClient(app) as c:
        for _ in range(50):
            h = c.get("/health").json()
            if h["ready"]:
                break
        assert h["ready"] and h["warmup"] == "prêt"
        r = c.post("/v1/streams", headers={"Authorization": "Bearer t"},
                   json={"pipeline": "streamdiffusion", "params": {"model_id": "stabilityai/sd-turbo", "prompt": "robot"}})
        assert r.status_code == 200 and r.json()["whip_url"].endswith("/whip")
        assert c.post("/v1/streams", json={}).status_code == 401
