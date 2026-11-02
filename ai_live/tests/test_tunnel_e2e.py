"""Tunnel complet avec du vrai WebRTC (aiortc) : caméra simulée → serveur console → worker
(processeur « demo ») → sortie OBS. Valide le chemin auto-hébergé sans GPU."""
import asyncio
import fractions

import av
import httpx
import numpy as np
import pytest
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack

from conftest import ServerThread, free_port
from live.engine import EngineConfig
from live.server import create_app


class GreyCamera(VideoStreamTrack):
    async def recv(self):
        pts, tb = await self.next_timestamp()
        f = av.VideoFrame.from_ndarray(np.full((240, 320, 3), 128, np.uint8), format="rgb24")
        f.pts, f.time_base = pts, tb
        return f


async def wait_ice(pc):
    for _ in range(50):
        if pc.iceGatheringState == "complete":
            return
        await asyncio.sleep(0.05)


async def mean_colour(track, n=5):
    vals = []
    for _ in range(n):
        f = await asyncio.wait_for(track.recv(), 10)
        vals.append(f.to_ndarray(format="rgb24").reshape(-1, 3).mean(axis=0))
    return np.mean(vals, axis=0)


@pytest.mark.asyncio
async def test_full_tunnel(worker):
    engines = {"selfhosted": EngineConfig(name="local", base_url=worker.url, api_key="tok",
                                          model_id="stabilityai/sd-turbo", usd_per_minute=0.012, use_controlnets=False)}
    port = free_port()
    with ServerThread(create_app(engines=engines, access_token="pass"), port) as console:
        H = {"X-Live-Token": "pass"}
        async with httpx.AsyncClient(base_url=console.url, timeout=30) as http:
            assert (await http.post("/api/sessions", json={"engine": "selfhosted"})).status_code == 401
            s = (await http.post("/api/sessions", json={"engine": "selfhosted"}, headers=H)).json()
            assert s["engine"] == "selfhosted" and s["out_url"].startswith("/output.html?k=")
            out_key = s["out_url"].split("k=")[1]

            # 1) Publication de la caméra (WHIP via la console)
            pub = RTCPeerConnection()
            pub.addTrack(GreyCamera())
            await pub.setLocalDescription(await pub.createOffer())
            await wait_ice(pub)
            r = await http.post(f"/api/sessions/{s['id']}/whip", content=pub.localDescription.sdp,
                                headers={**H, "Content-Type": "application/sdp"})
            assert r.status_code == 200, r.text
            await pub.setRemoteDescription(RTCSessionDescription(sdp=r.text, type="answer"))

            # 2) Lecture de la sortie IA par la page OBS (clé de sortie, sans jeton)
            view = RTCPeerConnection()
            view.addTransceiver("video", direction="recvonly")
            got = asyncio.get_running_loop().create_future()
            view.on("track", lambda t: got.done() or got.set_result(t))
            await view.setLocalDescription(await view.createOffer())
            await wait_ice(view)
            r = None
            for _ in range(40):  # la première image entrante doit arriver au worker
                r = await http.post(f"/api/out/{out_key}/whep", content=view.localDescription.sdp,
                                    headers={"Content-Type": "application/sdp"})
                if r.status_code == 200:
                    break
                await asyncio.sleep(0.25)
            assert r.status_code == 200, r.text
            await view.setRemoteDescription(RTCSessionDescription(sdp=r.text, type="answer"))
            track = await asyncio.wait_for(got, 10)

            before = await mean_colour(track)
            assert np.abs(before - 128).max() > 5, "la sortie doit être transformée"

            # 3) Commande vocale → mise à jour à chaud du moteur → l'image change
            c = (await http.post(f"/api/sessions/{s['id']}/command", json={"text": "transforme-moi en astronaute"}, headers=H)).json()
            assert c["ok"] and "astronaut" in c["session"]["scene"]["prompt"]
            await asyncio.sleep(0.5)
            after = await mean_colour(track)
            assert np.abs(after - before).max() > 2, "le changement de prompt doit modifier l'image"

            # 4) Retour à l'original : la page OBS le voit instantanément ; caricature → bandeau
            await http.post(f"/api/sessions/{s['id']}/bypass", json={"on": True}, headers=H)
            assert (await http.get(f"/api/out/{out_key}")).json()["bypass"] is True
            await http.post(f"/api/sessions/{s['id']}/command", json={"text": "deviens Macron"}, headers=H)
            o = (await http.get(f"/api/out/{out_key}")).json()
            assert o["parody"] and o["parody_of"] == "Emmanuel Macron" and o["bypass"] is False

            # 5) Mesure et arrêt
            st = (await http.get(f"/api/sessions/{s['id']}", headers=H)).json()
            assert st["connected"] and st["minutes"] > 0 and st["estimated_cost_usd"] is not None
            st = (await http.delete(f"/api/sessions/{s['id']}", headers=H)).json()
            assert st["ended"]
            await pub.close()
            await view.close()
