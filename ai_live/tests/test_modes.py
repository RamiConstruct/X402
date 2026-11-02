"""Modes de rendu (rapide / équilibré / qualité), graine fixe et commande « autre version »."""
import json

import httpx
from fastapi.testclient import TestClient

from live.commands import apply_command
from live.engine import QUALITY_MODES, EngineConfig, StreamEngine, scene_params
from live.scene import DEFAULT_SEED, Scene, SceneHistory
from live.server import create_app

DD = EngineConfig(name="dd", base_url="https://api.daydream.live", api_key="K", switch_models=True)
SELF = EngineConfig(name="gpu", base_url="http://w", api_key="t", model_id="stabilityai/sd-turbo", supports_output_size=True)


def test_modes_daydream():
    rapide = scene_params(Scene(), DD, initial=True, mode="rapide")
    assert rapide["model_id"] == "stabilityai/sd-turbo" and rapide["width"] == 512 and len(rapide["t_index_list"]) == 1
    eq = scene_params(Scene(), DD, initial=True, mode="equilibre")
    assert eq["model_id"] == "stabilityai/sdxl-turbo" and len(eq["controlnets"]) == 2
    q = scene_params(Scene(), DD, initial=True, mode="qualite")
    assert q["width"] == q["height"] == 512 and len(q["t_index_list"]) == 2
    assert {c["model_id"].split("-")[1] for c in q["controlnets"]} == {"depth", "canny", "tile"}
    assert q["t_index_list"][0] < q["t_index_list"][1] <= 45
    # Valeurs refusées par l'API Daydream (largeur multiple de 64, ≤ 1024)
    for m in QUALITY_MODES.values():
        assert m["size"] % 64 == 0 and m["size"] <= 1024


def test_mode_keeps_model_on_selfhosted():
    p = scene_params(Scene(), SELF, initial=True, mode="qualite")
    assert p["model_id"] == "stabilityai/sd-turbo" and p["width"] == 512 and len(p["t_index_list"]) == 2


def test_unknown_mode_falls_back():
    assert scene_params(Scene(), DD, initial=True, mode="nimporte")["model_id"] == "stabilityai/sdxl-turbo"


def test_seed_and_variant():
    h = SceneHistory()
    assert scene_params(h.current, DD, initial=False)["seed"] == DEFAULT_SEED
    r = apply_command(h, "autre version")
    assert r.ok and h.current.seed != DEFAULT_SEED
    s1 = h.current.seed
    apply_command(h, "transforme-moi en pirate")
    assert h.current.seed == s1  # changer de personnage garde la graine (pas de saut inutile)
    apply_command(h, "annule")
    apply_command(h, "annule")
    assert h.current.seed == DEFAULT_SEED


def test_server_mode_roundtrip():
    seen = []

    def handler(req):
        if req.method == "POST" and req.url.path == "/v1/streams":
            seen.append(json.loads(req.content))
            return httpx.Response(200, json={"id": "s1", "whip_url": "https://w/whip"})
        if req.method == "PATCH":
            seen.append(json.loads(req.content))
            return httpx.Response(200, json={})
        return httpx.Response(200, json={})

    factory = lambda cfg: StreamEngine(cfg, client=httpx.Client(transport=httpx.MockTransport(handler)))  # noqa: E731
    app = create_app(engines={"daydream": DD}, engine_factory=factory, access_token="", gpu=False)
    c = TestClient(app)
    cat = c.get("/api/catalog").json()
    assert [m["key"] for m in cat["modes"]] == ["rapide", "equilibre", "qualite"]
    assert c.post("/api/sessions", json={"engine": "daydream", "mode": "turbo"}).status_code == 400
    s = c.post("/api/sessions", json={"engine": "daydream", "mode": "qualite"}).json()
    assert s["mode"] == "qualite" and s["mode_label"] == "Qualité"
    assert len(seen[0]["params"]["controlnets"]) == 3
    c.post(f"/api/sessions/{s['id']}/command", json={"text": "plus fort"})
    assert len(seen[-1]["params"]["t_index_list"]) == 2  # les mises à jour gardent le mode


