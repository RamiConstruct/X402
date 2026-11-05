"""Catalogue : le programme de démonstration (sans IA) ne s'affiche pas comme « Mon GPU »."""
import httpx

from conftest import ServerThread, free_port
from live.engine import EngineConfig
from live.server import create_app


def test_demo_worker_is_labelled_as_demo(worker):
    engines = {"selfhosted": EngineConfig(name="Mon GPU (StreamDiffusion auto-hébergé)", base_url=worker.url,
                                          api_key="tok", supports_output_size=True),
               "daydream": EngineConfig(name="Daydream (API hébergée)", base_url="https://example.invalid", api_key="k")}
    port = free_port()
    with ServerThread(create_app(engines=engines, gpu=False, fleet=False, access_token="x"), port) as srv:
        cat = httpx.get(f"{srv.url}/api/catalog", timeout=10).json()
    names = {e["key"]: e["name"] for e in cat["engines"]}
    assert names["selfhosted"].startswith("Démo technique")
    assert names["daydream"] == "Daydream (API hébergée)"
    assert cat["access_required"] is True
