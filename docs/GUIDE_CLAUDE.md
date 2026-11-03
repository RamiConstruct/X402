# Guide de Claude pour le Laboratoire

> Écrit par Claude, pour Claude (toute nouvelle session, sur le web, sur PC ou dans le projet claude.ai).
> `CLAUDE.md` = les règles courtes. Ce guide = comprendre en profondeur, reprendre sans rien casser,
> et grandir sans se perdre. À tenir à jour à chaque étape importante (section 10).

---

## 1. Pour qui et pourquoi
- **Le fondateur** : francophone, nomade, travaille surtout depuis son téléphone, souvent en dictée vocale
  (fautes de transcription fréquentes : lire l'intention, pas la lettre). Musulman pratiquant : l'intention du
  projet est la gratitude envers Allah ; le projet doit être utile, apporter du bonheur, et respecter ses valeurs
  (`docs/VISION.md` : honnêteté, aucune dépense sans accord, finance sans riba ni gharar, création originale).
- **Ce qu'il veut** : des produits IA en ligne, pilotables depuis un téléphone, qui lui donnent l'indépendance
  financière ; il les utilise d'abord lui-même puis les vend.
- **Comment il travaille avec moi** : il délègue largement (« fais tout », « accorde-toi les autorisations ») et
  veut le minimum de questions. Mais il garde trois verrous : **l'argent**, **les nouvelles actions sur le serveur**
  (une phrase : « M'autorises-tu à le faire une fois ? »), et **ses goûts** (il n'aime pas Daydream ; il veut le
  meilleur, « quoi qu'il en coûte », tout en restant rentable).
- **Comment lui répondre** : français simple, phrases courtes, tableaux, pas de jargon (ou expliqué en 3 mots),
  une recommandation claire plutôt qu'une liste d'options, honnêteté sur ce qui n'est pas testé ou pas possible.
  Quand il dit « je ne sais pas, et toi ? » : décider, expliquer pourquoi en 2 lignes, et agir.

## 2. Les produits
| Produit | Promesse | Adresse | État (3 nov. 2026) |
|---|---|---|---|
| **AI LIVE** | Tu te filmes et l'IA te transforme en direct (chevalier, robot, anime…) à la voix, et tu peux diffuser sur YouTube, Twitch, Kick, TikTok | live.labotory.site (`/mobile.html` pour le téléphone) | En ligne, en phase de test, moteur actuel Daydream (à remplacer par nos GPU) |
| **AI STUDIO** | Montage vidéo par instructions en langage naturel, devis avant exécution, crédits | studio.labotory.site (sur invitation) | En ligne, crédits prêts, paiement Stripe inactif |
| **Site vitrine** | Présentation, liste d'attente, 15 langues selon le pays | labotory.site, suivi public sur `/suivi` | En ligne |

## 3. Carte technique (où est quoi)
```
Téléphone / navigateur ──WebRTC (WHIP/WHEP)──▶ moteur IA (Daydream aujourd'hui ; nos GPU loués demain)
   │  mobile.html/js, rtc.js, rendu.js, motion.wasm, modèle silhouette
   └──HTTPS──▶ Cloudflare ──tunnel──▶ serveur Oracle (Sydney, 1 Go, gratuit)
                                         ├ ai-live-console (FastAPI, port interne) : sessions, commandes, flotte
                                         ├ ai-live-worker (démo processeur, pour les tests)
                                         ├ ai-studio (FastAPI + SQLite)
                                         ├ coturn (relais TURN de secours) ; cloudflared (tunnel)
                                         └ chien de garde systemd + mémoire d'échange
Cloudflare : Workers « laboratoire » (site, 2 modules : worker.js + langues.js) et « sentinelle-labo »
             (cron 5 min : surveille, redémarre Oracle via son API, tente de créer la VM A1 gratuite) ;
             KV « laboratoire » (avancement, liste d'attente), « coffre-labo » (secrets, sauvegardes),
             « sentinelle-labo » ; routage e-mail contact@labotory.site → boîte du fondateur.
GitHub : RamiConstruct/X402 ; GitHub Actions construit l'image du programme GPU (GHCR, publique).
```
Fichiers clés : voir le tableau « Architecture » de `CLAUDE.md`. Les détails du rendu téléphone sont en tête
de `ai_live/live/static/rendu.js` ; la flotte en tête de `ai_live/live/gpu/fleet.py`.

## 4. Journal des décisions (pourquoi les choses sont ainsi)
| Date | Décision | Raison |
|---|---|---|
| 29–30 oct. | Atelier x402 et labo d'arbitrage hors ligne | Premières pistes ; mises de côté au profit d'AI LIVE / STUDIO |
| 2 nov. | Deux pilotes : AI STUDIO (A) et AI LIVE (B) | Analyse stratégique (`docs/ai_live_studio/ANALYSE_STRATEGIQUE.md`) |
| 2 nov. | Daydream pour démarrer AI LIVE | Zéro GPU à gérer, pour valider vite |
| 2 nov. | Phase de test : pas de diffusion par défaut, essais enregistrés localement | Sécurité et image : rien n'est publié par erreur |
| 2 nov. | Plateformes sans minimum d'abonnés en premier | Le fondateur part de zéro abonné |
| 2 nov. | Site en 15 langues, langue selon le pays | Clientèle mondiale, fondateur nomade |
| 2 nov. | Modes Rapide / Équilibré / Qualité + Auto, graine fixe, 512 px | Mesures Daydream : 640 px bloquait, 512 px stable ; « couleurs vives » donnait du psychédélique |
| 2 nov. | Images de référence et « garder mon visage » en option expérimentale | Le petit serveur saturait pendant les essais ; IP-Adapter seulement en SDXL |
| 3 nov. | Protections serveur + sentinelle Cloudflare | Panne de 5 h (tunnel QUIC sur serveur saturé) |
| 3 nov. | Asie : Singapour/Tokyo, GPU proches des utilisateurs | Le délai dépend de la distance utilisateur ↔ GPU (`BENCHMARK_ASIE.md`) |
| 3 nov. | Rendu côté téléphone : 1080/1440p agrandi, prédiction du mouvement, silhouette | Gratuit pour nous, masque le délai réseau (`ETUDE_INSTANTANEITE.md`) |
| 3 nov. | Rust/WebAssembly pour le calcul du mouvement seulement | Mesuré ×9 ; ailleurs Rust n'apporte rien (IA = GPU, serveur = attente réseau) |
| 3 nov. | Pas d'agrandissement par IA sur le téléphone | Trop de calcul pour 25 i/s ; à faire sur le GPU serveur |
| 3 nov. | Le fondateur n'aime pas Daydream → flotte de GPU à nous | Indépendance, qualité, coût ; plusieurs GPU moyens plutôt qu'un gros |
| 3 nov. | Objectif 1440p / 90 i/s affichées / délai ressenti nul | Exigence produit ; atteint par IA 720p + agrandissement + images intermédiaires |
| 3 nov. | Pas de compte GPU « pour l'instant » | Décision du fondateur : avancer sur le code sans dépense |
| 3 nov. | Remise en question (`docs/REMISE_EN_QUESTION.md`) : tests GitHub automatiques, versions anti-cache automatiques ; à venir : fusion vers `main`, LiveKit, TypeScript, WebGPU, banc d'essai des modèles causaux (Causal Forcing, StreamDiffusionV2) | Nouveautés juin–nov. 2026 et faiblesses relevées |

## 5. Où on en est (vérifié le 3 nov. 2026, voir `docs/SAUVEGARDE.md`)
**Fait et en ligne** : AI LIVE téléphone (voix 15 langues, personnages/décors/styles, modes + Auto, rendu
480p→1440p, fluidité avec délai mesuré, Rust, silhouette, enregistrement 60 i/s), console ordinateur, page OBS,
diffusion multi-plateformes (code prêt), AI STUDIO 15 langues, site 15 langues, liste d'attente, suivi,
protections, sentinelle.
**Fait, inactif** : flotte de GPU automatique (attend une clé Vast.ai/RunPod), paiement Stripe (attend les clés),
pages légales (attendent l'identité du fondateur), migration A1 (attend de la place chez Oracle).
**Jamais testé en vrai** : notre programme GPU sur un vrai GPU ; le rendu sur un vrai téléphone ; la diffusion
réelle vers une plateforme. Ne jamais présenter ces points comme « fonctionnels ».

## 6. Où on veut aller — feuille de route avec critères de passage
| Phase | Objectif | Critère pour passer à la suivante | Coût |
|---|---|---|---|
| **0. Validation** (en cours) | Le fondateur s'en sert lui-même | Il fait un live satisfaisant sur son téléphone | 0 |
| **1. Nos GPU** | Programme GPU testé sur 1 RTX 4090 puis 1 H100 ; mesurer i/s, délai, qualité, **places par GPU** | Qualité ≥ Daydream, délai < 150 ms en Asie, coût par heure-utilisateur connu | 10–100 $ d'essais |
| **2. Bêta payante** | Stripe actif, pages légales publiées, 10–50 testeurs de la liste d'attente, flotte en Standard | Marge ≥ 60 % mesurée sur de vraies factures GPU ; aucune panne non rattrapée | payé par les crédits |
| **3. Qualité Ultra** | Modèle vidéo causal (StreamDiffusionV2), 720p IA → 1440p, images intermédiaires, H100 | Rendu 1440p / 90 i/s affichées validé par le fondateur | selon ventes |
| **4. Expansion** | Régions Singapour + Tokyo (+ Mumbai), console sur un VPS Asie, R2 pour les vidéos, modèle maison par personnage | Croissance des abonnés, coûts sous contrôle | selon ventes |

## 7. Garde-fous de croissance (pour ne pas se perdre)
1. **Une seule source de vérité** : `CLAUDE.md` (règles), ce guide (compréhension), `docs/SAUVEGARDE.md` (état),
   page `/suivi` (vue publique, sans secret). Toute décision importante → une ligne dans la section 4.
2. **Chaque heure de GPU est payée par des crédits clients** avant d'ajouter de la capacité. Prix client ≥ coût GPU
   par place × 2,5 (marge ≥ 60 %). Plafond horaire de la flotte toujours défini (`LIVE_FLEET_MAX_USD_H`).
3. **Mesurer avant de construire** : chiffres marqués « estimation » tant qu'ils ne sont pas mesurés
   (places par GPU, i/s, coût Daydream à la minute…). Remplacer dès qu'on a une mesure.
4. **Petits lots testés et réversibles** : un sujet par commit, tests verts avant mise en ligne, vérification en
   ligne après.
5. **Ne pas multiplier les chantiers** : finir la phase en cours avant d'ouvrir la suivante ; noter les idées
   dans la section 9 plutôt que de les démarrer.
6. **Sécurité d'abord** : aucun secret dans le dépôt ni la discussion ; régénérer toute clé exposée.
7. **Honnêteté** : distinguer « codé », « testé en simulation », « testé en vrai », « vendu ».

## 8. Pièges déjà rencontrés (ne pas les refaire)
**Mise en ligne**
- Cache Cloudflare (4 h) : toujours changer les `?v=<hash>` des scripts dans `mobile.html`, `index.html`,
  `output.html` et `motion.wasm?v=` dans `rendu.js`.
- Le paquet est installé à DEUX endroits sur le serveur (paquet Python + `/opt/ai-live/app/live`) : extraire dans
  les deux. Redémarrer `ai-live-console` seulement si du Python a changé.
- Le Worker du site a 2 modules (worker.js + langues.js) ; son script en ligne a un hash CSP à recalculer.
- Mise en scène de fichiers via `PUT /_deploy/<nom>` du site (jeton) : stocké 1 h dans le KV, à copier tout de suite.

**Commandes**
- `pkill -f`/`pgrep -f` avec un motif présent dans ta propre commande tue ta session : ne pas faire.
- Longues commandes SSH : `nohup … &` sur le serveur, `python -u` pour ne pas perdre la sortie.
- Ne jamais lancer de tests vidéo lourds (aiortc) sur le serveur de 1 Go : il sature et le tunnel tombe.

**Daydream (tant qu'il sert)**
- Largeur multiple de 64, ≤ 1024 ; 640 reste bloqué au chargement → 512.
- `PATCH` avant que la vidéo coule → 404 « Stream not ready » : garder en attente et appliquer après WHEP (fait).
- IP-Adapter seulement avec sdxl-turbo.

**Oracle / Cloudflare / réseau**
- Nouvelle clé API Oracle : 401 pendant 1–2 min, c'est normal.
- A1 gratuite : « Out of host capacity » fréquent ; 2 OCPU / 12 Go maximum sur ce compte.
- Le proxy de l'environnement bloque certains sites (limits.oraclecloud.com, spheron.network).
- Wikimedia refuse les téléchargements depuis l'environnement : passer par le serveur.

**Navigateur / tests**
- Le navigateur de test (SwiftShader) est très lent en WebGL : un faible i/s y est normal ; tester la logique en
  480p.
- Tests Node lancés via `vm` : les tableaux viennent d'un autre contexte → comparer avec `[...x]`.

## 9. Idées en réserve (ne pas démarrer sans accord)
Modèles vidéo causaux (Causal Forcing, StreamDiffusionV2) à comparer en phase 1 ; LiveKit (phase 2) ; Mojo pour nos noyaux GPU (phase 3–4) ; Agrandissement par IA côté GPU ; images intermédiaires côté GPU ; MoQ/WebTransport (à surveiller) ; Burn/CubeCL
pour partager les petits modèles téléphone/serveur ; modules (LoRA) par personnage ; R2 + Wasabi pour les vidéos ;
VPS Vultr Singapour ; essais ralentis et effets ; AI STUDIO : export vers les réseaux sociaux.

## 10. Rituel de fin d'étape (à faire à chaque jalon)
1. Tests verts (`CLAUDE.md` → Tests) et vérification des pages en ligne.
2. Commit + push sur la branche de la session.
3. Mettre à jour : `docs/SAUVEGARDE.md` (état), section 4 et 5 de ce guide, `avancement.json` → `/suivi`
   (`PUT /avancement.json` avec le jeton du site).
4. Si la configuration du serveur a changé : nouvelle sauvegarde dans le KV `coffre-labo` (jamais dans le dépôt).
5. Dire au fondateur, en quelques lignes : ce qui est fait, vérifié comment, ce qui reste, ce qu'il doit faire.

## 11. Démarrage rapide d'une nouvelle session
1. Lire `CLAUDE.md`, puis ce guide (sections 5–8), puis `docs/SAUVEGARDE.md`.
2. Vérifier les variables d'environnement (liste dans `CLAUDE.md`) ; sans elles : pas d'accès serveur, le dire.
3. `git log --oneline -15` pour voir le dernier travail ; lancer les tests.
4. Demander au fondateur seulement ce qui bloque vraiment ; sinon avancer sur la phase en cours.

## 12. Lexique pour parler au fondateur
GPU = carte graphique (fait les calculs d'IA) · VPS / serveur = ordinateur loué en ligne · i/s = images par seconde
· délai = temps entre ton geste et l'image transformée · flotte = ensemble de GPU loués automatiquement ·
TURN = relais vidéo quand le réseau bloque · KV = petit coffre de données chez Cloudflare · tunnel = connexion
sécurisée entre Cloudflare et le serveur, sans ouvrir de port.
