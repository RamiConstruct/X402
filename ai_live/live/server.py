"""Serveur console AI LIVE.

* Garde les clés API côté serveur (le navigateur ne les voit jamais).
* Relaie les échanges SDP WHIP/WHEP vers le moteur choisi (Daydream ou worker auto-hébergé) ;
  la vidéo elle-même circule directement entre le navigateur et le moteur.
* Tient l'état de scène, applique les commandes vocales, mesure la durée et le coût.
* Fournit une page « sortie » pour OBS, protégée par une clé aléatoire (pas de connexion requise).
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import Body, FastAPI, Header, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .commands import apply_command, set_preset
from .engine import EngineConfig, EngineError, StreamEngine
from .gpu.catalog import MODELS
from .gpu.manager import GpuError, GpuManager, Limits
from .scene import CHARACTERS, DECORS, STYLES, SceneHistory

STATIC = Path(__file__).parent / "static"


def engines_from_env() -> dict[str, EngineConfig]:
    def f(name: str) -> float | None:
        v = os.environ.get(name)
        return float(v) if v else None
    return {
        "daydream": EngineConfig(
            name="Daydream (API hébergée)", base_url=os.environ.get("DAYDREAM_BASE_URL", "https://api.daydream.live"),
            api_key=os.environ.get("DAYDREAM_API_KEY", ""), model_id=os.environ.get("DAYDREAM_MODEL", "stabilityai/sdxl-turbo"),
            usd_per_minute=f("DAYDREAM_USD_PER_MIN")),
        "selfhosted": EngineConfig(
            name="Mon GPU (StreamDiffusion auto-hébergé)", base_url=os.environ.get("SELFHOST_URL", "http://127.0.0.1:8890"),
            api_key=os.environ.get("SELFHOST_TOKEN", "local"), model_id=os.environ.get("SELFHOST_MODEL", "stabilityai/sd-turbo"),
            usd_per_minute=f("SELFHOST_USD_PER_MIN"), use_controlnets=os.environ.get("SELFHOST_CONTROLNETS", "0") == "1",
            supports_output_size=True),
    }


def gpu_manager_from_env() -> GpuManager | None:
    from .gpu.providers import ProviderError, RunPodProvider, VastProvider
    providers = {}
    for name, cls, var in (("vast", VastProvider, "VAST_API_KEY"), ("runpod", RunPodProvider, "RUNPOD_API_KEY")):
        if os.environ.get(var):
            try:
                providers[name] = cls(os.environ[var])
            except ProviderError:
                pass
    if not providers:
        return None
    data = Path(os.environ.get("LIVE_DATA_DIR", Path.cwd() / "data"))
    limits = Limits(max_usd_per_hour=float(os.environ.get("LIVE_GPU_MAX_USD_H", "1.5")),
                    idle_minutes=float(os.environ.get("LIVE_GPU_IDLE_MIN", "10")),
                    max_hours=float(os.environ.get("LIVE_GPU_MAX_HOURS", "4")),
                    owner_mode=os.environ.get("LIVE_OWNER_MODE", "1") == "1")
    from .turn import ice_from_env

    def worker_env() -> dict[str, str]:  # identifiants TURN valables toute la durée de location
        ice = ice_from_env(label="worker", ttl_s=int((limits.max_hours + 1) * 3600))
        return {"WORKER_ICE_SERVERS": json.dumps(ice)} if ice else {}
    return GpuManager(providers, data / "gpu_state.json", image=os.environ.get("LIVE_WORKER_IMAGE", ""),
                      limits=limits, worker_env=worker_env)


@dataclass
class Session:
    id: str
    out_key: str
    engine_key: str
    stream_id: str
    whip_url: str
    history: SceneHistory
    whep_url: str | None = None
    created: float = field(default_factory=time.time)
    connected_at: float | None = None
    ended_at: float | None = None
    end_reason: str | None = None
    log: list = field(default_factory=list)
    broadcast: dict | None = None        # {"platform", "target" (clé masquée), "format"} — la clé n'est jamais conservée

    def minutes(self) -> float:
        if not self.connected_at:
            return 0.0
        return ((self.ended_at or time.time()) - self.connected_at) / 60

    def note(self, msg: str) -> None:
        self.log.append({"at": time.time(), "message": msg})
        self.log = self.log[-100:]


FORMATS = {"vertical": "720x1280", "horizontal": "1280x720", "carre": "720x720"}


def broadcast_url(b: dict) -> tuple[str, dict]:
    """Construit l'URL RTMP(S) à partir du serveur et de la clé ; renvoie aussi une vue sans la clé."""
    server = str(b.get("server_url", "")).strip().rstrip("/")
    key = str(b.get("stream_key", "")).strip()
    if not server.startswith(("rtmp://", "rtmps://")):
        raise HTTPException(400, "l'adresse du serveur doit commencer par rtmp:// ou rtmps://")
    if not key or "/" in key or " " in key:
        raise HTTPException(400, "clé de stream manquante ou invalide")
    fmt = b.get("format", "vertical")
    if fmt not in FORMATS:
        raise HTTPException(400, "format inconnu (vertical, horizontal, carre)")
    return f"{server}/{key}", {"platform": str(b.get("platform", "autre"))[:30], "target": f"{server}/***", "format": fmt}


