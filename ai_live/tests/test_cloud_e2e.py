"""Parcours complet « GPU loué » : devis → location → worker prêt → live via le moteur cloud → libération.
Le fournisseur est simulé ; le worker est réel (processeur démo) et le WebRTC aussi."""
import asyncio

import httpx
import pytest
from aiortc import RTCPeerConnection, RTCSessionDescription

from conftest import ServerThread, free_port
from live.gpu.manager import GpuManager, Limits
from live.server import create_app
from test_gpu import FakeProvider
from test_tunnel_e2e import GreyCamera, mean_colour, wait_ice


@pytest.mark.asyncio
async def test_rent_then_live_then_release(tmp_path, worker):
    fp = FakeProvider(endpoint=worker.url, price=0.6)
    gpu = GpuManager({"fake": fp}, tmp_path / "gpu.json", image="ghcr.io/moi/live-worker:1", limits=Limits())
    # Le faux fournisseur renvoie le vrai worker local ; son jeton est celui du test.
    gpu.providers["fake"].launch = lambda offer, image, env, label: fp.launched.append(env) or "i1"
    port = free_port()
    with ServerThread(create_app(engines={}, gpu=gpu, access_token=""), port) as console:
        async with httpx.AsyncClient(base_url=console.url, timeout=30) as http:
            cat = (await http.get("/api/catalog")).json()
            assert cat["gpu_rental"] and cat["gpu_image_configured"] and len(cat["models"]) == 3
            assert (await http.post("/api/sessions", json={"engine": "cloud"})).status_code == 409  # rien de loué / pas prêt

            q = (await http.post("/api/gpu/quote", json={"model_key": "sd-turbo"})).json()
            assert q["offers"][0]["gpu"] == "RTX 5090" and q["offers"][0]["price_per_min"] == 0.01
            r = (await http.post("/api/gpu/rent", json={"offer_key": q["offers"][0]["key"], "model_key": "sd-turbo"})).json()
            assert r["state"] == "starting" and "token" not in r
            gpu.rental.token = "tok"  # le worker de test attend ce jeton

            st = (await http.get("/api/gpu/rental")).json()["rental"]
            assert st["state"] == "ready", st

            s = (await http.post("/api/sessions", json={"engine": "cloud"})).json()
            assert s["engine"].startswith("cloud:") and s["usd_per_minute"] == 0.01
            pub = RTCPeerConnection()
            pub.addTrack(GreyCamera())
            await pub.setLocalDescription(await pub.createOffer())
            await wait_ice(pub)
            a = await http.post(f"/api/sessions/{s['id']}/whip", content=pub.localDescription.sdp,
                                headers={"Content-Type": "application/sdp"})
            assert a.status_code == 200, a.text
            await pub.setRemoteDescription(RTCSessionDescription(sdp=a.text, type="answer"))

            view = RTCPeerConnection()
            view.addTransceiver("video", direction="recvonly")
            got = asyncio.get_running_loop().create_future()
            view.on("track", lambda t: got.done() or got.set_result(t))
            await view.setLocalDescription(await view.createOffer())
            await wait_ice(view)
            for _ in range(40):
                w = await http.post(f"/api/sessions/{s['id']}/whep", content=view.localDescription.sdp,
                                    headers={"Content-Type": "application/sdp"})
                if w.status_code == 200:
                    break
                await asyncio.sleep(0.25)
            await view.setRemoteDescription(RTCSessionDescription(sdp=w.text, type="answer"))
            colour = await mean_colour(await asyncio.wait_for(got, 10))
            assert abs(colour - 128).max() > 5

            rel = (await http.delete("/api/gpu/rental")).json()["rental"]
            assert rel["state"] == "released" and fp.destroyed == ["i1"]
            assert (await http.get(f"/api/sessions/{s['id']}")).json()["ended"]  # la session est coupée avec le GPU
            await pub.close()
            await view.close()
