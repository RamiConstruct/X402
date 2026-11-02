"""Diffusion directe vers TikTok, YouTube, Twitch, Kick… (RTMP/RTMPS) depuis le worker.

Le worker reçoit la caméra (vidéo + micro) du téléphone, transforme la vidéo, puis pousse
lui-même le flux final vers la plateforme : aucun PC ni OBS n'est nécessaire.

* Vidéo : images transformées, mises au format demandé (ex. 720x1280 vertical pour TikTok)
  sans déformation (bandes noires), encodées en H.264 (NVENC si disponible sur le GPU, sinon x264).
* Son : le micro du téléphone, ré-échantillonné et encodé en AAC.
* Horodatage sur l'horloge réelle : le son reste synchronisé même si le GPU saute des images.
"""
from __future__ import annotations

import asyncio
import fractions
import logging
import os
import time

import av
import numpy as np

log = logging.getLogger("live.worker.rtmp")
MS = fractions.Fraction(1, 1000)


def mask_url(url: str) -> str:
    """Masque la clé de stream dans les journaux."""
    head, _, _ = url.rpartition("/")
    return f"{head}/***" if head else "***"


def fit_canvas(rgb: np.ndarray, width: int, height: int) -> np.ndarray:
    """Redimensionne sans déformer et centre sur un fond noir (letterbox / pillarbox)."""
    h, w = rgb.shape[:2]
    scale = min(width / w, height / h)
    nw, nh = max(2, int(w * scale) // 2 * 2), max(2, int(h * scale) // 2 * 2)
    frame = av.VideoFrame.from_ndarray(rgb, format="rgb24").reformat(width=nw, height=nh)
    small = frame.to_ndarray(format="rgb24")
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    y, x = (height - nh) // 2, (width - nw) // 2
    canvas[y:y + nh, x:x + nw] = small
    return canvas


def _video_codec() -> str:
    pref = os.environ.get("WORKER_RTMP_CODEC")
    if pref:
        return pref
    try:
        av.codec.Codec("h264_nvenc", "w")
        return "h264_nvenc" if os.environ.get("WORKER_PROCESSOR") == "streamdiffusion" else "libx264"
    except Exception:  # noqa: BLE001
        return "libx264"


class RtmpPusher:
    def __init__(self, url: str, width: int = 720, height: int = 1280, fps: int = 30,
                 video_kbps: int = 3000, audio_kbps: int = 128) -> None:
        self.url, self.width, self.height, self.fps = url, width, height, fps
        self.video_kbps, self.audio_kbps = video_kbps, audio_kbps
        self.container = None
        self.vstream = self.astream = None
        self.t0: float | None = None
        self.resampler = av.AudioResampler(format="fltp", layout="stereo", rate=48000)
        self.tasks: list[asyncio.Task] = []
        self.stats = {"video_frames": 0, "audio_frames": 0, "error": None, "started": False}
        self._lock = asyncio.Lock()

    def _open(self) -> None:
        fmt = "flv"
        self.container = av.open(self.url, mode="w", format=fmt, options={"rw_timeout": "10000000"})
        codec = _video_codec()
        self.vstream = self.container.add_stream(codec, rate=self.fps)
        self.vstream.width, self.vstream.height, self.vstream.pix_fmt = self.width, self.height, "yuv420p"
        self.vstream.bit_rate = self.video_kbps * 1000
        self.vstream.time_base = MS
        self.vstream.codec_context.options = ({"preset": "p3", "tune": "ll", "g": str(self.fps * 2)} if codec == "h264_nvenc"
                                              else {"preset": "veryfast", "tune": "zerolatency", "g": str(self.fps * 2)})
        self.astream = self.container.add_stream("aac", rate=48000)
        self.astream.layout = "stereo"
        self.astream.bit_rate = self.audio_kbps * 1000
        self.astream.time_base = fractions.Fraction(1, 48000)
        self.t0 = time.monotonic()
        self.stats["started"] = True
        log.info("diffusion démarrée vers %s (%s)", mask_url(self.url), codec)

    def _now_ms(self) -> int:
        return int((time.monotonic() - (self.t0 or time.monotonic())) * 1000)

    async def _mux(self, packets) -> None:
        async with self._lock:
            for p in packets:
                self.container.mux(p)

    async def _video_loop(self, track) -> None:
        last_pts = -1
        while True:
            frame = await track.recv()
            if self.container is None:
                self._open()
            canvas = fit_canvas(frame.to_ndarray(format="rgb24"), self.width, self.height)
            vf = av.VideoFrame.from_ndarray(canvas, format="rgb24").reformat(format="yuv420p")
            pts = max(self._now_ms(), last_pts + 1)
            vf.pts, vf.time_base, last_pts = pts, MS, pts
            await self._mux(self.vstream.encode(vf))
            self.stats["video_frames"] += 1

    async def _audio_loop(self, track) -> None:
        samples = None
        while True:
            frame = await track.recv()
            if self.container is None:
                continue  # le son démarre avec la première image vidéo
            if samples is None:
                samples = int(self._now_ms() * 48)  # aligne le son sur l'horloge de la vidéo
            frame.pts = None
            for rf in self.resampler.resample(frame):
                rf.pts, rf.time_base = samples, fractions.Fraction(1, 48000)
                samples += rf.samples
                await self._mux(self.astream.encode(rf))
                self.stats["audio_frames"] += 1

    def start(self, video_track, audio_track=None) -> None:
        async def guard(coro):
            try:
                await coro
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - fin de flux ou plateforme injoignable
                if not self.stats["error"]:
                    self.stats["error"] = f"{type(e).__name__}: {e}"[:300]
                log.warning("diffusion interrompue : %s", self.stats["error"])
        self.tasks.append(asyncio.ensure_future(guard(self._video_loop(video_track))))
        if audio_track is not None:
            self.tasks.append(asyncio.ensure_future(guard(self._audio_loop(audio_track))))

    async def stop(self) -> None:
        for t in self.tasks:
            t.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.container is not None:
            try:
                async with self._lock:
                    for s in (self.vstream, self.astream):
                        for p in s.encode(None):
                            self.container.mux(p)
                    self.container.close()
            except Exception:  # noqa: BLE001
                pass
            self.container = None
