"""Diffusion directe vers TikTok, YouTube, Twitch, Kick… (RTMP/RTMPS) depuis le worker.

Le worker reçoit la caméra (vidéo + micro) du téléphone, transforme la vidéo, puis pousse
lui-même le flux final vers la plateforme : aucun PC ni OBS n'est nécessaire.

* Vidéo : images transformées, mises au format demandé (ex. 720x1280 vertical pour TikTok)
  sans déformation (bandes noires), encodées en H.264 (NVENC si disponible sur le GPU, sinon x264).
* Son : le micro du téléphone, ré-échantillonné et encodé en AAC.
* Horodatage sur l'horloge réelle : le son reste synchronisé même si le GPU saute des images.

Organisation — chaque image est mise au format et encodée UNE seule fois, quel que soit
le nombre de plateformes :

    image transformée ─▶ fil d'encodage (format + H.264 + AAC)
                                 │ paquets
                   ┌─────────────┼─────────────┐
                   ▼             ▼             ▼
            fil plateforme 1  fil plateforme 2  fil plateforme 3   (connexion + envoi RTMP)

* Rien de ce travail ne tourne sur la boucle asyncio : le WebRTC et l'API du worker restent fluides.
* Une plateforme injoignable, qui coupe ou qui ne répond plus ne bloque que son propre envoi.
  Si elle prend du retard, ses paquets en attente sont abandonnés et elle reprend à la
  prochaine image clé (toutes les 2 s) ; les autres plateformes ne sont pas touchées.

Envoi réseau : PyAV ouvre la connexion RTMP en gardant le verrou global de Python (GIL) ;
une plateforme qui accepte la connexion puis ne répond plus figerait tout le worker. Quand
l'exécutable `ffmpeg` est présent (image Docker du worker, Linux), chaque plateforme passe
donc par son propre petit processus `ffmpeg -c copy` alimenté par un tube : il ne réencode
rien, et il peut être arrêté de force s'il reste bloqué. Sans `ffmpeg`, repli sur l'envoi
direct par PyAV (ancien comportement face à une plateforme muette). `WORKER_RTMP_SUBPROCESS=0`
force ce repli.
"""
from __future__ import annotations

import asyncio
import fractions
import io
import logging
import os
import queue
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import av
import numpy as np

from .metrics import StageTimer, timed

log = logging.getLogger("live.worker.rtmp")
MS = fractions.Fraction(1, 1000)
AUDIO_TB = fractions.Fraction(1, 48000)


def mask_url(url: str) -> str:
    """Masque la clé de stream dans les journaux."""
    head, _, _ = url.rpartition("/")
    return f"{head}/***" if head else "***"


def scrub(message: str, urls: list[str]) -> str:
    """Retire les clés de stream d'un message d'erreur (FFmpeg cite souvent l'adresse complète)."""
    for url in urls:
        message = message.replace(url, mask_url(url))
        key = url.rpartition("/")[2]
        if key:
            message = message.replace(key, "***")
    return message


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


def _ffmpeg_cli() -> str | None:
    """Chemin de l'exécutable ffmpeg pour l'envoi isolé, ou None (repli sur l'envoi direct par PyAV)."""
    if os.environ.get("WORKER_RTMP_SUBPROCESS", "auto") == "0":
        return None
    return shutil.which("ffmpeg")


class _PipeWriter:
    """Tube vers le processus ffmpeg, vu par PyAV comme un fichier non repositionnable."""

    def __init__(self, raw) -> None:
        self.raw = raw

    def write(self, data) -> int:
        view = memoryview(data)
        while view:  # os.write relâche le GIL : un ffmpeg bloqué ne bloque que ce fil
            n = os.write(self.raw.fileno(), view)
            view = view[n:]
        return len(data)


