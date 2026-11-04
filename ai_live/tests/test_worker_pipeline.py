"""Lots 0, 1 et 2 du worker : chronométrage par étape, chemin tenseur de StreamDiffusion,
encodage unique avec un fil d'envoi par plateforme (panne ou silence d'une plateforme isolés)."""
import asyncio
import json
import shutil
import socket
import subprocess
import sys
import threading
import time
import types

import httpx
import numpy as np
import pytest
from aiortc import RTCPeerConnection, RTCSessionDescription

from conftest import free_port
from live.worker.metrics import StageTimer
from live.worker.rtmp import _Output, mask_url, scrub
from test_broadcast_e2e import Tone
from test_tunnel_e2e import GreyCamera, wait_ice

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg absent")
H = {"Authorization": "Bearer tok"}


# --- lot 0 : chronomètre --------------------------------------------------------------------------
def test_stage_timer_summary():
    t = StageTimer(window=100)
    for ms in range(1, 101):
        t.add("model", float(ms))
    t.add("pre", 2.0)
    s = t.summary()
    assert s["model"]["n"] == 100 and s["model"]["avg_ms"] == 50.5 and s["model"]["max_ms"] == 100.0
    assert 94 <= s["model"]["p95_ms"] <= 96
    assert s["pre"] == {"avg_ms": 2.0, "p95_ms": 2.0, "max_ms": 2.0, "n": 1}
    assert "model 50.5/" in t.line()


def test_stage_timer_window_and_threads():
    t = StageTimer(window=10)

    def work():
        for _ in range(500):
            with t.measure("x"):
                pass
            t.summary()  # lecture concurrente pendant les écritures

    threads = [threading.Thread(target=work) for _ in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert t.summary()["x"]["n"] == 10


# --- lot 2 : unités ---------------------------------------------------------------------------------
def test_scrub_removes_stream_keys():
    url = "rtmps://live.example.com/app/sk_live_SECRET123"
    msg = f"OSError: [Errno 5] I/O error: '{url}' (clé sk_live_SECRET123)"
    clean = scrub(msg, [url])
    assert "SECRET123" not in clean and mask_url(url) in clean


def test_output_drops_backlog_and_waits_for_keyframe():
    o = _Output("rtmp://h/app/KEY", 0, max_queue=2)
    o._thread = threading.current_thread()  # simule un fil d'envoi en vie, sans réseau
    for i in range(3):
        o.offer(("v", b"x", i, i, None, False))
    assert o.stats["dropped"] == 2 and o._resync is True
    assert o._q.qsize() == 1 and o._q.get_nowait()[2] == 2  # seul le paquet le plus récent reste


# --- lot 1 : chemin tenseur (faux StreamDiffusion, torch CPU) --------------------------------------------
class FakeWrapper:
    instances: list = []

    def __init__(self, **kw):
        self.kw, self.device, self.inputs = kw, "cpu", []
        FakeWrapper.instances.append(self)

    def prepare(self, **kw):
        pass

    def update_stream_params(self, **kw):
        pass

    def __call__(self, image):
        self.inputs.append(image)
        if self.kw["output_type"] == "pt":  # comme le fork Daydream : (1, 3, H, W) dans [0, 1], sur le GPU
            return image.clone()
        return image  # chemin PIL : renvoie l'image redimensionnée


@pytest.fixture
def fake_streamdiffusion(monkeypatch):
    mod = types.ModuleType("streamdiffusion")
    mod.StreamDiffusionWrapper = FakeWrapper
    monkeypatch.setitem(sys.modules, "streamdiffusion", mod)
    FakeWrapper.instances.clear()
    return FakeWrapper


@pytest.mark.parametrize("tensor_io", ["0", "1"])
def test_streamdiffusion_paths_resize_and_time(fake_streamdiffusion, monkeypatch, tensor_io):
    if tensor_io == "1":
        pytest.importorskip("torch")
    pytest.importorskip("PIL")
    from live.worker.processors import StreamDiffusionProcessor

    monkeypatch.setenv("SD_TENSOR_IO", tensor_io)
    p = StreamDiffusionProcessor({"width": 64, "height": 48})
    p.timer = StageTimer()
    w = fake_streamdiffusion.instances[-1]
    assert w.kw["output_type"] == ("pt" if tensor_io == "1" else "pil")
    rgb = np.zeros((240, 320, 3), np.uint8)
    rgb[:, :160] = (200, 100, 50)  # moitié gauche colorée
    out = p.process(rgb)
    assert out.shape == (48, 64, 3) and out.dtype == np.uint8
    assert np.abs(out[24, 10].astype(int) - (200, 100, 50)).max() <= 2  # couleur conservée à gauche
    assert np.abs(out[24, 54].astype(int)).max() <= 2  # noir à droite
    if tensor_io == "1":
        x = w.inputs[-1]
        assert tuple(x.shape) == (1, 3, 48, 64) and 0.0 <= float(x.min()) and float(x.max()) <= 1.0
    assert {"sd_pre", "sd_model", "sd_post"} <= set(p.timer.summary())


def test_tensor_to_rgb_accepts_fallback_shapes():
    torch = pytest.importorskip("torch")
    from live.worker.processors import tensor_to_rgb

    chw = torch.full((1, 3, 4, 5), 0.5)
    assert tensor_to_rgb(chw).shape == (4, 5, 3) and tensor_to_rgb(chw)[0, 0, 0] == 128
    fallback = torch.zeros((1, 4, 5, 3), dtype=torch.uint8)  # image noire du filtre de sécurité
    assert tensor_to_rgb(fallback).shape == (4, 5, 3)


# --- lot 2 : bout à bout, directement sur le worker ----------------------------------------------------
async def publish(http, worker, urls):
    s = (await http.post(f"{worker.url}/v1/streams", headers=H,
                         json={"params": {"prompt": "x", "output_size": "720x1280"}, "output_rtmp_urls": urls})).json()
    pc = RTCPeerConnection()
    pc.addTrack(GreyCamera())
    pc.addTrack(Tone())
    await pc.setLocalDescription(await pc.createOffer())
    await wait_ice(pc)
    r = await http.post(s["whip_url"], content=pc.localDescription.sdp,
                        headers={**H, "Content-Type": "application/sdp"})
    assert r.status_code == 201, r.text
    await pc.setRemoteDescription(RTCSessionDescription(sdp=r.text, type="answer"))
    return s["id"], pc


def listen(port, out, seconds):
    return subprocess.Popen(["ffmpeg", "-loglevel", "error", "-listen", "1", "-i", f"rtmp://127.0.0.1:{port}/app/BON",
                             "-c", "copy", "-t", str(seconds), "-y", str(out)])


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
                       capture_output=True, text=True, check=True)
    return {st["codec_type"]: st for st in json.loads(r.stdout)["streams"]}


