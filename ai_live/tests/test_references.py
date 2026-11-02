"""Images de référence (IP-Adapter) et « garder mon visage » (FaceID)."""
import json

import httpx
from fastapi.testclient import TestClient

from live.engine import EngineConfig, StreamEngine, scene_params
from live.references import References
from live.scene import Scene
from live.server import create_app

DD = EngineConfig(name="dd", base_url="https://api.daydream.live", api_key="K", switch_models=True, supports_ip_adapter=True)
SELF = EngineConfig(name="gpu", base_url="http://w", api_key="t", model_id="stabilityai/sd-turbo")


def make_refs(tmp_path):
    root = tmp_path / "references"
    for kind, key in [("characters", "chevalier"), ("styles", "anime")]:
        (root / kind / key).mkdir(parents=True)
        for i in (1, 2):
            (root / kind / key / f"{i}.jpg").write_bytes(b"\xff\xd8jpg")
    (root / "manifest.json").write_text(json.dumps({
        "characters": {"chevalier": [{"file": "1.jpg", "license": "CC0"}, {"file": "2.jpg", "license": "CC0"}]},
        "styles": {"anime": [{"file": "1.jpg", "license": "CC0"}, {"file": "2.jpg", "license": "CC0"}]}}))
    return References(root, "https://live.example")


def test_pick_reference_priority_and_variant(tmp_path):
    R = make_refs(tmp_path)
    assert R.pick(Scene()) is None
    assert R.pick(Scene(style="anime")).endswith("/refs/styles/anime/1.jpg") or R.pick(Scene(style="anime")).endswith("/2.jpg")
    s = Scene(character="chevalier", style="anime")
    url = R.pick(s)
    assert "/refs/characters/chevalier/" in url  # le personnage passe avant le style
    s2 = Scene(character="chevalier", seed=s.seed + 1)
    assert R.pick(s2) != url  # « autre version » change aussi d'image de référence
    assert R.pick(Scene(parody_of="Emmanuel Macron")) is None  # jamais de référence pour une caricature
    assert R.pick(Scene(character="robot")) is None  # pas d'image pour ce personnage → texte seul


def test_params_regular_reference():
    p = scene_params(Scene(character="chevalier"), DD, initial=True, mode="equilibre", refs={"style_image_url": "https://x/1.jpg"})
    assert p["ip_adapter"]["type"] == "regular" and p["ip_adapter"]["enabled"] is True
    assert p["ip_adapter_style_image_url"] == "https://x/1.jpg"


def test_params_face_lock_wins():
    s = Scene(character="chevalier", face_lock=True)
    p = scene_params(s, DD, initial=False, mode="qualite", refs={"style_image_url": "https://x/1.jpg", "face_image_url": "https://x/face.jpg"})
    assert p["ip_adapter"]["type"] == "faceid" and p["ip_adapter_style_image_url"] == "https://x/face.jpg"


def test_params_disabled_when_unsupported():
    # mode Rapide (sd-turbo) : Daydream refuse ip_adapter → aucun champ envoyé
    p = scene_params(Scene(character="chevalier"), DD, initial=True, mode="rapide", refs={"style_image_url": "https://x/1.jpg"})
    assert "ip_adapter" not in p and "ip_adapter_style_image_url" not in p
    p = scene_params(Scene(character="chevalier"), SELF, initial=True, refs={"style_image_url": "https://x/1.jpg"})
    assert "ip_adapter" not in p
    # pas de référence : adaptateur désactivé (pour couper une référence précédente)
    p = scene_params(Scene(), DD, initial=False, mode="equilibre", refs={})
    assert p["ip_adapter"]["enabled"] is False and "ip_adapter_style_image_url" not in p


def test_face_upload_flow(tmp_path):
    seen = []

    def handler(req):
        if req.method in ("POST", "PATCH") and "/v1/streams" in req.url.path:
            seen.append(json.loads(req.content))
            return httpx.Response(200, json={"id": "s1", "whip_url": "https://w/whip"})
        return httpx.Response(200, json={})

    factory = lambda cfg: StreamEngine(cfg, client=httpx.Client(transport=httpx.MockTransport(handler)))  # noqa: E731
    app = create_app(engines={"daydream": DD}, engine_factory=factory, access_token="tok", gpu=False,
                     references=make_refs(tmp_path))
    c = TestClient(app)
    h = {"X-Live-Token": "tok"}
    s = c.post("/api/sessions", json={"engine": "daydream", "mode": "equilibre"}, headers=h).json()
    c.post(f"/api/sessions/{s['id']}/command", json={"text": "transforme-moi en chevalier"}, headers=h)
    assert seen[-1]["params"]["ip_adapter"]["type"] == "regular"
    assert c.post(f"/api/sessions/{s['id']}/face", content=b"\xff\xd8jpg", headers={**h, "content-type": "image/jpeg"}).status_code == 200
    face_url = seen[-1]["params"]["ip_adapter_style_image_url"]
    assert seen[-1]["params"]["ip_adapter"]["type"] == "faceid" and "/api/face/" in face_url
    path = face_url.split("https://live.example")[1]
    assert c.get(path).content == b"\xff\xd8jpg"  # lisible par Daydream (adresse secrète, sans jeton)
    assert c.post(f"/api/sessions/{s['id']}/face", content=b"not-a-jpeg", headers={**h, "content-type": "image/jpeg"}).status_code == 400
    assert c.post(f"/api/sessions/{s['id']}/face", content=b"x", headers={"content-type": "image/jpeg"}).status_code == 401
    c.delete(f"/api/sessions/{s['id']}/face", headers=h)
    assert seen[-1]["params"]["ip_adapter"]["type"] == "regular"
    assert c.get(path).status_code == 404  # photo effacée dès qu'on désactive
    c.post(f"/api/sessions/{s['id']}/face", content=b"\xff\xd8jpg", headers={**h, "content-type": "image/jpeg"})
    p2 = seen[-1]["params"]["ip_adapter_style_image_url"].split("https://live.example")[1]
    c.delete(f"/api/sessions/{s['id']}", headers=h)
    assert c.get(p2).status_code == 404  # et à la fin de la session
    assert c.get("/refs/characters/chevalier/1.jpg").status_code == 200
