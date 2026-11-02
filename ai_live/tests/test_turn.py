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
