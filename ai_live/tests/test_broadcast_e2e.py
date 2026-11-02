"""Diffusion directe : téléphone (vidéo + micro) → console → worker → RTMP vers une « plateforme ».
La plateforme est simulée par FFmpeg en écoute RTMP, qui enregistre ce qu'il reçoit ;
on vérifie ensuite le fichier : vidéo H.264 au format vertical + son AAC."""
import asyncio
import fractions
import json
import shutil
import subprocess

import av
import httpx
import numpy as np
import pytest
from aiortc import AudioStreamTrack, RTCPeerConnection, RTCSessionDescription

from conftest import ServerThread, free_port
from live.engine import EngineConfig
from live.server import create_app
from test_tunnel_e2e import GreyCamera, wait_ice

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg absent")


class Tone(AudioStreamTrack):
    """Micro simulé : bip 440 Hz, trames de 20 ms en 48 kHz."""
    def __init__(self):
        super().__init__()
        self.t = 0

    async def recv(self):
        n = 960
        await asyncio.sleep(0.02)
        samples = (np.sin(2 * np.pi * 440 * (np.arange(n) + self.t) / 48000) * 8000).astype(np.int16)
        self.t += n
        f = av.AudioFrame.from_ndarray(samples.reshape(1, -1), format="s16", layout="mono")
        f.sample_rate, f.pts, f.time_base = 48000, self.t, fractions.Fraction(1, 48000)
        return f


@pytest.mark.asyncio
async def test_direct_broadcast_vertical_with_audio(worker, tmp_path):
    rport = free_port()
    out = tmp_path / "recu.flv"
    # « Plateforme » : FFmpeg écoute en RTMP et enregistre sans réencoder.
    listener = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-listen", "1", "-i", f"rtmp://127.0.0.1:{rport}/live/CLE",
                                 "-c", "copy", "-t", "6", "-y", str(out)])
    engines = {"selfhosted": EngineConfig(name="local", base_url=worker.url, api_key="tok", model_id="demo",
                                          use_controlnets=False, supports_output_size=True)}
    port = free_port()
    try:
        with ServerThread(create_app(engines=engines, gpu=False, access_token=""), port) as console:
            async with httpx.AsyncClient(base_url=console.url, timeout=30) as http:
                bad = await http.post("/api/sessions", json={"engine": "selfhosted", "broadcast": {"server_url": "http://x", "stream_key": "k"}})
                assert bad.status_code == 400
                s = (await http.post("/api/sessions", json={"engine": "selfhosted", "broadcast": {
                    "platform": "test", "server_url": f"rtmp://127.0.0.1:{rport}/live", "stream_key": "CLE", "format": "vertical"}})).json()
                assert s["broadcast"][0]["target"].endswith("/***") and "CLE" not in json.dumps(s)  # la clé n'est jamais renvoyée

                pc = RTCPeerConnection()
                pc.addTrack(GreyCamera())
                pc.addTrack(Tone())
                await pc.setLocalDescription(await pc.createOffer())
                await wait_ice(pc)
                r = await http.post(f"/api/sessions/{s['id']}/whip", content=pc.localDescription.sdp,
                                    headers={"Content-Type": "application/sdp"})
                assert r.status_code == 200, r.text
                await pc.setRemoteDescription(RTCSessionDescription(sdp=r.text, type="answer"))
                await asyncio.get_running_loop().run_in_executor(None, listener.wait, 30)
                await http.delete(f"/api/sessions/{s['id']}")
                await pc.close()
    finally:
        if listener.poll() is None:
            listener.kill()

    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(out)],
                                      capture_output=True, text=True, check=True).stdout)
    streams = {st["codec_type"]: st for st in probe["streams"]}
    assert streams["video"]["codec_name"] == "h264"
    assert (streams["video"]["width"], streams["video"]["height"]) == (720, 1280)
    assert streams["audio"]["codec_name"] == "aac"


@pytest.mark.asyncio
async def test_multistream_two_platforms(worker, tmp_path):
    ports = [free_port(), free_port()]
    outs = [tmp_path / "a.flv", tmp_path / "b.flv"]
    listeners = [subprocess.Popen(["ffmpeg", "-loglevel", "error", "-listen", "1", "-i", f"rtmp://127.0.0.1:{p}/app/K{i}",
                                   "-c", "copy", "-t", "4", "-y", str(o)]) for i, (p, o) in enumerate(zip(ports, outs))]
    engines = {"selfhosted": EngineConfig(name="local", base_url=worker.url, api_key="tok", model_id="demo",
                                          use_controlnets=False, supports_output_size=True)}
    port = free_port()
    try:
        with ServerThread(create_app(engines=engines, gpu=False, access_token=""), port) as console:
            async with httpx.AsyncClient(base_url=console.url, timeout=30) as http:
                dests = [{"platform": f"p{i}", "server_url": f"rtmp://127.0.0.1:{p}/app", "stream_key": f"K{i}", "format": "horizontal"}
                         for i, p in enumerate(ports)]
                mixed = [dict(dests[0]), {**dests[1], "format": "vertical"}]
                assert (await http.post("/api/sessions", json={"engine": "selfhosted", "broadcast": mixed})).status_code == 400
                s = (await http.post("/api/sessions", json={"engine": "selfhosted", "broadcast": dests})).json()
                assert [b["platform"] for b in s["broadcast"]] == ["p0", "p1"]
                pc = RTCPeerConnection()
                pc.addTrack(GreyCamera())
                pc.addTrack(Tone())
                await pc.setLocalDescription(await pc.createOffer())
                await wait_ice(pc)
                r = await http.post(f"/api/sessions/{s['id']}/whip", content=pc.localDescription.sdp,
                                    headers={"Content-Type": "application/sdp"})
                await pc.setRemoteDescription(RTCSessionDescription(sdp=r.text, type="answer"))
                for lst in listeners:
                    await asyncio.get_running_loop().run_in_executor(None, lst.wait, 30)
                await http.delete(f"/api/sessions/{s['id']}")
                await pc.close()
    finally:
        for lst in listeners:
            if lst.poll() is None:
                lst.kill()
    for o in outs:
        probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(o)],
                                          capture_output=True, text=True, check=True).stdout)
        kinds = {st["codec_type"]: st for st in probe["streams"]}
        assert (kinds["video"]["width"], kinds["video"]["height"]) == (1280, 720) and kinds["audio"]["codec_name"] == "aac"
