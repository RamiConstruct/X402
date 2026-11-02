import base64
import hashlib
import hmac
import json

from live.check_turn import parse, parse_urls
from live.turn import credentials, ice_from_env


def test_credentials_match_coturn_rest_scheme():
    user, cred = credentials("s3cret", "live", ttl_s=600, now=1_000_000)
    assert user == "1000600:live"
    assert cred == base64.b64encode(hmac.new(b"s3cret", b"1000600:live", hashlib.sha1).digest()).decode()


def test_ice_from_env(monkeypatch):
    monkeypatch.delenv("LIVE_ICE_SERVERS", raising=False)
    monkeypatch.delenv("LIVE_TURN_SECRET", raising=False)
    assert ice_from_env() == []
    monkeypatch.setenv("LIVE_TURN_SECRET", "abc")
    monkeypatch.setenv("LIVE_TURN_URLS", json.dumps(["turn:1.2.3.4:3478?transport=udp"]))
    ice = ice_from_env()
    assert ice[0]["urls"] == ["turn:1.2.3.4:3478?transport=udp"] and ":live" in ice[0]["username"]
    assert "abc" not in json.dumps(ice)  # le secret n'est jamais transmis


def test_catalog_exposes_temporary_credentials_only(monkeypatch):
    from fastapi.testclient import TestClient
    from live.server import create_app
    monkeypatch.setenv("LIVE_TURN_SECRET", "topsecret")
    monkeypatch.setenv("LIVE_TURN_URLS", '["turn:9.9.9.9:3478?transport=tcp"]')
    with TestClient(create_app(engines={}, gpu=False)) as c:
        cat = c.get("/api/catalog").json()
    assert cat["ice_servers"][0]["urls"] == ["turn:9.9.9.9:3478?transport=tcp"]
    assert "topsecret" not in json.dumps(cat)


def test_url_parsing():
    assert parse("turn:1.2.3.4:3478?transport=tcp") == ("1.2.3.4", 3478, "tcp", False)
    assert parse("turns:turn.ex.com:5349?transport=tcp") == ("turn.ex.com", 5349, "tcp", True)
    assert parse_urls("[turn:a:3478?transport=udp,turn:a:3478?transport=tcp]") == ["turn:a:3478?transport=udp", "turn:a:3478?transport=tcp"]


def test_cloudflare_turn_generates_filters_and_caches():
    import httpx
    from live.turn import CloudflareTurn
    calls = []

    def handler(req):
        calls.append((str(req.url), req.headers["authorization"], json.loads(req.content)))
        return httpx.Response(201, json={"iceServers": [
            {"urls": ["stun:stun.cloudflare.com:3478", "stun:stun.cloudflare.com:53"]},
            {"urls": ["turn:turn.cloudflare.com:3478?transport=udp", "turn:turn.cloudflare.com:53?transport=udp",
                      "turns:turn.cloudflare.com:443?transport=tcp"], "username": "u", "credential": "c"}]})

    cf = CloudflareTurn("KID", "TOK", client=httpx.Client(transport=httpx.MockTransport(handler)))
    ice = cf.ice_servers(3600)
    assert calls[0] == ("https://rtc.live.cloudflare.com/v1/turn/keys/KID/credentials/generate-ice-servers",
                        "Bearer TOK", {"ttl": 3600})
    assert ice[1]["urls"] == ["turn:turn.cloudflare.com:3478?transport=udp", "turns:turn.cloudflare.com:443?transport=tcp"]
    assert all(":53" not in u for s in ice for u in s["urls"])
    cf.ice_servers(3600)
    assert len(calls) == 1  # mis en cache


def test_cloudflare_failure_falls_back_to_coturn(monkeypatch):
    import live.turn as t
    monkeypatch.setenv("LIVE_CF_TURN_KEY_ID", "k")
    monkeypatch.setenv("LIVE_CF_TURN_API_TOKEN", "x")
    monkeypatch.setenv("LIVE_TURN_SECRET", "s")
    monkeypatch.setenv("LIVE_TURN_URLS", '["turn:turn.exemple.site:3478?transport=udp"]')
    monkeypatch.delenv("LIVE_ICE_SERVERS", raising=False)

    class Boom:
        key_id = "k"

        def ice_servers(self, ttl_s):
            raise RuntimeError("down")
    monkeypatch.setattr(t, "_cf", Boom())
    ice = t.ice_from_env()
    assert ice and ice[0]["urls"] == ["turn:turn.exemple.site:3478?transport=udp"]