class _Output:
    """Une plateforme : sa connexion RTMP, sa file de paquets déjà encodés et son fil d'envoi."""

    def __init__(self, url: str, index: int, max_queue: int = 150) -> None:  # 150 paquets ≈ 2 s de vidéo + son
        self.url, self.index = url, index
        self._q: queue.Queue = queue.Queue(maxsize=max_queue)
        self._resync = False
        self._dead = False
        self._thread: threading.Thread | None = None
        self._templates: tuple = (None, None)
        self._ffmpeg = _ffmpeg_cli()
        self._proc: subprocess.Popen | None = None
        self._stderr: list[str] = []
        # dropped : paquets jetés parce que la plateforme ne suivait pas (compté par le fil d'encodage) ;
        # skipped : images jetées en attendant une image clé (compté par le fil d'envoi).
        self.stats = {"started": False, "video_packets": 0, "audio_packets": 0, "dropped": 0, "skipped": 0,
                      "error": None, "isolated": self._ffmpeg is not None}

    def begin(self, video_template, audio_template) -> None:
        self._templates = (video_template, audio_template)
        self._thread = threading.Thread(target=self._run, name=f"live-rtmp-{self.index}", daemon=True)
        self._thread.start()

    def offer(self, item: tuple) -> None:
        """Appelé par le fil d'encodage. Ne bloque jamais : si la plateforme ne suit pas, la file est vidée."""
        if self._dead or self._thread is None:
            return
        try:
            self._q.put_nowait(item)
        except queue.Full:
            self.stats["dropped"] += self._drain()
            self._resync = True  # positionné AVANT de remettre un paquet : le fil d'envoi le verra
            try:
                self._q.put_nowait(item)
            except queue.Full:
                self.stats["dropped"] += 1

    def _drain(self) -> int:
        n = 0
        while True:
            try:
                self._q.get_nowait()
                n += 1
            except queue.Empty:
                return n

    @staticmethod
    def _mux(container, stream, item: tuple) -> None:
        _, data, pts, dts, time_base, key = item
        p = av.Packet(data)
        p.pts, p.dts, p.time_base, p.stream = pts, dts, time_base, stream
        p.is_keyframe = key
        container.mux(p)

    def _open(self):
        if self._ffmpeg is None:
            return av.open(self.url, mode="w", format="flv")  # connexion au premier paquet, GIL tenu (voir en-tête)
        # Copie sans réencodage : FLV reçu sur l'entrée standard → même FLV vers la plateforme.
        self._proc = subprocess.Popen(
            [self._ffmpeg, "-hide_banner", "-loglevel", "error", "-fflags", "nobuffer", "-probesize", "65536",
             "-analyzeduration", "500000", "-f", "flv", "-i", "pipe:0", "-map", "0", "-c", "copy",
             "-rw_timeout", "10000000", "-f", "flv", self.url],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, bufsize=0)

        def read_errors(stream):  # vidé en continu pour que ffmpeg ne bloque jamais sur ses messages
            for line in iter(stream.readline, b""):
                self._stderr.append(line.decode(errors="replace").strip())
                del self._stderr[:-20]
        threading.Thread(target=read_errors, args=(self._proc.stderr,), daemon=True).start()
        return av.open(_PipeWriter(self._proc.stdin), mode="w", format="flv",
                       options={"flvflags": "no_duration_filesize"})

    def _failure(self, e: Exception) -> str:
        msg = f"{type(e).__name__}: {e}"
        if self._proc is not None:
            try:
                self._proc.wait(2)
            except subprocess.TimeoutExpired:
                pass
            if self._stderr:
                msg = f"ffmpeg : {' / '.join(self._stderr[-3:])}"
        return scrub(msg, [self.url])[:300]

    def _run(self) -> None:
        container = None
        try:
            item = self._q.get()
            if item is None:
                return
            container = self._open()
            vtpl, atpl = self._templates
            vs = container.add_stream_from_template(vtpl)  # copie les paramètres de l'encodeur partagé, sans réencoder
            vs.time_base = MS
            aus = container.add_stream_from_template(atpl) if atpl is not None else None
            if aus is not None:
                aus.time_base = AUDIO_TB
            need_key, media = True, False
            while item is not None:
                if self._resync:
                    self._resync, need_key = False, True
                kind, key = item[0], item[5]
                if kind == "v":
                    if need_key and not key:
                        self.stats["skipped"] += 1  # on attend une image clé : sans elle l'image serait illisible
                    else:
                        need_key, media = False, True
                        self._mux(container, vs, item)
                        self.stats["video_packets"] += 1
                        if not self.stats["started"]:
                            self.stats["started"] = True
                            log.info("diffusion démarrée vers %s (%s)", mask_url(self.url),
                                     "ffmpeg isolé" if self._proc is not None else "PyAV direct")
                elif media and aus is not None:
                    self._mux(container, aus, item)
                    self.stats["audio_packets"] += 1
                item = self._q.get()
            c, container = container, None
            c.close()  # écrit la fin du flux FLV
            if self._proc is not None:
                self._proc.stdin.close()
                if self._proc.wait(10) != 0:
                    raise RuntimeError(f"ffmpeg terminé avec le code {self._proc.returncode}")
        except Exception as e:  # noqa: BLE001 - plateforme injoignable ou coupure
            if not self.stats["error"]:
                self.stats["error"] = self._failure(e)
            log.warning("diffusion vers %s interrompue : %s", mask_url(self.url), self.stats["error"])
        finally:
            self._dead = True
            if container is not None:
                try:
                    container.close()
                except Exception:  # noqa: BLE001
                    pass
            if self._proc is not None and self._proc.poll() is None:
                self._proc.kill()

    def close(self, timeout: float = 5.0) -> None:
        """Termine l'envoi. Si la plateforme ne répond plus, son processus ffmpeg est arrêté de force."""
        if self._thread is None:
            return
        if not self._dead:
            try:
                self._q.put_nowait(None)
            except queue.Full:
                self._drain()
                self._q.put_nowait(None)
        self._thread.join(timeout)
        if self._thread.is_alive():
            self.stats["error"] = self.stats["error"] or "la plateforme ne répond plus : envoi abandonné"
            if self._proc is not None and self._proc.poll() is None:
                self._proc.kill()  # débloque le fil (tube cassé), qui se termine aussitôt
                self._thread.join(2)

    def view(self) -> dict:
        return {"target": mask_url(self.url), **self.stats}


