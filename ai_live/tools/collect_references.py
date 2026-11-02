"""Constitue la bibliothèque d'images de référence (Wikimedia Commons, licences libres uniquement).

Usage : python ai_live/tools/collect_references.py [--per 3] [--only chevalier,robot]
Pour chaque personnage / décor / style, cherche des photos, ne garde que domaine public, CC0, CC BY,
CC BY-SA, les réduit à 512 px (JPEG) et écrit live/references/manifest.json avec auteur, licence et source.
Les images choisies doivent ensuite être relues à l'œil (planche contact) avant publication.
"""
from __future__ import annotations

import argparse
import html
import io
import json
import re
import time
from pathlib import Path

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parents[1] / "live" / "references"
API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "LaboratoireRefs/1.0 (https://labotory.site; contact via site)"}
OK_LICENSE = re.compile(r"^(public domain|pd|cc0|cc by(-sa)? \d(\.\d)?)", re.I)

# Requêtes de recherche par clé (en anglais : Commons est surtout indexé en anglais).
QUERIES: dict[str, dict[str, list[str]]] = {
    "characters": {
        "chevalier": ["suit of armour Wallace Collection", "plate armour Royal Armouries", "full plate armour display", "armour Metropolitan Museum"],
        "robot": ["humanoid robot exhibition", "robot ASIMO", "humanoid robot expo", "android robot"],
        "pirate": ["pirate costume", "pirate hat coat costume", "pirate reenactor"],
        "viking": ["viking warrior reenactment", "viking helmet shield reenactor", "viking armour reenactment"],
        "astronaute": ["spacesuit display museum", "space suit exhibit", "EVA spacesuit display"],
        "samourai": ["samurai armour museum", "samurai armor display", "yoroi armour"],
        "sorcier": ["wizard costume", "wizard robe hat costume", "Gandalf costume"],
        "zombie": ["zombie walk", "zombie makeup costume"],
        "superheros": ["superhero costume display", "superhero cosplay", "superhero suit exhibit"],
        "dessin_anime": ["costume mascot", "theme park mascot costume", "mascot costume character"],
    },
    "decors": {
        "cyberpunk": ["neon street night Tokyo", "neon signs night city rain"],
        "medieval": ["medieval castle courtyard", "medieval town street"],
        "espace": ["ISS cupola Earth view", "space station module interior empty", "Earth from space ISS"],
        "jungle": ["tropical rainforest", "jungle sunlight rainforest"],
        "plage": ["tropical beach palm trees", "beach sunset palm"],
        "hiver": ["snowy forest photograph", "snow covered spruce forest", "winter forest snowfall"],
        "desert": ["Erg Chebbi dunes", "Namib desert dunes", "sand dunes landscape Sahara"],
        "sous_marin": ["coral reef fish underwater", "coral reef NOAA"],
    },
    "styles": {
        "anime": ["anime style illustration public domain", "manga style drawing"],
        "bd": ["comic book page public domain golden age", "comic strip public domain"],
        "peinture": ["Van Gogh painting", "impasto oil painting"],
        "aquarelle": ["J. M. W. Turner watercolour", "watercolor landscape painting", "Winslow Homer watercolor"],
        "pixel": ["pixel art landscape", "pixel art scene", "pixel art game"],
        "film_noir": ["Detour 1945 film screenshot", "film noir screenshot public domain", "D.O.A. 1950 film screenshot"],
        "cinema": [],
        "pate_a_modeler": ["plasticine figurines", "clay figures animation", "plasticine sculpture"],
    },
}


def search(client: httpx.Client, q: str, n: int = 12) -> list[dict]:
    r = client.get(API, params={
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6, "gsrsearch": f"{q} filetype:bitmap",
        "gsrlimit": n, "prop": "imageinfo", "iiprop": "url|extmetadata|size|mime", "iiurlwidth": 768,
    })
    r.raise_for_status()
    pages = (r.json().get("query") or {}).get("pages", {}).values()
    out = []
    for p in sorted(pages, key=lambda x: x.get("index", 0)):
        ii = (p.get("imageinfo") or [{}])[0]
        m = ii.get("extmetadata") or {}
        lic = html.unescape(re.sub("<[^>]+>", "", (m.get("LicenseShortName") or {}).get("value", ""))).strip()
        if not OK_LICENSE.match(lic) or ii.get("mime") not in ("image/jpeg", "image/png") or min(ii.get("width", 0), ii.get("height", 0)) < 400:
            continue
        artist = html.unescape(re.sub("<[^>]+>", "", (m.get("Artist") or {}).get("value", ""))).strip()[:120]
        out.append({"title": p["title"], "thumb": ii.get("thumburl"), "page": ii.get("descriptionurl"), "license": lic, "author": artist or "inconnu"})
    return out


_FACE = None


def has_face(jpg: bytes) -> bool:
    """Visage détecté (OpenCV) ? Les références de personnages et de décors doivent être sans
    visage reconnaissable : l'IA ne doit pas reprendre les traits d'une personne réelle."""
    global _FACE
    try:
        import cv2
        import numpy as np
    except ImportError:
        return False
    if not hasattr(cv2, "CascadeClassifier"):  # OpenCV 5 : détecteur Haar retiré → filtrage à faire ailleurs
        return False
    if _FACE is None:
        _FACE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_GRAYSCALE)
    faces = _FACE.detectMultiScale(img, scaleFactor=1.1, minNeighbors=6, minSize=(28, 28))
    return len(faces) > 0


def to_jpeg(data: bytes) -> bytes:
    img = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = img.size
    s = min(w, h)  # carré centré (comme l'image envoyée à l'IA)
    img = img.crop(((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2)).resize((512, 512), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=86, optimize=True)
    return buf.getvalue()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per", type=int, default=3)
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    only = set(filter(None, a.only.split(",")))
    manifest_path = ROOT / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    with httpx.Client(headers=UA, timeout=30, follow_redirects=True) as client:
        for kind, items in QUERIES.items():
            for key, queries in items.items():
                if only and key not in only:
                    continue
                seen, picked = set(), []
                old = ROOT / kind / key
                if old.exists():
                    for f in old.glob("*.jpg"):
                        f.unlink()
                for q in queries:
                    for c in search(client, q):
                        if c["title"] in seen or len(picked) >= a.per:
                            continue
                        seen.add(c["title"])
                        try:
                            data = client.get(c["thumb"]).content
                            jpg = to_jpeg(data)
                        except Exception as e:  # noqa: BLE001
                            print("  ignorée", c["title"], e)
                            continue
                        if kind != "styles" and has_face(jpg):
                            print("  visage détecté, ignorée :", c["title"][:60])
                            continue
                        name = f"{len(picked) + 1}.jpg"
                        (ROOT / kind / key).mkdir(parents=True, exist_ok=True)
                        (ROOT / kind / key / name).write_bytes(jpg)
                        picked.append({"file": name, "source": c["page"], "license": c["license"], "author": c["author"], "title": c["title"]})
                        time.sleep(0.3)
                manifest.setdefault(kind, {})[key] = picked
                print(f"{kind}/{key}: {len(picked)} image(s)")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
