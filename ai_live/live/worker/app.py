"""Worker GPU auto-hébergé, compatible avec le protocole de l'API Daydream.

À lancer sur la machine qui possède le GPU (ton Legion, un RTX 5090 loué…) :

    WORKER_TOKEN=secret WORKER_PROCESSOR=streamdiffusion \
    python -m live.worker --host 0.0.0.0 --port 8890

Le serveur console s'y connecte comme à Daydream (même routes, même WHIP/WHEP).
Politique « dernière image » : si le GPU est plus lent que la caméra, les images
intermédiaires sont abandonnées au lieu de s'accumuler (pas de retard croissant).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass, field

import av
from aiortc import MediaStreamTrack, RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaRelay
from fastapi import FastAPI, Header, HTTPException, Request, Response

from .processors import Processor, make_processor
from .rtmp import RtmpPusher, mask_url

log = logging.getLogger("live.worker")


class ProcessedTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, source: MediaStreamTrack, processor: Processor, stats: dict) -> None:
        super().__init__()
        self.source, self.processor, self.stats = source, processor, stats
        self.bypass = False   # True = l'image originale est renvoyée telle quelle (retour à l'original)
        self._latest: av.VideoFrame | None = None
        self._new = asyncio.Event()
        self._reader = asyncio.ensure_future(self._read())

    async def _read(self) -> None:
        try:
            while True:
                self._latest = await self.source.recv()
                self.stats["frames_in"] += 1
                self._new.set()
        except Exception:  # fin du flux source
            self._new.set()

    async def recv(self) -> av.VideoFrame:
        await self._new.wait()
        self._new.clear()
        frame = self._latest
        if frame is None:
            raise asyncio.CancelledError
        if self.bypass:
            self.stats["frames_out"] += 1
            return frame
        t0 = time.perf_counter()
        rgb = frame.to_ndarray(format="rgb24")
        out = await asyncio.get_running_loop().run_in_executor(None, self.processor.process, rgb)
        new = av.VideoFrame.from_ndarray(out, format="rgb24")
        new.pts, new.time_base = frame.pts, frame.time_base
        self.stats["frames_out"] += 1
        self.stats["last_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return new

    def stop(self) -> None:
        self._reader.cancel()
        super().stop()


@dataclass
class Stream:
    id: str
    params: dict
    processor: Processor
    pcs: list = field(default_factory=list)
    output: ProcessedTrack | None = None
    relay: MediaRelay = field(default_factory=MediaRelay)
    stats: dict = field(default_factory=lambda: {"frames_in": 0, "frames_out": 0, "last_ms": None})
    created: float = field(default_factory=time.time)
    rtmp_urls: list = field(default_factory=list)  # diffusion directe (1re = output_rtmp_url de l'API Daydream ; jusqu'à 3)
    output_size: tuple[int, int] = (720, 1280)
    audio: MediaStreamTrack | None = None
    pushers: list = field(default_factory=list)


def ice_config(raw: str | None) -> RTCConfiguration:
    """WORKER_ICE_SERVERS = JSON [{"urls": "turn:host:3478?transport=tcp", "username": "...", "credential": "..."}].
    Indispensable sur les GPU loués derrière un NAT ou sans UDP (RunPod) : la vidéo passe par un relais TURN."""
    servers = [RTCIceServer(urls="stun:stun.l.google.com:19302")]
    for s in json.loads(raw) if raw else []:
        servers.append(RTCIceServer(urls=s["urls"], username=s.get("username"), credential=s.get("credential")))
    return RTCConfiguration(iceServers=servers)


def create_worker_app(token: str | None = None, public_url: str | None = None, warmup: dict | None = None) -> FastAPI:
    token = token if token is not None else os.environ.get("WORKER_TOKEN", "")
    public_url = (public_url or os.environ.get("WORKER_PUBLIC_URL", "")).rstrip("/")
    if warmup is None and os.environ.get("WORKER_WARMUP_PARAMS"):
        warmup = json.loads(os.environ["WORKER_WARMUP_PARAMS"])
    rtc_config = ice_config(os.environ.get("WORKER_ICE_SERVERS"))
    app = FastAPI(title="AI LIVE worker")
    streams: dict[str, Stream] = {}
    warm: dict = {"processor": None, "params": warmup, "state": "en cours" if warmup else "aucun", "error": None}

    @app.on_event("startup")
    async def _warmup():
        """Charge et compile le modèle AVANT le live (TensorRT : plusieurs minutes au premier lancement)."""
        if not warmup:
            return

        async def run():
            try:
                warm["processor"] = await asyncio.get_running_loop().run_in_executor(None, make_processor, dict(warmup))
                warm["state"] = "prêt"
            except Exception as e:  # noqa: BLE001 - remonté par /health
                warm["state"], warm["error"] = "échec", str(e)[:500]
                log.exception("préchauffage échoué")
        asyncio.ensure_future(run())

    def take_processor(params: dict):
        p, w = warm["processor"], warm["params"] or {}
        same = p is not None and all(params.get(k, w.get(k)) == w.get(k) for k in ("model_id", "width", "height"))
        if same:
            warm["processor"] = None
            p.update(params)
            return p
        return make_processor(params)

    def auth(authorization: str) -> None:
        if token and authorization != f"Bearer {token}":
            raise HTTPException(401, "jeton invalide")

    def base(req: Request) -> str:
        return public_url or str(req.base_url).rstrip("/")

    @app.get("/health")
    def health():
        ready = warm["state"] in ("prêt", "aucun") or bool(streams)
        return {"ok": True, "ready": ready, "warmup": warm["state"], "error": warm["error"], "streams": len(streams),
                "processor": os.environ.get("WORKER_PROCESSOR", "demo")}

    @app.post("/v1/streams")
    async def create(req: Request, authorization: str = Header(default="")):
        auth(authorization)
        body = await req.json()
        params = dict(body.get("params") or {})
        sid = "wst_" + secrets.token_hex(12)
        processor = await asyncio.get_running_loop().run_in_executor(None, take_processor, params)
        urls = ([body["output_rtmp_url"]] if body.get("output_rtmp_url") else []) + list(body.get("output_rtmp_urls") or [])
        urls = list(dict.fromkeys(str(u) for u in urls))  # sans doublons, ordre conservé
        if len(urls) > 3:
            raise HTTPException(400, "3 destinations de diffusion au maximum")
        if any(not u.startswith(("rtmp://", "rtmps://")) for u in urls):
            raise HTTPException(400, "les adresses de diffusion doivent commencer par rtmp:// ou rtmps://")
        size = str(params.pop("output_size", "720x1280"))
        try:
            ow, oh = (int(v) for v in size.lower().split("x"))
        except ValueError:
            raise HTTPException(400, "output_size invalide (ex. 720x1280)") from None
        streams[sid] = Stream(id=sid, params=params, processor=processor, rtmp_urls=urls, output_size=(ow, oh))
        return {"id": sid, "whip_url": f"{base(req)}/v1/streams/{sid}/whip", "output_playback_id": sid,
                "pipeline": body.get("pipeline", "streamdiffusion"), "params": params}

    @app.patch("/v1/streams/{sid}")
    async def update(sid: str, req: Request, authorization: str = Header(default="")):
        auth(authorization)
        st = streams.get(sid) or _404()
        params = dict((await req.json()).get("params") or {})
        if "bypass" in params:
            bypass = bool(params.pop("bypass"))
            if st.output is not None:
                st.output.bypass = bypass
        st.params.update(params)
        st.processor.update(params)
        return {"id": sid, "params": st.params}

    @app.get("/v1/streams/{sid}")
    def get(sid: str, authorization: str = Header(default="")):
        auth(authorization)
        st = streams.get(sid) or _404()
        out = {"id": sid, "params": st.params, "stats": st.stats}
        if st.pushers:
            out["broadcast"] = [{"target": mask_url(p.url), **p.stats} for p in st.pushers]
        return out

    @app.post("/v1/streams/{sid}/whip")
    async def whip(sid: str, req: Request, authorization: str = Header(default="")):
        auth(authorization)
        st = streams.get(sid) or _404()
        offer = (await req.body()).decode()
        pc = RTCPeerConnection(configuration=rtc_config)
        st.pcs.append(pc)
        got_video = asyncio.Event()

        @pc.on("track")
        def on_track(track):
            if track.kind == "video" and st.output is None:
                st.output = ProcessedTrack(track, st.processor, st.stats)
                got_video.set()
            elif track.kind == "audio" and st.audio is None:
                st.audio = track

        await pc.setRemoteDescription(RTCSessionDescription(sdp=offer, type="offer"))
        await pc.setLocalDescription(await pc.createAnswer())
        if st.rtmp_urls and st.output is not None and not st.pushers:
            w, h = st.output_size
            for url in st.rtmp_urls:  # un encodeur par plateforme : une plateforme en panne n'arrête pas les autres
                pusher = RtmpPusher(url, width=w, height=h)
                pusher.start(st.relay.subscribe(st.output, buffered=False),
                             st.relay.subscribe(st.audio, buffered=False) if st.audio is not None else None)
                st.pushers.append(pusher)
        return Response(pc.localDescription.sdp, media_type="application/sdp", status_code=201,
                        headers={"Livepeer-Playback-Url": f"{base(req)}/v1/streams/{sid}/whep",
                                 "Location": f"/v1/streams/{sid}/whip"})

    @app.post("/v1/streams/{sid}/whep")
    async def whep(sid: str, req: Request):
        st = streams.get(sid) or _404()
        if st.output is None:
            raise HTTPException(409, "aucun flux entrant pour l'instant")
        offer = (await req.body()).decode()
        pc = RTCPeerConnection(configuration=rtc_config)
        st.pcs.append(pc)
        await pc.setRemoteDescription(RTCSessionDescription(sdp=offer, type="offer"))
        for t in pc.getTransceivers():
            if t.kind == "video":
                pc.addTrack(st.relay.subscribe(st.output, buffered=False))
                break
        await pc.setLocalDescription(await pc.createAnswer())
        return Response(pc.localDescription.sdp, media_type="application/sdp", status_code=201)

    async def _close(st: Stream) -> None:
        for pusher in st.pushers:
            await pusher.stop()
        if st.output:
            st.output.stop()
        for pc in st.pcs:
            await pc.close()

    @app.delete("/v1/streams")
    async def delete(id: str, authorization: str = Header(default="")):
        auth(authorization)
        st = streams.pop(id, None) or _404()
        await _close(st)
        return {"deleted": id}

    @app.on_event("shutdown")
    async def _shutdown():
        for st in list(streams.values()):
            await _close(st)

    return app


def _404():
    raise HTTPException(404, "flux introuvable")