@needs_ffmpeg
@pytest.mark.asyncio
@pytest.mark.parametrize("isolated", ["auto", "0"])  # ffmpeg isolé par plateforme, ou repli PyAV direct
async def test_dead_platform_does_not_stop_the_others(worker, tmp_path, monkeypatch, isolated):
    monkeypatch.setenv("WORKER_RTMP_SUBPROCESS", isolated)
    dead, good = free_port(), free_port()  # « dead » : personne n'écoute (connexion refusée)
    out = tmp_path / "bon.flv"
    lst = listen(good, out, 4)
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            sid, pc = await publish(http, worker, [f"rtmp://127.0.0.1:{dead}/app/MORTE_SECRETE",
                                                   f"rtmp://127.0.0.1:{good}/app/BON"])
            await asyncio.get_running_loop().run_in_executor(None, lst.wait, 30)
            for _ in range(50):  # l'erreur de la plateforme morte remonte dès que ffmpeg a abandonné
                info = (await http.get(f"{worker.url}/v1/streams/{sid}", headers=H)).json()
                if info["broadcast"]["targets"][0]["error"]:
                    break
                await asyncio.sleep(0.1)
            await http.delete(f"{worker.url}/v1/streams", params={"id": sid}, headers=H)
            await pc.close()
    finally:
        if lst.poll() is None:
            lst.kill()
    kinds = probe(out)
    assert kinds["video"]["codec_name"] == "h264" and (kinds["video"]["width"], kinds["video"]["height"]) == (720, 1280)
    assert kinds["audio"]["codec_name"] == "aac"
    b = info["broadcast"]
    assert b["started"] and b["video_frames"] > 0 and b["codec"] == "libx264"
    morte, bonne = b["targets"]
    # (la « plateforme » de test raccroche après 4 s : une erreur de fin de flux est normale ici)
    assert morte["error"] and bonne["started"] and bonne["video_packets"] > 0
    assert morte["isolated"] is (isolated == "auto")
    assert "MORTE_SECRETE" not in json.dumps(info)  # la clé n'apparaît jamais, même dans l'erreur
    # Lot 0 : les durées par étape sont exposées.
    assert {"to_rgb", "process", "from_rgb", "rtmp_prep", "rtmp_encode"} <= set(info["timings"])
    assert "frames_dropped" in info["stats"]


@needs_ffmpeg
@pytest.mark.asyncio
async def test_silent_platform_does_not_freeze_the_worker(worker, tmp_path):
    hole = socket.socket()  # « plateforme » qui accepte la connexion puis ne répond jamais
    hole.bind(("127.0.0.1", 0))
    hole.listen(5)
    good = free_port()
    out = tmp_path / "bon.flv"
    lst = listen(good, out, 4)
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            sid, pc = await publish(http, worker, [f"rtmp://127.0.0.1:{hole.getsockname()[1]}/app/MUETTE",
                                                   f"rtmp://127.0.0.1:{good}/app/BON"])
            worst = 0.0
            while lst.poll() is None:  # pendant toute la diffusion, l'API du worker répond vite
                t0 = time.monotonic()
                assert (await http.get(f"{worker.url}/health")).status_code == 200
                worst = max(worst, time.monotonic() - t0)
                await asyncio.sleep(0.2)
            info = (await http.get(f"{worker.url}/v1/streams/{sid}", headers=H)).json()
            t0 = time.monotonic()
            await http.delete(f"{worker.url}/v1/streams", params={"id": sid}, headers=H)
            stop_s = time.monotonic() - t0
            await pc.close()
    finally:
        hole.close()
        if lst.poll() is None:
            lst.kill()
    assert worst < 1.0, f"le worker a été bloqué {worst:.1f} s"
    assert stop_s < 15, "l'arrêt ne doit pas attendre indéfiniment une plateforme muette"
    kinds = probe(out)
    assert kinds["video"]["codec_name"] == "h264" and kinds["audio"]["codec_name"] == "aac"
    muette, bonne = info["broadcast"]["targets"]
    assert muette["isolated"] and bonne["started"] and bonne["video_packets"] > 0