def _app_with_log():
    log = []

    def handler(req):
        if req.method == "POST" and req.url.path == "/v1/streams":
            body = json.loads(req.content)
            log.append(("POST", body))
            n = sum(1 for m, _ in log if m == "POST")
            return httpx.Response(200, json={"id": f"s{n}", "whip_url": f"https://w/{n}/whip"})
        if req.method == "DELETE":
            log.append(("DELETE", dict(req.url.params)))
        if req.method == "PATCH":
            log.append(("PATCH", json.loads(req.content)))
        return httpx.Response(200, json={})

    factory = lambda cfg: StreamEngine(cfg, client=httpx.Client(transport=httpx.MockTransport(handler)))  # noqa: E731
    return TestClient(create_app(engines={"daydream": DD}, engine_factory=factory, access_token="", gpu=False)), log


def test_switch_mode_recreates_stream_and_keeps_scene():
    c, log = _app_with_log()
    s = c.post("/api/sessions", json={"engine": "daydream", "mode": "qualite"}).json()
    c.post(f"/api/sessions/{s['id']}/command", json={"text": "transforme-moi en pirate"})
    r = c.post(f"/api/sessions/{s['id']}/mode", json={"mode": "rapide", "reason": "auto"})
    assert r.status_code == 200
    v = r.json()
    assert v["mode"] == "rapide" and v["mode_label"] == "Rapide"
    assert ("DELETE", {"id": "s1"}) in log
    last_post = [b for m, b in log if m == "POST"][-1]
    assert last_post["params"]["model_id"] == "stabilityai/sd-turbo" and "pirate" in last_post["params"]["prompt"]
    assert any("rapide" in e["message"].lower() for e in v["log"])
    # même mode : rien à faire
    assert c.post(f"/api/sessions/{s['id']}/mode", json={"mode": "rapide"}).json()["mode"] == "rapide"
    assert sum(1 for m, _ in log if m == "POST") == 2


def test_switch_mode_refused_while_broadcasting_or_unknown():
    c, _ = _app_with_log()
    s = c.post("/api/sessions", json={"engine": "daydream", "mode": "equilibre"}).json()
    assert c.post(f"/api/sessions/{s['id']}/mode", json={"mode": "turbo"}).status_code == 400
    b = c.post("/api/sessions", json={"engine": "daydream", "broadcast": [
        {"platform": "youtube", "server_url": "rtmp://a.example/live", "stream_key": "k1", "format": "horizontal"}]}).json()
    r = c.post(f"/api/sessions/{b['id']}/mode", json={"mode": "rapide"})
    assert r.status_code == 409


def test_command_before_stream_ready_is_kept_then_applied():
    calls = {"patch": 0}

    def handler(req):
        if req.method == "POST" and req.url.path == "/v1/streams":
            return httpx.Response(200, json={"id": "s1", "whip_url": "https://w/whip"})
        if req.method == "PATCH":
            calls["patch"] += 1
            if calls["patch"] == 1:
                return httpx.Response(404, json={"error": "Stream not ready yet", "code": "STREAMS/NOT_FOUND"})
            calls["last"] = json.loads(req.content)
            return httpx.Response(200, json={})
        if req.url.path.endswith("/whip"):
            return httpx.Response(201, text="v=0 answer", headers={"livepeer-playback-url": "https://w/whep"})
        if req.url.path.endswith("/whep"):
            return httpx.Response(201, text="v=0 play")
        return httpx.Response(200, json={})

    factory = lambda cfg: StreamEngine(cfg, client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)  # noqa: E731
    c = TestClient(create_app(engines={"daydream": DD}, engine_factory=factory, access_token="", gpu=False))
    s = c.post("/api/sessions", json={"engine": "daydream"}).json()
    r = c.post(f"/api/sessions/{s['id']}/command", json={"text": "transforme-moi en pirate"})
    assert r.status_code == 200 and r.json()["ok"]  # plus d'erreur 502 pendant le chargement
    c.post(f"/api/sessions/{s['id']}/whip", content=b"v=0 offer", headers={"content-type": "application/sdp"})
    c.post(f"/api/sessions/{s['id']}/whep", content=b"v=0 offer", headers={"content-type": "application/sdp"})
    assert "pirate" in calls["last"]["params"]["prompt"]  # appliqué dès que la sortie IA est prête
