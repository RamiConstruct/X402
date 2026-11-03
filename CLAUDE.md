# Le Laboratoire — AI LIVE et AI STUDIO

Mémoire du projet pour Claude (sessions Claude Code et projet claude.ai). À lire avant toute tâche.
**Guide complet (historique, décisions, pièges, feuille de route, garde-fous de croissance) : `docs/GUIDE_CLAUDE.md`.**

## Le projet
- **AI LIVE** : transformation IA en temps réel de la caméra (personnages, décors, styles) pilotée à la voix,
  sur téléphone et ordinateur, avec diffusion en direct vers YouTube, Twitch, Kick…
  Site : https://live.labotory.site (page téléphone : `/mobile.html`).
- **AI STUDIO** : montage vidéo par IA, crédits payants (Stripe prêt, pas encore activé).
  Site : https://studio.labotory.site
- **Site vitrine** : https://labotory.site (15 langues, liste d'attente), suivi : `/suivi`.
- Le fondateur l'utilise d'abord lui-même, puis le vendra. Il écrit en français, souvent depuis son téléphone :
  répondre en français simple, concret, sans jargon.

## Règles à respecter
- Ne **jamais** créditer « Claude » ni l'IA de développement sur le site.
- Ne **jamais** publier de secret, d'adresse IP ni de donnée personnelle (site, dépôt, journaux).
- Les secrets viennent des **variables d'environnement** de la session (jamais de la discussion, jamais dans le dépôt).
- **Aucune dépense** (location de GPU, abonnement, achat) sans accord explicite. Pour une nouvelle action sur le
  serveur, demander brièvement : « M'autorises-tu à le faire une fois ? »
- Éthique : pas d'imitation photoréaliste de personnes réelles sans consentement ; parodie seulement en
  caricature avec le bandeau « PARODIE IA » ; contenus sexuels, violents et haineux bloqués.
- Le fondateur **n'aime pas Daydream** : objectif = nos propres GPU (flotte automatique, `ai_live/live/gpu/fleet.py`).
- Objectif qualité : **1440p, 90 i/s affichées, délai ressenti nul** (voir `docs/ai_live_studio/OBJECTIF_1440P_90.md`).
- Travailler sur la branche indiquée par la session ; pas de demande de fusion sans demande explicite.

## Architecture
| Partie | Où | Rôle |
|---|---|---|
| `ai_live/live/server.py` | serveur Oracle (Sydney, 1 Go) derrière un tunnel Cloudflare | console : sessions, commandes vocales, moteurs, flotte |
| `ai_live/live/engine.py`, `scene.py`, `commands.py`, `i18n_commands.py` | serveur | paramètres StreamDiffusion, scènes, commandes en 15 langues |
| `ai_live/live/worker/` + `Dockerfile.worker` | GPU loué | programme IA (StreamDiffusion, WebRTC WHIP/WHEP, RTMP) |
| `ai_live/live/gpu/` | serveur | location Vast.ai / RunPod ; `fleet.py` = flotte automatique (LIVE_FLEET=1) |
| `ai_live/live/static/` | navigateur | `mobile.*`, `rtc.js` (WebRTC, mode auto), `rendu.js` (1080/1440p WebGL2, prédiction du mouvement, silhouette MediaPipe), `motion.wasm` (Rust) |
| `ai_live/motion_rs/` | Rust → WebAssembly | calcul du mouvement, 9× plus rapide que JS |
| `ai_studio/` | serveur | AI Studio (FastAPI), facturation `studio/billing.py` |
| `site/laboratoire/` | Worker Cloudflare | site vitrine 15 langues (`langues/*.json` → `build_langues.mjs`) |
| `site/sentinelle/` | Worker Cloudflare (cron 5 min) | surveille le serveur, le redémarre via l'API Oracle, tente de créer la VM A1 |

## Tests
```sh
cd ai_live && .venv/bin/python -m pytest -q          # ~91 tests
node ai_live/tests/js/rendu.test.mjs && node ai_live/tests/js/autotune.test.mjs
cd ai_studio && .venv/bin/python -m pytest -q        # ~29 tests
```
Après une modification de fichier statique : mettre à jour les `?v=<hash>` dans `mobile.html`, `index.html`,
`output.html` (et `motion.wasm?v=` dans `rendu.js`), sinon le cache Cloudflare sert l'ancienne version.

## Mise en ligne (AI Live)
Archive des fichiers modifiés → `scp` puis extraction sur le serveur via `ssh` (accès par `cloudflared access ssh`,
hôte de connexion dans les variables d'environnement), dans le paquet installé ET `/opt/ai-live/app/live`, puis
`sudo systemctl restart ai-live-console` si du Python a changé. Vérifier ensuite la page en ligne.

## Variables d'environnement attendues (réglages de l'environnement Claude Code)
`LABO_SSH_KEY`, `OCI_CONFIG_JSON`, `OCI_API_KEY_PEM`, `LABO_TOKEN`, `SENT_TOKEN`, `DAYDREAM_API_KEY`,
plus tard `VAST_API_KEY` / `RUNPOD_API_KEY`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`.

## En attente
- Compte GPU (Vast.ai ou RunPod) → premier test réel, mesure des places par GPU, activation de la flotte.
- Pages légales : identité du fondateur à compléter (`docs/legal/`).
- Stripe : compte et clés (`docs/ai_live_studio/ACTIVER_STRIPE.md`).
- Migration vers la VM Oracle A1 gratuite (la sentinelle réessaie toutes les 29 min : « Out of host capacity »).
- Essai sur vrai téléphone : 1080/1440p, fluidité, silhouette.

## Installer ailleurs / sauvegarde
`docs/INSTALLER_PC.md` (PC + projet claude.ai), `docs/SAUVEGARDE.md` (bilan et emplacement des sauvegardes),
`tools/installer_pc.sh` / `.ps1` (installation + vérification automatiques).

## Documents utiles
`docs/ai_live_studio/` : BENCHMARK_ASIE, ETUDE_INSTANTANEITE, OBJECTIF_1440P_90, PLAN_INVESTISSEMENT, ACTIVER_STRIPE.
