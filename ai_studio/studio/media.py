"""Outils FFmpeg : analyse, découpe d'un segment, opérations locales, réassemblage.

Principe non destructif : le fichier source n'est jamais modifié. Pour une
modification limitée à une plage [début, fin], on découpe avant / segment / après,
on ne traite QUE le segment, puis on réassemble.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class MediaError(RuntimeError):
    pass


@dataclass(frozen=True)
class Probe:
    duration_s: float
    width: int
    height: int
    fps: float
    has_audio: bool


def _run(args: list[str], timeout: int = 900) -> subprocess.CompletedProcess:
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as e:
        raise MediaError(f"{args[0]} introuvable : installez FFmpeg") from e
    except subprocess.TimeoutExpired as e:
        raise MediaError("délai FFmpeg dépassé") from e
    if p.returncode != 0:
        raise MediaError(p.stderr.strip().splitlines()[-1] if p.stderr.strip() else "échec FFmpeg")
    return p


def available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def probe(path: Path) -> Probe:
    p = _run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)], 60)
    data = json.loads(p.stdout)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if video is None:
        raise MediaError("aucune piste vidéo")
    duration = float(data.get("format", {}).get("duration") or video.get("duration") or 0)
    if duration <= 0:
        raise MediaError("durée illisible")
    num, _, den = (video.get("avg_frame_rate") or "0/1").partition("/")
    fps = float(num) / float(den) if den and float(den) else 0.0
    has_audio = any(s.get("codec_type") == "audio" for s in data.get("streams", []))
    return Probe(duration_s=duration, width=int(video["width"]), height=int(video["height"]), fps=fps, has_audio=has_audio)


_ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
_AUD = ["-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2"]


def normalize(src: Path, dst: Path, width: int, height: int, fps: float = 30.0) -> None:
    """Ré-encode dans un format commun (même taille, fps, audio stéréo) pour permettre la concaténation."""
    pr = probe(src)
    vf = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
          f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps:g}")
    args = ["ffmpeg", "-y", "-v", "error", "-i", str(src)]
    if pr.has_audio:
        args += ["-map", "0:v:0", "-map", "0:a:0"]
    else:  # piste muette ajoutée pour que tous les morceaux aient la même structure
        args += ["-f", "lavfi", "-t", f"{pr.duration_s:.3f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
                 "-map", "0:v:0", "-map", "1:a:0"]
    _run(args + ["-vf", vf, *_ENC, *_AUD, str(dst)])


def cut(src: Path, dst: Path, start: float, end: float) -> None:
    """Extrait [start, end] avec ré-encodage (coupe précise à l'image)."""
    _run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(src),
          *_ENC, *_AUD, str(dst)])


def concat(parts: list[Path], dst: Path, workdir: Path, total_s: float | None = None) -> None:
    """Concatène des morceaux homogènes ; `total_s` rogne la sortie à la durée exacte attendue
    (le rembourrage AAC de chaque morceau ajoute sinon quelques dizaines de ms par jointure)."""
    lst = workdir / "concat.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts), encoding="utf-8")
    trim = ["-t", f"{total_s:.3f}"] if total_s else []
    _run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), *trim, *_ENC, *_AUD, str(dst)])


# Opérations locales : capacité → (filtre vidéo, filtre audio, options)
def local_filter(capability: str, width: int, height: int) -> tuple[str | None, str | None, list[str]]:
    even = lambda v: max(2, int(v) // 2 * 2)  # noqa: E731
    if capability == "format.vertical":
        if width * 16 >= height * 9:   # source plus large que 9:16 → recadrage central en largeur
            w, h = even(height * 9 / 16), even(height)
        else:
            w, h = even(width), even(width * 16 / 9)
        return f"crop={w}:{h}", None, []
    if capability == "format.square":
        side = even(min(width, height))
        return f"crop={side}:{side}", None, []
    if capability == "style.bw":
        return "hue=s=0,eq=contrast=1.08", None, []
    if capability == "style.cinematic":
        return ("eq=contrast=1.12:saturation=0.85:gamma=0.97,"
                "colorbalance=rs=-0.04:bs=0.06:rh=0.06:bh=-0.04,vignette=PI/5"), None, []
    if capability == "style.warm":
        return "colorbalance=rs=0.08:gs=0.02:bs=-0.08:rm=0.05:bm=-0.05", None, []
    if capability == "style.cool":
        return "colorbalance=rs=-0.07:bs=0.09:rm=-0.04:bm=0.06", None, []
    if capability == "speed.slow":
        return "setpts=2.0*PTS", "atempo=0.5", []
    if capability == "speed.fast":
        return "setpts=0.5*PTS", "atempo=2.0", []
    if capability == "audio.mute":
        return None, "volume=0", []
    raise MediaError(f"opération locale inconnue : {capability}")


def apply_local(src: Path, dst: Path, capability: str) -> None:
    pr = probe(src)
    vf, af, extra = local_filter(capability, pr.width, pr.height)
    args = ["ffmpeg", "-y", "-v", "error", "-i", str(src)]
    if vf:
        args += ["-vf", vf]
    if pr.has_audio:
        if af:
            args += ["-af", af]
        args += _AUD
    else:
        args += ["-an"]
    _run(args + [*_ENC, *extra, str(dst)])


def simulated_edit(src: Path, dst: Path) -> None:
    """Effet visible signalant une simulation (teinte + vignette + grain)."""
    pr = probe(src)
    args = ["ffmpeg", "-y", "-v", "error", "-i", str(src),
            "-vf", "hue=h=140:s=1.4,eq=contrast=1.15,vignette=PI/4,noise=alls=12:allf=t"]
    args += _AUD if pr.has_audio else ["-an"]
    _run(args + [*_ENC, str(dst)])


def make_test_clip(dst: Path, seconds: float = 3.0, size: str = "640x360", with_audio: bool = True) -> None:
    args = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=30:duration={seconds}"]
    if with_audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    args += [*_ENC]
    args += _AUD if with_audio else []
    _run(args + ["-shortest", str(dst)])
