"""Parcours complet « flotte » : 1er essai → GPU en préparation (503 + ticket) → GPU prêt → session sur le
vrai programme GPU (processeur démo) avec image renvoyée → fin de session → place libérée."""
import asyncio

import httpx
import pytest
from aiortc import RTCPeerConnection, RTCSessionDescription

from conftest import ServerThread, free_port
from live.gpu.fleet import FleetLimits, GpuFleet, Tier
from live.server import create_app
from test_fleet import FakeProvider, offer
from test_tunnel_e2e import GreyCamera, mean_colour, wait_ice


@pytest.mark.asyncio
async def test_fleet_wait_then_live_then_slot_released(tmp_path, worker):
    fp = FakeProvider([offer(1, loc="Singapore, SG")])
    fp.status = lambda iid: type("S", (), {"running": True, "endpoint": worker.url, "detail": "ok", "usd_per_hour": None})()
    fleet = GpuFleet({"fake": fp}, tmp_path / "fleet.json", image="img", limits=FleetLimits(spare_nodes=0),
                     tiers={"standard": Tier("standard", "Standard", "sd-turbo", 24, 2, 1.0)})
    port = free_port()
    with ServerThread(create_app(engines={}, gpu=False, fleet=fleet, access_token=""), port) as console:
        async with httpx.AsyncClient(base_url=console.url, timeout=30) as http:
            cat = (await http.get("/api/catalog")).json()
            assert cat["fleet"] == [{"key": "flotte:standard", "name": "Standard"}]

            r = await http.post("/api/sessions", json={"engine": "flotte:standard"})
            assert r.status_code == 503 and r.headers["retry-after"] == "20"
            ticket = r.json()["detail"]["ticket"]
            assert ticket.startswith("ses_") and len(fp.launched) == 1

            for n in fleet.nodes.values():
                n.token = "tok"                        # le programme GPU de test attend ce jeton
            fleet.tick()                               # le GPU démarre et répond « prêt »
            s = (await http.post("/api/sessions", json={"engine": "flotte:standard", "ticket": ticket})).json()
            assert s["id"] == ticket and s["engine"].startswith("node:")
            assert s["usd_per_minute"] == round(0.5 / 60 / 2, 4)   # prix du GPU partagé entre ses places
            assert fleet.node_of(ticket) is not None

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
            assert abs(colour - 128).max() > 5        # l'image traitée revient bien

            assert (await http.get("/api/fleet")).json()["nodes"][0]["users"] == 1
            await http.delete(f"/api/sessions/{s['id']}")
            assert fleet.node_of(ticket) is None       # place libérée sur le GPU
            await pub.close()
            await view.close()