class Cmd(BaseModel):
    text: str


class Preset(BaseModel):
    kind: str
    key: str | None = None


class Strength(BaseModel):
    value: int


class Rent(BaseModel):
    offer_key: str
    model_key: str


def create_app(engines: dict[str, EngineConfig] | None = None, engine_factory=StreamEngine,
               access_token: str | None = None, max_minutes: float | None = None,
               gpu: GpuManager | None | bool = True, ice_servers: list | None = None) -> FastAPI:
    configs = dict(engines or engines_from_env())
    gpu = gpu_manager_from_env() if gpu is True else (gpu or None)
    from .turn import ice_from_env
    # Identifiants TURN régénérés à chaque demande (ils expirent) ; le secret reste ici.
    ice_provider = (lambda: list(ice_servers)) if ice_servers is not None else ice_from_env
    access_token = access_token if access_token is not None else os.environ.get("LIVE_ACCESS_TOKEN", "")
    max_minutes = max_minutes if max_minutes is not None else float(os.environ.get("LIVE_MAX_SESSION_MIN", "60"))
    clients = {k: engine_factory(c) for k, c in configs.items()}
    sessions: dict[str, Session] = {}
    by_out: dict[str, Session] = {}
    lock = threading.Lock()
    app = FastAPI(title="AI LIVE")

    def guard(x_live_token: str) -> None:
        if access_token and not secrets.compare_digest(x_live_token, access_token):
            raise HTTPException(401, "jeton d'accès requis")

    def get(sid: str) -> Session:
        s = sessions.get(sid)
        if not s:
            raise HTTPException(404, "session introuvable")
        return s

    def enforce_cap(s: Session) -> None:
        if s.ended_at is None and s.minutes() > max_minutes:
            end(s, f"durée maximale atteinte ({max_minutes:.0f} min)")

    def end(s: Session, reason: str) -> None:
        if s.ended_at is None:
            s.ended_at, s.end_reason = time.time(), reason
            clients[s.engine_key].delete(s.stream_id)
            s.note(f"session terminée : {reason}")

    def view(s: Session) -> dict:
        cfg = configs[s.engine_key]
        mins = s.minutes()
        return {"id": s.id, "engine": s.engine_key, "engine_name": cfg.name, "model": cfg.model_id,
                "out_url": f"/output.html?k={s.out_key}", "connected": s.connected_at is not None,
                "ended": s.ended_at is not None, "end_reason": s.end_reason, "minutes": round(mins, 2),
                "usd_per_minute": cfg.usd_per_minute,
                "estimated_cost_usd": round(mins * cfg.usd_per_minute, 4) if cfg.usd_per_minute is not None else None,
                "max_minutes": max_minutes, "scene": s.history.current.describe(), "log": s.log[-20:],
                "broadcast": s.broadcast}

    def touch(s: Session) -> None:
        if gpu and s.engine_key.startswith("cloud:") and s.ended_at is None:
            gpu.touch()

    def push(s: Session) -> None:
        touch(s)
        if s.ended_at is not None:
            raise HTTPException(410, "session terminée")
        try:
            clients[s.engine_key].update(s.stream_id, s.history.current)
        except EngineError as e:
            s.note(f"mise à jour moteur échouée : {e}")
            raise HTTPException(502, str(e)) from e

    @app.get("/api/catalog")
    def catalog():
        pick = lambda c: [{"key": k, "label": v["label"]} for k, v in c.items()]  # noqa: E731
        return {"characters": pick(CHARACTERS), "decors": pick(DECORS), "styles": pick(STYLES),
                "engines": [{"key": k, "name": c.name, "model": c.model_id, "configured": bool(c.api_key),
                             "usd_per_minute": c.usd_per_minute} for k, c in configs.items() if not k.startswith("cloud:")],
                "access_required": bool(access_token), "ice_servers": ice_provider(), "gpu_rental": gpu is not None,
                "gpu_image_configured": bool(gpu and gpu.image),
                "models": [{"key": m.key, "label": m.label, "min_vram_gb": m.min_vram_gb, "notes": m.notes,
                            "fps_estimate": m.fps_estimate} for m in MODELS.values()]}

    # --- Location de GPU (Vast.ai / RunPod) ---
    def need_gpu() -> GpuManager:
        if gpu is None:
            raise HTTPException(400, "location GPU non configurée (VAST_API_KEY ou RUNPOD_API_KEY)")
        return gpu

    @app.post("/api/gpu/quote")
    def gpu_quote(body: dict = Body(...), x_live_token: str = Header(default="")):
        guard(x_live_token)
        try:
            return need_gpu().quote(body.get("model_key", ""))
        except GpuError as e:
            raise HTTPException(400, str(e)) from e

    @app.post("/api/gpu/rent")
    def gpu_rent(r: Rent, x_live_token: str = Header(default="")):
        guard(x_live_token)
        m = need_gpu()
        if not m.image:
            raise HTTPException(400, "LIVE_WORKER_IMAGE non défini : image Docker du worker à publier d'abord")
        try:
            m.rent(r.offer_key, r.model_key)
        except GpuError as e:
            raise HTTPException(400, str(e)) from e
        return m.view()

    @app.get("/api/gpu/rental")
    def gpu_rental(x_live_token: str = Header(default="")):
        guard(x_live_token)
        m = need_gpu()
        m.refresh()
        return {"rental": m.view(), "history": m.history[-10:]}

    @app.delete("/api/gpu/rental")
    def gpu_release(x_live_token: str = Header(default="")):
        guard(x_live_token)
        m = need_gpu()
        for s in sessions.values():
            if s.engine_key.startswith("cloud:") and s.ended_at is None:
                end(s, "GPU libéré")
        try:
            m.release()
        except GpuError as e:
            raise HTTPException(502, str(e)) from e
        return {"rental": m.view()}

    def cloud_engine() -> str:
        m = need_gpu()
        r = m.refresh()
        if r is None or r.state != "ready" or not r.endpoint:
            raise HTTPException(409, "le GPU loué n'est pas encore prêt")
        key = f"cloud:{r.id}"
        if key not in configs:
            model = MODELS[r.model_key]
            configs[key] = EngineConfig(name=f"GPU loué — {r.gpu_name} ({r.provider})", base_url=r.endpoint,
                                        api_key=r.token, model_id=model.model_id, width=model.width, height=model.height,
                                        use_controlnets=model.use_controlnets, usd_per_minute=r.client_price_per_min(),
                                        supports_output_size=True)
            clients[key] = engine_factory(configs[key])
        return key

    @app.post("/api/sessions")
    def create(body: dict = Body(default={}), x_live_token: str = Header(default="")):
        guard(x_live_token)
        key = body.get("engine", "daydream")
        if key == "cloud":
            key = cloud_engine()
        if key not in configs:
            raise HTTPException(400, "moteur inconnu")
        history = SceneHistory()
        rtmp, bview, size = None, None, None
        if body.get("broadcast"):
            rtmp, bview = broadcast_url(body["broadcast"])
            size = FORMATS[bview["format"]]
        try:
            data = clients[key].create(history.current, output_rtmp_url=rtmp, output_size=size)
        except EngineError as e:
            raise HTTPException(502, str(e)) from e
        s = Session(id="ses_" + secrets.token_hex(8), out_key=secrets.token_urlsafe(16), engine_key=key,
                    stream_id=data["id"], whip_url=data["whip_url"], history=history)
        s.broadcast = bview
        s.note(f"flux créé sur {configs[key].name}" + (f" — diffusion directe vers {bview['platform']} ({bview['format']})" if bview else ""))
        with lock:
            sessions[s.id], by_out[s.out_key] = s, s
        return view(s)

    @app.post("/api/sessions/{sid}/whip")
    async def whip(sid: str, request: Request, x_live_token: str = Header(default="")):
        guard(x_live_token)
        s = get(sid)
        offer = (await request.body()).decode()
        try:
            answer, whep_url = await asyncio.to_thread(clients[s.engine_key].whip, s.whip_url, offer)
        except EngineError as e:
            raise HTTPException(502, str(e)) from e
        s.whep_url = whep_url or s.whep_url
        s.connected_at = s.connected_at or time.time()
        s.note("caméra connectée au moteur")
        return Response(answer, media_type="application/sdp")

    async def _whep(s: Session, offer: str) -> Response:
        if not s.whep_url:
            raise HTTPException(409, "la caméra n'est pas encore connectée")
        try:
            answer = await asyncio.to_thread(clients[s.engine_key].whep, s.whep_url, offer)
            return Response(answer, media_type="application/sdp")
        except EngineError as e:
            raise HTTPException(502, str(e)) from e

    @app.post("/api/sessions/{sid}/whep")
    async def whep(sid: str, request: Request, x_live_token: str = Header(default="")):
        guard(x_live_token)
        return await _whep(get(sid), (await request.body()).decode())

    @app.get("/api/sessions/{sid}")
    def state(sid: str, x_live_token: str = Header(default="")):
        guard(x_live_token)
        s = get(sid)
        enforce_cap(s)
        touch(s)
        return view(s)

    @app.post("/api/sessions/{sid}/command")
    def command(sid: str, c: Cmd, x_live_token: str = Header(default="")):
        guard(x_live_token)
        s = get(sid)
        state = lambda: (s.history.current.prompt(), s.history.current.t_index_list(),  # noqa: E731
                         s.history.current.bypass if s.broadcast else None)
        before = state()
        r = apply_command(s.history, c.text)
        s.note(f"« {c.text[:80]} » → {r.message}")
        if r.changed and state() != before:
            push(s)
        return {"ok": r.ok, "message": r.message, "blocked": r.blocked, "session": view(s)}

    @app.post("/api/sessions/{sid}/preset")
    def preset(sid: str, p: Preset, x_live_token: str = Header(default="")):
        guard(x_live_token)
        s = get(sid)
        r = set_preset(s.history, p.kind, p.key)
        if not r.ok:
            raise HTTPException(400, r.message)
        push(s)
        return view(s)

    @app.post("/api/sessions/{sid}/strength")
    def strength(sid: str, v: Strength, x_live_token: str = Header(default="")):
        guard(x_live_token)
        s = get(sid)
        new = s.history.edit()
        new.strength = max(1, min(5, v.value))
        s.history.apply(new)
        push(s)
        return view(s)

    @app.post("/api/sessions/{sid}/bypass")
    def bypass(sid: str, body: dict = Body(...), x_live_token: str = Header(default="")):
        guard(x_live_token)
        s = get(sid)
        new = s.history.edit()
        new.bypass = bool(body.get("on"))
        s.history.apply(new)
        if s.broadcast:
            push(s)  # diffusion directe : pas d'OBS, c'est le moteur qui renvoie l'image originale
        # sinon : aucune requête moteur, la page de sortie OBS devient transparente instantanément
        return view(s)

    @app.delete("/api/sessions/{sid}")
    def stop(sid: str, x_live_token: str = Header(default="")):
        guard(x_live_token)
        s = get(sid)
        end(s, "arrêtée par l'utilisateur")
        return view(s)

    # --- Page de sortie OBS (clé aléatoire, sans jeton) ---
    def out(key: str) -> Session:
        s = by_out.get(key)
        if not s:
            raise HTTPException(404, "sortie introuvable")
        return s

    @app.get("/api/out/{key}")
    def out_state(key: str):
        s = out(key)
        enforce_cap(s)
        sc = s.history.current
        return {"bypass": sc.bypass, "parody": sc.parody, "parody_of": sc.parody_of,
                "connected": s.whep_url is not None, "ended": s.ended_at is not None}

    @app.post("/api/out/{key}/whep")
    async def out_whep(key: str, request: Request):
        return await _whep(out(key), (await request.body()).decode())

    if gpu is not None:
        def reaper():  # libère le GPU inactif même si personne n'ouvre la console
            while True:
                time.sleep(30)
                try:
                    gpu.refresh()
                except Exception:  # noqa: BLE001
                    pass
        threading.Thread(target=reaper, daemon=True, name="gpu-reaper").start()

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    app.state.sessions = sessions
    app.state.gpu = gpu
    return app
