#!/usr/bin/env bash
# Kit de skills Claude Code (version 2026-11-03)
# Copie dans <dossier>/.claude/skills une sélection de skills GitHub vérifiés,
# figés sur un commit précis : rien ne change sans que tu relances une nouvelle version.
# Usage : bash install.sh [dossier-du-depot]   (par défaut : dossier courant)
set -euo pipefail

ROOT="${1:-.}"
DEST="$ROOT/.claude/skills"
KIT="$ROOT/.claude/kit"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$DEST" "$KIT/licences"

fetch() { # <owner/repo> <commit> -> chemin du clone
  local dir="$TMP/${1//\//_}"
  git init -q "$dir"
  git -C "$dir" fetch -q --depth 1 "https://github.com/$1" "$2"
  git -C "$dir" -c advice.detachedHead=false checkout -q FETCH_HEAD
  echo "$dir"
}

ADDED=()
add() { # <dossier source> <nom>
  if [ -e "$DEST/$2" ]; then echo "  déjà présent, laissé tel quel : $2"; return; fi
  [ -f "$1/SKILL.md" ] || { echo "  ERREUR : pas de SKILL.md dans $1" >&2; exit 1; }
  cp -R "$1" "$DEST/$2"
  ADDED+=("$2")
  echo "  ajouté : $2"
}

echo "1/4 Méthode de travail (obra/superpowers, MIT)"
SP=$(fetch obra/superpowers 2ce8aa15d05bd57213e6f746f953aafb7ded7a8b)
SP_SKILLS="brainstorming writing-plans executing-plans subagent-driven-development
dispatching-parallel-agents test-driven-development systematic-debugging
requesting-code-review receiving-code-review using-git-worktrees finishing-a-development-branch"
for s in $SP_SKILLS; do add "$SP/skills/$s" "$s"; done
# Hors plugin, les renvois « superpowers:nom » deviennent « nom ».
for s in $SP_SKILLS; do
  find "$DEST/$s" -name '*.md' -exec perl -pi -e 's/\bsuperpowers:([a-z][a-z-]*)/$1/g' {} +
done
cp "$SP/LICENSE" "$KIT/licences/obra-superpowers-MIT.txt"

echo "2/4 Cloudflare Workers (cloudflare/skills, Apache-2.0)"
CF=$(fetch cloudflare/skills 1a33048817d06df12882cb881dfc754e7039954a)
for s in workers-best-practices agents-sdk durable-objects cf-cli; do add "$CF/skills/$s" "$s"; done
cp "$CF/LICENSE" "$KIT/licences/cloudflare-skills-Apache-2.0.txt"

echo "3/4 Sécurité (trailofbits/skills, CC BY-SA 4.0)"
TB=$(fetch trailofbits/skills 2be6433b39e009cd2b6fd3be1895f6b1faa5af9a)
add "$TB/plugins/static-analysis/skills/semgrep" semgrep
add "$TB/plugins/static-analysis/skills/sarif-parsing" sarif-parsing
add "$TB/plugins/sharp-edges/skills/sharp-edges" sharp-edges
add "$TB/plugins/supply-chain-risk-auditor/skills/supply-chain-risk-auditor" supply-chain-risk-auditor
cp "$TB/LICENSE" "$KIT/licences/trailofbits-skills-CC-BY-SA-4.0.txt"

echo "4/4 Construire un serveur MCP (anthropics/skills, Apache-2.0)"
AN=$(fetch anthropics/skills ca45fc496a3436251f191354091d557da31c15b5)
add "$AN/skills/mcp-builder" mcp-builder

echo
echo "Terminé : ${#ADDED[@]} skill(s) ajouté(s) dans $DEST"
