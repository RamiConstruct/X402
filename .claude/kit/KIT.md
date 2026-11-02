# Kit de skills Claude Code

Skills tirés de GitHub, vérifiés et figés sur un commit précis. Ils se chargent
dans toutes les sessions Claude Code ouvertes sur ce dépôt : web, mobile,
application de bureau et terminal.

Installation ou mise à jour : `bash .claude/kit/install.sh` (un skill déjà
présent n'est jamais écrasé). Pour un autre dépôt : `bash install.sh /chemin/du/depot`.

## Contenu (20 skills, une seule source par rôle)

| Rôle | Skills | Source (commit) | Licence |
|---|---|---|---|
| Méthode de travail : idée → plan → tests → débogage → revue → fin de branche | brainstorming, writing-plans, executing-plans, subagent-driven-development, dispatching-parallel-agents, test-driven-development, systematic-debugging, requesting-code-review, receiving-code-review, using-git-worktrees, finishing-a-development-branch | obra/superpowers (`2ce8aa1`) | MIT |
| Cloudflare Workers | workers-best-practices, agents-sdk, durable-objects, cf-cli | cloudflare/skills (`1a33048`) | Apache-2.0 |
| Sécurité du code | semgrep, sarif-parsing, sharp-edges, supply-chain-risk-auditor | trailofbits/skills (`2be6433`) | CC BY-SA 4.0 |
| Construire un serveur MCP (piste « bot vendeur x402 ») | mcp-builder | anthropics/skills (`ca45fc4`) | Apache-2.0 |

Les textes de licence sont dans `.claude/kit/licences/` (celle de mcp-builder est
dans son dossier).

**Modification apportée** : dans les skills Superpowers, les renvois
`superpowers:nom` sont devenus `nom`, puisqu'ils ne sont plus chargés comme
plugin. Tous les autres fichiers sont copiés sans changement.
Attribution : Superpowers © 2025 Jesse Vincent ; skills © Cloudflare,
© Trail of Bits, © Anthropic.

## Volontairement absents

- **verification-before-completion** (Superpowers), **wrangler** (Cloudflare) et
  **hf-mem** (Hugging Face) : activés sur le compte claude.ai, donc déjà chargés
  dans les sessions cloud. Les copier ici créerait des doublons.
- **using-superpowers** : amorce du plugin, conçue pour un hook de démarrage ;
  hors plugin, elle forcerait l'usage de skills à chaque message.
- **mattpocock/skills** et **addyosmani/agent-skills** : même rôle que
  Superpowers (plans, TDD, débogage, revue). Un seul jeu évite les conflits.
- **codeql** (Trail of Bits) : fait le même travail que semgrep, en plus lourd.
- **coinbase/agentic-wallet-skills** : manipule un vrai portefeuille. Exclu tant
  qu'aucune décision explicite ne l'autorise (VISION.md, principes 2 et 5).

Vérifié le 2026-11-03 : chaque `SKILL.md` a un nom et une description, aucun nom
en double, aucun renvoi `superpowers:` restant.

## Carte du code : code-review-graph

Serveur MCP local (tirth8205/code-review-graph, v2.3.9 figée, MIT) qui construit
une carte du code (fonctions, appels, imports, tests) pour que Claude lise
seulement les fichiers utiles au lieu de tout parcourir.

- `.mcp.json` : lance le serveur via `uvx`, limité à 11 outils qui ne touchent pas au code
  (les 19 autres, dont celui qui applique des refactorisations, sont désactivés par `CRG_TOOLS`).
- `.claude/settings.json` : construit la carte au démarrage de chaque session
  (environ 4 s) et la met à jour après chaque modification de fichier.
  Si `uvx` est absent, les hooks ne font rien.
- `.code-review-graphignore` : exclut `.claude/` et `fixtures/` de la carte.
- `CLAUDE.md` : dit à Claude d'interroger la carte avant de fouiller les fichiers.
- Les 4 skills que l'installeur génère (debug-issue, explore-codebase,
  refactor-safely, review-changes) ont été retirés : ils doublaient Superpowers.
