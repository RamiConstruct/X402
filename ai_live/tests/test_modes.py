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
