"""Met à jour les numéros de version anti-cache des fichiers statiques d'AI Live (?v=<empreinte>).

Sans eux, le cache Cloudflare (4 h) sert l'ancienne version des scripts après une mise en ligne.
  python tools/versionner.py            # réécrit les ?v= de mobile.html, index.html, output.html et rendu.js
  python tools/versionner.py --verifier # échoue si une mise à jour a été oubliée (utilisé par les tests GitHub)
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "ai_live" / "live" / "static"
SOURCES = ["rtc.js", "rendu.js", "mobile.js", "i18n_ui.js", "app.js", "motion.wasm"]
PAGES = ["mobile.html", "index.html", "output.html", "rendu.js"]
MOTIF = re.compile(r"(\.(?:js|wasm)\?v=)[0-9a-f]{8}")


def empreinte() -> str:
    h = hashlib.sha256()
    for name in SOURCES:
        data = (STATIC / name).read_bytes()
        if name == "rendu.js":   # rendu.js contient lui-même un ?v= : l'exclure du calcul
            data = re.sub(rb"(\.wasm\?v=)[0-9a-f]{8}", rb"\1", data)
        h.update(data)
    return h.hexdigest()[:8]


def main() -> int:
    v = empreinte()
    verifier = "--verifier" in sys.argv
    oublis = []
    for name in PAGES:
        p = STATIC / name
        old = p.read_text(encoding="utf-8")
        new = MOTIF.sub(lambda m: m.group(1) + v, old)
        if new != old:
            if verifier:
                oublis.append(name)
            else:
                p.write_text(new, encoding="utf-8")
    if oublis:
        print(f"Versions anti-cache à mettre à jour ({', '.join(oublis)}) : lancer python tools/versionner.py")
        return 1
    print(f"Versions anti-cache : ?v={v}" + (" (à jour)" if verifier else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
