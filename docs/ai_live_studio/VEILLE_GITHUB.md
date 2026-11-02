# Veille GitHub — classement (2026-11-02)

Critères : utilité réelle pour le projet ou pour le travail de Claude, activité récente (dernier commit
≤ 3 mois sauf mention), popularité, licence compatible avec un usage commercial. Étoiles et dates
relevées le 2026-11-02 via l'API de recherche GitHub.

## A. Pour rendre Claude plus efficace sur le projet

| # | Projet | ⭐ | Dernier commit | Licence | Décision |
|---|---|---|---|---|---|
| 1 | [obra/superpowers](https://github.com/obra/superpowers) — méthodes de travail (débogage, vérification, plans, TDD) | 311 k | 2026-10-29 | MIT | **Installé** (4 compétences, `.claude/skills/`) |
| 2 | [anthropics/skills](https://github.com/anthropics/skills) — compétences officielles Anthropic | 187 k | 2026-10-28 | Apache-2.0 (par dossier) | **Installé** : frontend-design, webapp-testing |
| 3 | [upstash/context7](https://github.com/upstash/context7) — documentation à jour des bibliothèques | 64 k | 2026-11-02 | MIT | **Installé** (serveur MCP distant, `.mcp.json`) |
| 4 | [anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official) — annuaire officiel de plugins | 46 k | 2026-11-02 | Apache-2.0 | À parcourir au cas par cas |
| 5 | [thedotmack/claude-mem](https://github.com/thedotmack/claude-mem) — mémoire entre sessions | 110 k | 2026-11-02 | Apache-2.0 | Pas maintenant : hooks + service local qui enregistre tout (clés, IP) ; à revoir sur un poste dédié |
| 6 | [headroomlabs-ai/headroom](https://github.com/headroomlabs-ai/headroom) — compression des sorties d'outils | 79 k | 2026-11-02 | Apache-2.0 | Pas utile ici (le contexte est déjà géré) |
| 7 | [microsoft/playwright-mcp](https://github.com/microsoft/playwright-mcp) | 39 k | 2026-11-01 | Apache-2.0 | Déjà couvert (Playwright installé) |
| 8 | [github/github-mcp-server](https://github.com/github/github-mcp-server) | 34 k | 2026-11-02 | MIT | Déjà connecté |
| 9 | [PrefectHQ/fastmcp](https://github.com/PrefectHQ/fastmcp) — créer nos propres serveurs MCP | 28 k | 2026-11-02 | Apache-2.0 | Utile plus tard (MCP « AI Live » pour piloter le live depuis un assistant) |
| 10 | [hesreallyhim/awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code), [VoltAgent/awesome-claude-code-subagents](https://github.com/VoltAgent/awesome-claude-code-subagents) | 57 k / 26 k | 2026-11-02 | — | Listes de référence (veille) |

Écartés volontairement : affaan-m/ECC (295 k ⭐, « harness » très intrusif : hooks partout),
JuliusBrussee/caveman (réponses télégraphiques : mauvais pour toi), dépôts de « prompts système »
récupérés (provenance douteuse), packs de compétences de piratage.

## B. Pour AI Live (temps réel)

| # | Projet | ⭐ | Dernier commit | Licence | Intérêt |
|---|---|---|---|---|---|
| 1 | [chenfengxu714/StreamDiffusionV2](https://github.com/chenfengxu714/StreamDiffusionV2) | 0,6 k | 2026-09-14 | Apache-2.0 | **Priorité test GPU** : nouvelle génération, meilleure stabilité temporelle (moins de scintillement) |
| 2 | [daydreamlive/scope](https://github.com/daydreamlive/scope) — outil de pipelines temps réel de Daydream | 0,5 k | 2026-07-17 | à vérifier | Comprendre/reprendre leurs réglages ; licence à confirmer avant usage |
| 3 | [livekit/livekit](https://github.com/livekit/livekit) + [livekit/agents](https://github.com/livekit/agents) | 22 k / 15 k | 2026-11-02 | Apache-2.0 | Infrastructure WebRTC à grande échelle (quand il y aura beaucoup d'utilisateurs) |
| 4 | [bluenviron/mediamtx](https://github.com/bluenviron/mediamtx) | 21 k | 2026-11-02 | MIT | Relais vidéo sur le VPS : multidiffusion, enregistrement, WHIP/WHEP ; à installer quand la diffusion passera par notre serveur |
| 5 | [pipecat-ai/pipecat](https://github.com/pipecat-ai/pipecat) | 17 k | 2026-11-02 | BSD-2 | Commandes vocales multilingues robustes (reconnaissance + compréhension) |
| 6 | [huggingface/diffusers](https://github.com/huggingface/diffusers) | 35 k | 2026-11-02 | Apache-2.0 | Base de tous les moteurs |
| — | jcelerier/librediffusion (StreamDiffusion en C++/CUDA) | 40 | 2026-10-25 | AGPL-3.0 | Rapide mais AGPL : incompatible avec un service fermé |
| — | krea-ai/realtime-video (Krea Realtime 14B) | 0,6 k | 2025-11-13 | non précisée | Trop ancien et trop lourd pour l'instant |
| — | livepeer/ai-runner | — | archivé | MIT | Abandonné : ne pas utiliser |

## C. Pour AI Studio (montage vidéo)

| # | Projet | ⭐ | Dernier commit | Licence | Intérêt |
|---|---|---|---|---|---|
| 1 | [Wan-Video/Wan2.2](https://github.com/Wan-Video/Wan2.2) | 18 k | 2026-09-21 | Apache-2.0 | Modèle vidéo ouvert de référence (gros GPU) |
| 2 | [hao-ai-lab/FastVideo](https://github.com/hao-ai-lab/FastVideo) | 4,8 k | 2026-11-02 | Apache-2.0 | Accélère la génération vidéo (coût par seconde plus bas) |
| 3 | [Lightricks/LTX-Video](https://github.com/Lightricks/LTX-Video) | 11 k | 2026-01-05 | Apache-2.0 | Rapide, mais moins actif (10 mois) |

## Favoris GitHub

Je ne peux pas ajouter d'étoiles depuis cette session : l'outil GitHub disponible n'a pas cette action, et la
ligne de commande GitHub ne sert ici qu'à la recherche. Pour les mettre en favoris toi-même, ouvre chaque lien
des tableaux et clique sur « Star ». Les plus utiles : superpowers, anthropics/skills, context7, StreamDiffusionV2,
mediamtx, livekit, pipecat, Wan2.2, FastVideo.
