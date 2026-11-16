# Kit de skills Claude Code

Skills tirés de GitHub, vérifiés et figés sur un commit précis. Ils se chargent
dans toutes les sessions Claude Code ouvertes sur ce dépôt : web, mobile,
application de bureau et terminal.

Installation ou mise à jour : `bash .claude/kit/install.sh` (un skill déjà
présent n'est jamais écrasé). Pour un autre dépôt : `bash install.sh /chemin/du/depot`.

## Contenu (20 skills tiers, une seule source par rôle)

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

## Contrôles qualité : `make check` et `make scan`

Cinq outils GitHub, lancés par `uvx` à une version figée dans le `Makefile` :
rien n'est installé dans le dépôt ni sur la machine, et ils marchent dans toute
session où `uv` est présent.

| Commande | Outil (version) | Rôle | Licence |
|---|---|---|---|
| `make lint` | astral-sh/ruff (0.17.5) | Erreurs Python réelles : imports inutiles, noms indéfinis, syntaxe (`ruff.toml`) | MIT |
| `make shell` | koalaman/shellcheck (0.11.0, via shellcheck-py) | Erreurs dans les scripts shell, à partir du niveau « warning » | GPL-3.0 |
| `make secrets` | Yelp/detect-secrets (1.5.0) | Bloque tout secret potentiel absent de `.secrets.baseline` (VISION.md, principe 5) | Apache-2.0 |
| `make audit` | pypa/pip-audit (2.10.1) | Failles connues dans les dépendances de `ai_studio` et `ai_live` | Apache-2.0 |
| `make semgrep` | semgrep/semgrep (1.185.0) | Analyse de sécurité du code, règles `p/python` et `p/secrets` ; c'est le binaire qu'attend le skill `semgrep` | LGPL-2.1 |

- `make check` = lint + shell + secrets + tests. Rapide, à lancer avant chaque commit.
- `make scan` = audit + semgrep. Plus lent et en ligne, à lancer avant une mise en production.
- `.secrets.baseline` liste 27 faux positifs relus le 2026-11-16 (empreintes de
  fixtures, identifiant de namespace KV, mots de passe d'exemple et de test).
  Après une relecture : `uvx --from detect-secrets==1.5.0 detect-secrets scan --exclude-files '^\.claude/' > .secrets.baseline`.
- Les skills tiers (`.claude/skills/`) et `fixtures/` sont exclus des contrôles.

État au 2026-11-16 : `make check` et `make scan` passent, 222 tests, aucune faille
connue, aucun résultat Semgrep. Seule correction de code : 6 imports inutilisés
retirés dans des fichiers de test.

Volontairement absents : **gitleaks** et **trivy** (binaires hors PyPI, même rôle
que detect-secrets et pip-audit), **mypy** (le code n'est pas annoté pour, ce
serait du bruit), **pre-commit** (un hook local ne suit pas les sessions cloud ;
`make check` fait le même travail).

## Boîte à outils : web, documents, données

Huit outils open source lancés par `bash .claude/kit/outil.sh <outil> [arguments]`,
à version figée, via `uvx` : rien n'est installé dans le dépôt. Le skill maison
`boite-a-outils` dit à Claude quand et comment s'en servir.

| Outil | Dépôt | Étoiles | Rôle | Licence |
|---|---|---|---|---|
| `scrapling` | D4Vinci/Scrapling 0.5.1 | 103 k | Page web → Markdown, requête HTTP rapide | BSD-3-Clause |
| `crawl` | unclecode/crawl4ai 0.9.5 | 87 k | Page rendue dans un vrai navigateur → Markdown | Apache-2.0 |
| `trafilatura` | adbar/trafilatura 2.3.1 | 7 k | Texte principal d'un article | Apache-2.0 |
| `markitdown` | microsoft/markitdown 0.1.9 | 195 k | PDF, Word, Excel, PowerPoint, HTML → Markdown | MIT |
| `yt-dlp` | yt-dlp/yt-dlp 2026.10.26 | 206 k | Métadonnées, sous-titres, médias en ligne | Unlicense |
| `ocr` | RapidAI/RapidOCR 3.10.0 (projet chinois, modèles PaddleOCR de Baidu) | — | Texte dans une image, chinois et latin, sans carte graphique | Apache-2.0 |
| `ast-grep` | ast-grep/ast-grep 0.51.3 | 17 k | Recherche de code par structure syntaxique | MIT |
| `duckdb` | duckdb/duckdb 2.0.0 | 43 k | SQL sur CSV, JSON, Parquet | MIT |

Étoiles relevées sur repos.ecosyste.ms entre le 9 et le 14 novembre 2026 (celles
de RapidOCR n'ont pas été relevées). Chaque outil a été lancé avec succès par
`outil.sh` le 2026-11-16 dans une session cloud.

- `crawl` réutilise le Chromium déjà présent en alignant la version de Playwright
  sur celle de Node. Sur une machine sans navigateur : `uvx playwright install chromium` une fois.
- `markitdown` est limité aux formats PDF, Word, Excel et PowerPoint : l'option
  `[all]` de la 0.1.9 dépend d'une préversion Azure introuvable sur PyPI.
- `trafilatura` ignore le certificat du proxy des sessions cloud et réessaie sans
  vérification TLS ; le résultat est correct, mais préférer `scrapling` pour une page sensible.

Volontairement absents :

- **NanmiCoder/MediaCrawler** (71 k, chinois) et **g1879/DrissionPage** (13 k, chinois) :
  licences qui interdisent l'usage commercial ; MediaCrawler collecte en plus derrière
  des comptes connectés, contre les règles des plateformes.
- **firecrawl/firecrawl** (201 k) : AGPL-3.0 et serveur à héberger (Redis, Docker) ;
  Scrapling et Crawl4AI couvrent le besoin sans serveur.
- **browser-use/browser-use** (121 k) : pilote un navigateur avec un modèle payant à
  chaque action (VISION.md, principe 2). Claude pilote déjà Playwright directement.
- **microsoft/playwright-mcp** (40 k) : Playwright est déjà installé ; un serveur MCP
  de plus chargerait ses outils dans chaque session.
- **opendatalab/MinerU** (83 k, chinois), **PaddlePaddle/PaddleOCR** (93 k, chinois)
  et **docling** (71 k) : plusieurs gigaoctets de modèles pour un gain utile seulement
  sur des PDF très complexes ; markitdown et RapidOCR suffisent pour l'instant.