class Broadcaster:
    """Diffuse le même flux vers 1 à 3 plateformes, avec un seul encodage vidéo et un seul encodage son."""

    def __init__(self, urls: list[str], width: int = 720, height: int = 1280, fps: int = 30,
                 video_kbps: int = 3000, audio_kbps: int = 128, timer: StageTimer | None = None,
                 max_queue: int = 150) -> None:
        self.urls = list(urls)
        self.width, self.height, self.fps = width, height, fps
        self.video_kbps, self.audio_kbps = video_kbps, audio_kbps
        self.timer = timer
        self.outputs = [_Output(u, i, max_queue) for i, u in enumerate(self.urls)]
        self.stats = {"codec": None, "video_frames": 0, "audio_frames": 0, "error": None, "started": False}
        self.tasks: list[asyncio.Task] = []
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="live-encode")  # un seul fil : ordre garanti
        self._resampler = av.AudioResampler(format="fltp", layout="stereo", rate=48000)
        self._enc = self._vstream = self._astream = None
        self._t0: float | None = None
        self._last_pts = -1
        self._samples: int | None = None

    # --- fil d'encodage -------------------------------------------------------------------------
    def _open_encoders(self) -> None:
        # Conteneur factice en mémoire : il fixe une fois pour toutes les paramètres de l'encodeur
        # (SPS/PPS H.264, configuration AAC) que chaque plateforme recopie dans son propre flux FLV.
        self._enc = av.open(io.BytesIO(), mode="w", format="flv")
        codec = _video_codec()
        v = self._enc.add_stream(codec, rate=self.fps)
        v.width, v.height, v.pix_fmt = self.width, self.height, "yuv420p"
        v.bit_rate = self.video_kbps * 1000
        v.time_base = MS
        v.codec_context.options = ({"preset": "p3", "tune": "ll", "g": str(self.fps * 2)} if codec == "h264_nvenc"
                                   else {"preset": "veryfast", "tune": "zerolatency", "g": str(self.fps * 2)})
        a = self._enc.add_stream("aac", rate=48000)
        a.layout = "stereo"
        a.bit_rate = self.audio_kbps * 1000
        a.time_base = AUDIO_TB
        self._vstream, self._astream = v, a
        self.stats["codec"] = codec

    def _start_outputs(self, first_packet) -> None:
        self._enc.mux(first_packet)  # démarre le conteneur factice : les paramètres sont recopiés dans codecpar
        for o in self.outputs:
            o.begin(self._vstream, self._astream)
        self.stats["started"] = True
        log.info("encodage %s %dx%d démarré pour %d plateforme(s)", self.stats["codec"], self.width, self.height,
                 len(self.outputs))

    def _fanout(self, kind: str, packet) -> None:
        item = (kind, bytes(packet), packet.pts, packet.dts, packet.time_base, packet.is_keyframe)
        for o in self.outputs:
            o.offer(item)

    def _encode_video(self, frame: av.VideoFrame, pts: int) -> None:
        if self._vstream is None:
            self._open_encoders()
        with timed(self.timer, "rtmp_prep"):
            canvas = fit_canvas(frame.to_ndarray(format="rgb24"), self.width, self.height)
            vf = av.VideoFrame.from_ndarray(canvas, format="rgb24").reformat(format="yuv420p")
        vf.pts, vf.time_base = pts, MS
        with timed(self.timer, "rtmp_encode"):
            packets = self._vstream.encode(vf)
        for p in packets:
            if not self.stats["started"]:
                self._start_outputs(p)
            self._fanout("v", p)
        self.stats["video_frames"] += 1

    def _encode_audio(self, frame: av.AudioFrame) -> None:
        if self._astream is None:
            return
        for rf in self._resampler.resample(frame):
            rf.pts, rf.time_base = self._samples, AUDIO_TB
            self._samples += rf.samples
            for p in self._astream.encode(rf):
                if self.stats["started"]:
                    self._fanout("a", p)
            self.stats["audio_frames"] += 1

    def _flush(self) -> None:
        for kind, stream in (("v", self._vstream), ("a", self._astream)):
            if stream is None:
                continue
            try:
                for p in stream.encode(None):
                    if self.stats["started"]:
                        self._fanout(kind, p)
            except Exception:  # noqa: BLE001 - encodeur jamais ouvert ou déjà fermé
                pass
        if self._enc is not None:
            try:
                self._enc.close()
            except Exception:  # noqa: BLE001
                pass
            self._enc = None

    # --- boucle asyncio : ne fait qu'horodater et passer la main ------------------------------------
    def _now_ms(self) -> int:
        return int((time.monotonic() - (self._t0 or time.monotonic())) * 1000)

    async def _video_loop(self, track) -> None:
        loop = asyncio.get_running_loop()
        while True:
            frame = await track.recv()
            if self._t0 is None:
                self._t0 = time.monotonic()
            pts = max(self._now_ms(), self._last_pts + 1)
            self._last_pts = pts
            await loop.run_in_executor(self._pool, self._encode_video, frame, pts)

    async def _audio_loop(self, track) -> None:
        loop = asyncio.get_running_loop()
        while True:
            frame = await track.recv()
            if self._t0 is None:
                continue  # le son démarre avec la première image vidéo
            if self._samples is None:
                self._samples = int(self._now_ms() * 48)  # aligne le son sur l'horloge de la vidéo
            frame.pts = None
            await loop.run_in_executor(self._pool, self._encode_audio, frame)

    def start(self, video_track, audio_track=None) -> None:
        async def guard(coro):
            try:
                await coro
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - fin de flux ou encodeur en échec
                if not self.stats["error"]:
                    self.stats["error"] = scrub(f"{type(e).__name__}: {e}", self.urls)[:300]
                log.warning("diffusion interrompue : %s", self.stats["error"])
        self.tasks.append(asyncio.ensure_future(guard(self._video_loop(video_track))))
        if audio_track is not None:
            self.tasks.append(asyncio.ensure_future(guard(self._audio_loop(audio_track))))

    async def stop(self) -> None:
        for t in self.tasks:
            t.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._pool, self._flush)  # après les encodages en cours (même fil, dans l'ordre)
        self._pool.shutdown(wait=False)
        await asyncio.gather(*(asyncio.to_thread(o.close) for o in self.outputs))

    def view(self) -> dict:
        return {**self.stats, "targets": [o.view() for o in self.outputs]}
