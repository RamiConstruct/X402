#!/usr/bin/env bash
# Installation et vérification complètes du Laboratoire sur Mac ou Linux.
# Usage (dans le dossier du dépôt) : bash tools/installer_pc.sh
set -euo pipefail
cd "$(dirname "$0")/.."
ok() { printf '  \033[32m✔\033[0m %s\n' "$1"; }
ko() { printf '  \033[31m✘\033[0m %s\n' "$1"; exit 1; }
echo "1. Outils"
command -v git >/dev/null || ko "Git manquant : https://git-scm.com"
command -v python3 >/dev/null || ko "Python 3.11+ manquant : https://www.python.org"
command -v node >/dev/null || ko "Node.js 20+ manquant : https://nodejs.org"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || ko "Python 3.11 ou plus requis"
ok "git, python $(python3 -V | cut -d' ' -f2), node $(node -v)"
command -v cargo >/dev/null && ok "Rust présent (facultatif)" || echo "  · Rust absent (facultatif : seulement pour recompiler motion.wasm)"
echo "2. AI Live"
(cd ai_live && python3 -m venv .venv && .venv/bin/pip install -q -e '.[dev]') && ok "dépendances installées"
(cd ai_live && .venv/bin/python -m pytest -q | tail -1) && ok "tests serveur"
node ai_live/tests/js/rendu.test.mjs >/dev/null && node ai_live/tests/js/autotune.test.mjs >/dev/null && ok "tests navigateur (rendu, mode auto, Rust)"
echo "3. AI Studio"
(cd ai_studio && python3 -m venv .venv && .venv/bin/pip install -q -e '.[dev]') && ok "dépendances installées"
(cd ai_studio && .venv/bin/python -m pytest -q | tail -1) && ok "tests"
echo "4. Site et outils"
(cd site/laboratoire && node build_langues.mjs >/dev/null) && ok "site : 15 langues valides"
ai_live/.venv/bin/python -m pytest -q tests | tail -1 && ok "tests à la racine"
echo
echo "Tout est installé. Lancer Claude Code dans ce dossier : claude"
echo "Essai local d'AI Live : cd ai_live && .venv/bin/python -m live --port 8780  puis http://localhost:8780/mobile.html"
