"""Applique le menu commun (site/nav/nav.html) aux pages statiques du site.

Usage : python3 site/nav/apply_nav.py
Chaque page reçoit le menu juste après <body>, avec la page courante marquée
(aria-current="page"). Le Worker labotory.site embarque sa propre copie (worker.js, NAV_CSS).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NAV = (Path(__file__).parent / "nav.html").read_text(encoding="utf-8").strip()
PAGES = {
    "ai_live/live/static/index.html": "live",
    "ai_live/live/static/mobile.html": "mobile",
    "ai_studio/studio/static/index.html": "studio",
}
OLD_FAB = re.compile(r"<style>\s*\.labfab.*?</details>\s*", re.S)
BLOCK = re.compile(r"<!-- labnav:start.*?<!-- labnav:end -->\s*", re.S)


def nav_for(key: str) -> str:
    return NAV.replace(f'data-k="{key}" ', f'data-k="{key}" aria-current="page" ')


def apply(path: Path, key: str) -> None:
    html = path.read_text(encoding="utf-8")
    html = OLD_FAB.sub("", html)
    html = BLOCK.sub("", html)
    html = html.replace("<body>\n", "<body>\n" + nav_for(key) + "\n", 1)
    if html.count("labnav:start") != 1:
        raise SystemExit(f"{path}: menu non inséré")
    path.write_text(html, encoding="utf-8")
    print("ok", path.relative_to(ROOT))


def apply_worker(path: Path) -> None:
    """Recopie le menu dans le Worker (constante NAV_HTML entre les marqueurs labnav)."""
    import json

    src = path.read_text(encoding="utf-8")
    compact = re.sub(r"\n\s*", "", re.sub(r"<!--.*?-->", "", NAV, flags=re.S))
    new, n = re.subn(
        r"(// labnav:start[^\n]*\n)const NAV_HTML = .*?;\n(// labnav:end)",
        lambda m: m.group(1) + "const NAV_HTML = " + json.dumps(compact, ensure_ascii=False) + ";\n" + m.group(2),
        src,
        flags=re.S,
    )
    if n != 1:
        raise SystemExit(f"{path}: marqueurs labnav introuvables")
    path.write_text(new, encoding="utf-8")
    print("ok", path.relative_to(ROOT))


if __name__ == "__main__":
    for rel, key in PAGES.items():
        apply(ROOT / rel, key)
    apply_worker(ROOT / "site/laboratoire/worker.js")
