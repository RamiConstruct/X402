"""Flotte de GPU automatique : placement, montée en charge, réserve, plafonds, reprise après redémarrage."""
from __future__ import annotations

import httpx
import pytest

from live.gpu.fleet import FleetLimits, GpuFleet, Tier, region_rank
from live.gpu.providers import InstanceStatus, Offer, Provider, ProviderError

TIERS = {"standard": Tier("standard", "Standard", "sd-turbo", 24, 3, 1.0),
         "ultra": Tier("ultra", "Ultra", "sdxl-turbo", 80, 1, 4.0)}


class FakeProvider(Provider):
    name = "fake"

    def __init__(self, offers):
        self.offers, self.launched, self.destroyed, self.running = offers, [], [], set()
        self.fail_destroy = False

    def search(self, min_vram_gb, max_usd_per_hour, limit=10):
        return [o for o in self.offers if o.vram_gb >= min_vram_gb and o.usd_per_hour <= max_usd_per_hour][:limit]

    def launch(self, offer, image, env, label):
        iid = f"i{len(self.launched)}"
        self.launched.append((iid, offer, env))
        return iid

    def status(self, iid):
        up = iid in self.running
        return InstanceStatus(running=up, endpoint=f"http://{iid}:8890" if up else None, detail="ok" if up else "boot")

    def destroy(self, iid):
        if self.fail_destroy:
            raise ProviderError("réseau")
        self.destroyed.append(iid)


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


def health_http():
    return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"ready": True})))


def offer(i, gpu="RTX 4090", vram=24, price=0.5, loc="Singapore, SG"):
    return Offer("fake", str(i), gpu, vram, price, loc, 0.99)


def make(tmp_path, offers=None, **lim):
    p = FakeProvider(offers or [offer(i) for i in range(10)])
    clock = Clock()
    f = GpuFleet({"fake": p}, tmp_path / "fleet.json", image="img", tiers=TIERS,
                 limits=FleetLimits(**{"max_usd_per_hour": 10, "max_nodes": 8, **lim}), http=health_http(), clock=clock)
    return f, p, clock


def boot_all(f, p):
    for iid, _, _ in p.launched:
        p.running.add(iid)
    f.tick()


def test_first_user_waits_and_gpus_are_rented(tmp_path):
    f, p, _ = make(tmp_path)
    assert f.assign("s1", "standard") is None                      # aucun GPU prêt : en préparation
    assert 1 <= len(p.launched) <= 2                               # la place demandée + la réserve
    env = p.launched[0][2]
    assert env["WORKER_PROCESSOR"] == "streamdiffusion" and "sd-turbo" in env["WORKER_WARMUP_PARAMS"]
    boot_all(f, p)
    assert all(n.state == "ready" for n in f.nodes.values())
    assert f.assign("s1", "standard") is not None


def test_users_are_packed_before_spreading(tmp_path):
    f, p, _ = make(tmp_path, spare_nodes=1)
    f.assign("x", "standard"); boot_all(f, p)
    nodes = {f.assign(f"s{i}", "standard").id for i in range(3)}
    assert len(nodes) == 1                                         # 3 places sur le même GPU
    boot_all(f, p)
    assert f.assign("s4", "standard").id not in nodes              # 4e utilisateur : GPU suivant
    # toujours un GPU d'avance (3 places libres) après les arrivées
    ready, coming = f._free_capacity(TIERS["standard"])
    assert ready + coming >= 3


def test_preferred_region_beats_cheaper_far_gpu(tmp_path):
    offers = [offer(1, price=0.3, loc="Texas, US"), offer(2, price=0.6, loc="Singapore, SG")]
    f, p, _ = make(tmp_path, offers=offers, regions=("Singapore", "Japan"), spare_nodes=0)
    f.assign("s1", "standard")
    assert p.launched[0][1].location == "Singapore, SG"
    assert region_rank("Tokyo, Japan", ("Singapore", "Japan")) == 1


def test_hourly_budget_and_max_nodes_are_respected(tmp_path):
    f, p, _ = make(tmp_path, max_usd_per_hour=1.2, spare_nodes=3)
    f.assign("s1", "standard")
    assert len(p.launched) == 2 and f.cost_per_hour() <= 1.2       # 2 × 0,5 $ ; le 3e dépasserait
    f2, p2, _ = make(tmp_path / "b", max_nodes=1, spare_nodes=3)
    f2.assign("s1", "standard")
    assert len(p2.launched) == 1


def test_ultra_tier_uses_big_gpus_one_user_each(tmp_path):
    offers = [offer(1), offer(2, gpu="H100 SXM", vram=80, price=2.9, loc="Vietnam")]
    f, p, _ = make(tmp_path, offers=offers, spare_nodes=0)
    f.assign("u1", "ultra")
    assert [o.gpu_name for _, o, _ in p.launched] == ["H100 SXM"]
    boot_all(f, p)
    assert f.assign("u1", "ultra") is not None
    assert f.assign("u2", "ultra") is None                         # 1 place par H100 : un autre est loué
    assert len(p.launched) == 2


def test_empty_gpus_are_returned_but_spare_kept_while_demand_is_recent(tmp_path):
    f, p, clock = make(tmp_path, spare_nodes=1, idle_minutes=5, demand_minutes=30)
    f.assign("x", "standard"); boot_all(f, p); f.release_session("x")   # « x » abandonne
    for i in range(6):
        f.assign(f"s{i}", "standard")
    boot_all(f, p)
    n_before = len(f.nodes)
    for i in range(6):
        f.release_session(f"s{i}")
    clock.t += 6 * 60; f.tick()
    assert len(f.nodes) == 1 and len(p.destroyed) == n_before - 1  # la réserve reste
    clock.t += 31 * 60; f.tick(); clock.t += 6 * 60; f.tick()
    assert len(f.nodes) == 0                                       # plus de demande : tout est rendu


def test_gpu_not_ready_in_time_is_replaced_then_forgotten(tmp_path):
    f, p, clock = make(tmp_path, spare_nodes=0, boot_minutes=30, wait_minutes=40, demand_minutes=1)
    f.assign("s1", "standard")
    clock.t += 31 * 60; f.tick()
    assert p.destroyed == ["i0"] and len(f.nodes) == 1             # remplacé : l'utilisateur attend encore
    clock.t += 31 * 60; f.tick()                                   # 2e échec, et l'attente a expiré
    assert not f.nodes and len(p.launched) == 2


def test_failed_destroy_keeps_node_tracked_and_state_survives_restart(tmp_path):
    f, p, clock = make(tmp_path, spare_nodes=0, boot_minutes=1)
    f.assign("s1", "standard")
    p.fail_destroy = True
    clock.t += 2 * 60; f.tick()
    assert len(f.nodes) == 1 and "non confirmé" in next(iter(f.nodes.values())).detail
    f2 = GpuFleet({"fake": p}, tmp_path / "fleet.json", image="img", tiers=TIERS, http=health_http(), clock=clock)
    assert len(f2.nodes) == 1                                      # retrouvé après redémarrage
    p.fail_destroy = False
    f2.shutdown()
    assert not f2.nodes and p.destroyed


def test_view_hides_worker_tokens(tmp_path):
    f, p, _ = make(tmp_path)
    f.assign("s1", "standard")
    v = f.view()
    assert v["nodes"] and all("token" not in n for n in v["nodes"])
    assert v["usd_per_hour"] == f.cost_per_hour()


def test_unknown_tier_is_refused(tmp_path):
    f, _, _ = make(tmp_path)
    with pytest.raises(Exception):
        f.assign("s1", "platine")
