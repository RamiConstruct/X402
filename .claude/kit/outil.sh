#!/usr/bin/env bash
# Boîte à outils : lance un outil open source à version figée, via uvx.
# Rien n'est installé dans le dépôt ; uvx met l'outil en cache au premier appel.
# Usage : bash .claude/kit/outil.sh <outil> [arguments de l'outil]
# Détail, étoiles et licences : .claude/kit/KIT.md
set -euo pipefail

usage() {
  cat <<'TXT'
Outils disponibles :
  scrapling    page web -> Markdown/HTML/texte, requête HTTP rapide   (D4Vinci/Scrapling 0.5.1)
  crawl        page web rendue dans un vrai navigateur -> Markdown    (unclecode/crawl4ai 0.9.5)
  trafilatura  texte principal d'un article, sans menus ni pubs       (adbar/trafilatura 2.3.1)
  markitdown   PDF, Word, Excel, PowerPoint, HTML... -> Markdown      (microsoft/markitdown 0.1.9)
  yt-dlp       métadonnées, sous-titres, audio et vidéo en ligne      (yt-dlp/yt-dlp 2026.10.26)
  ocr          texte dans une image, chinois et latin                 (RapidAI/RapidOCR 3.10.0)
  ast-grep     recherche de code par structure syntaxique             (ast-grep/ast-grep 0.51.3)
  duckdb       SQL directement sur des fichiers CSV, JSON, Parquet    (duckdb/duckdb 2.0.0)
TXT
}

[ $# -ge 1 ] || { usage; exit 2; }
tool="$1"; shift
command -v uvx >/dev/null 2>&1 || { echo "uvx est requis : https://docs.astral.sh/uv/" >&2; exit 1; }
export UV_NO_PROGRESS=1 CRAWL4AI_NO_CLOUD_NOTICE=1

case "$tool" in
  scrapling)   exec uvx --quiet --from 'scrapling[shell]==0.5.1' scrapling "$@" ;;
  crawl)
    # Crawl4AI pilote Chromium par Playwright. Si un Playwright Node est déjà
    # installé avec son navigateur (sessions cloud), on aligne la version pour
    # réutiliser ce navigateur. Sinon : `uvx playwright install chromium` une fois.
    pw="$(node -e "console.log(require('playwright/package.json').version)" 2>/dev/null || true)"
    if [ -n "$pw" ]; then
      exec uvx --quiet --with "playwright==$pw" --from crawl4ai==0.9.5 crwl "$@"
    fi
    exec uvx --quiet --from crawl4ai==0.9.5 crwl "$@" ;;
  trafilatura) exec uvx --quiet trafilatura@2.3.1 "$@" ;;
  markitdown)  exec uvx --quiet --from 'markitdown[pdf,docx,pptx,xlsx]==0.1.9' markitdown "$@" ;;
  yt-dlp)      exec uvx --quiet yt-dlp@2026.10.26 "$@" ;;
  ocr)         exec uvx --quiet --with onnxruntime --from rapidocr==3.10.0 rapidocr "$@" ;;
  ast-grep)    exec uvx --quiet --from ast-grep-cli==0.51.3 ast-grep "$@" ;;
  duckdb)      exec uvx --quiet --from duckdb-cli==2.0.0 duckdb "$@" ;;
  -h|--help|help) usage ;;
  *) echo "Outil inconnu : $tool" >&2; usage >&2; exit 2 ;;
esac
