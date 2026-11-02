"""Le client respecte le contrat de l'API Daydream (vérifié dans le SDK et le plugin officiels)."""
import json

import httpx
import pytest

from live.engine import EngineConfig, EngineError, StreamEngine
from live.scene import Scene


def make(handler):
    cfg = EngineConfig(name="dd", base_url="https://api.daydream.live", api_key="KEY")
    return StreamEngine(cfg, client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)


def test_create_payload_and_response():
    seen = {}

    def handler(req):
        seen["method"], seen["url"], seen["auth"] = req.method, str(req.url), req.headers["authorization"]
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"id": "str_1", "whip_url": "https://ai.livepeer.com/live/x/whip", "output_playback_id": "p"})

    data = make(handler).create(Scene(character="robot"))
    assert seen["method"] == "POST" and seen["url"] == "https://api.daydream.live/v1/streams"
    assert seen["auth"] == "Bearer KEY"
    body = seen["body"]
    assert body["pipeline"] == "streamdiffusion"
    p = body["params"]
    assert p["model_id"] == "stabilityai/sdxl-turbo" and "robot" in p["prompt"]
    assert p["t_index_list"] == [14] and p["width"] == 512 and p["num_inference_steps"] == 50
    assert [c["model_id"] for c in p["controlnets"]] == ["xinsir/controlnet-depth-sdxl-1.0", "xinsir/controlnet-tile-sdxl-1.0"]
    assert data["id"] == "str_1"


def test_update_is_patch_without_init_fields():
    seen = {}

    def handler(req):
        seen["method"], seen["path"], seen["body"] = req.method, req.url.path, json.loads(req.content)
        return httpx.Response(200, json={})

    make(handler).update("str_1", Scene(decor="espace", strength=2))
    assert seen["method"] == "PATCH" and seen["path"] == "/v1/streams/str_1"
    p = seen["body"]["params"]
    assert p["model_id"] and "spaceship" in p["prompt"] and p["t_index_list"] == [30]
    assert "width" not in p and "controlnets" not in p  # non modifiables à chaud


def test_whip_reads_playback_header():
    def handler(req):
        assert req.headers["content-type"] == "application/sdp" and req.headers["authorization"] == "Bearer KEY"
        return httpx.Response(201, text="v=0 answer", headers={"Livepeer-Playback-Url": "https://x/whep/abc"})

    answer, whep = make(handler).whip("https://ai.livepeer.com/live/x/whip", "v=0 offer")
    assert answer == "v=0 answer" and whep == "https://x/whep/abc"


def test_whep_retries_until_ready():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(404) if calls["n"] < 3 else httpx.Response(201, text="v=0 ok")

    assert make(handler).whep("https://x/whep/abc", "v=0 offer") == "v=0 ok" and calls["n"] == 3


def test_errors_and_missing_key():
    eng = make(lambda req: httpx.Response(401, text="bad key"))
    with pytest.raises(EngineError, match="401"):
        eng.create(Scene())
    eng.cfg.api_key = ""
    with pytest.raises(EngineError, match="clé API manquante"):
        eng.create(Scene())


def test_delete_uses_query_id():
    seen = {}

    def handler(req):
        seen["method"], seen["path"], seen["q"] = req.method, req.url.path, dict(req.url.params)
        return httpx.Response(200, json={})

    make(handler).delete("str_9")
    assert seen == {"method": "DELETE", "path": "/v1/streams", "q": {"id": "str_9"}}


def test_parody_adds_negative_photoreal():
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={})

    make(handler).update("s", Scene(parody_of="Emmanuel Macron"))
    assert "photorealistic" in seen["body"]["params"]["negative_prompt"]


def test_bypass_param_per_engine():
    from live.engine import scene_params
    s = Scene(character="robot", bypass=True)
    worker_cfg = EngineConfig(name="w", base_url="x", api_key="k", supports_output_size=True)
    dd_cfg = EngineConfig(name="d", base_url="x", api_key="k")
    assert scene_params(s, worker_cfg, initial=False)["bypass"] is True
    p = scene_params(s, dd_cfg, initial=False)
    assert "bypass" not in p and p["t_index_list"] == [49]
    assert "bypass" not in scene_params(s, worker_cfg, initial=True)
