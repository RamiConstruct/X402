# AI LIVE — pilote B : se transformer en direct pendant un stream

Tu parles (« transforme-moi en chevalier », « décor cyberpunk », « style anime »,
« ajoute de la neige », « plus fort », « retour à l'original »), la vidéo de ta
caméra est transformée en temps réel et envoyée dans OBS, puis sur Twitch/YouTube/Kick.

Un seul tunnel, **deux moteurs interchangeables** qui parlent le même protocole :

| Moteur | Où tourne l'IA | Pour quoi |
|---|---|---|
| `daydream` | API hébergée Daydream (StreamDiffusion géré par eux) | Démarrer en quelques minutes, sans GPU |
| `selfhosted` | **Ton** worker (`live.worker`) : ton Legion, ou un GPU loué | Ton propre moteur : marge, indépendance |

Conception : [`docs/ai_live_studio/PILOTE_LIVE_DEUX_CHEMINS.md`](../docs/ai_live_studio/PILOTE_LIVE_DEUX_CHEMINS.md).

```
Caméra (navigateur) ──WHIP──▶ console (relais SDP, clés cachées) ──▶ moteur (Daydream ou ton worker)
                                                                        │
OBS : [caméra] + [Source navigateur /output.html?k=…] ◀──WHEP───────────┘
Voix (Chrome) ─▶ commandes ─▶ état de scène ─▶ PATCH du moteur (sans couper le flux)
```

## Ce qui est vérifié

| Testé ici | Pas encore testé |
|---|---|
| 46 tests : chronométrage par étape, diffusion multiplateforme avec un seul encodage (plateforme refusée ou muette isolée, worker toujours réactif), chemin tenseur de StreamDiffusion (faux modèle, torch CPU ; ignoré si torch ou Pillow manquent), commandes FR, contrat de l'API Daydream, contrats **Vast.ai** et **RunPod** (requêtes exactes), garde-fous de location (inactivité, durée max, reprise après redémarrage, arrêt non confirmé), **tunnel WebRTC complet**, parcours « louer → live → libérer » avec un vrai worker | **Appels réels à Daydream, Vast.ai et RunPod** (clés absentes, domaines bloqués ici) |
| Parcours dans Chromium avec caméra simulée : démarrage, commandes, préréglages, page OBS, retour à l'original, arrêt — 0 erreur, 16 i/s avec le processeur de démonstration (CPU) | **Processeur StreamDiffusion sur GPU** (aucun GPU ici), y compris `SD_TENSOR_IO=1` |
| | Image Docker du worker GPU, relais TURN en conditions réelles |

Le protocole Daydream a été repris du **SDK TypeScript officiel** et du **plugin
TouchDesigner officiel** (`github.com/daydreamlive`) : création `POST /v1/streams`,
envoi WHIP avec la clé, URL de sortie dans l'en-tête `Livepeer-Playback-Url`,
mise à jour `PATCH /v1/streams/{id}`, suppression `DELETE /v1/streams?id=…`.

## 1. Installer (Windows ou Linux)

```bash
cd ai_live
python -m venv .venv
# Windows : .venv\Scripts\activate      Linux/Mac : source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest -q
```

## 2. Chemin B — tester avec Daydream (gratuit pour commencer)

1. Crée un compte sur daydream.live et une clé API (création immédiate d'après leur changelog ; vérifie les crédits gratuits et le tarif à l'inscription).
2. Lance la console :
   ```bash
   # Windows PowerShell :  $env:DAYDREAM_API_KEY="ta_cle"; python -m live
   DAYDREAM_API_KEY=ta_cle python -m live
   ```
3. Ouvre **http://127.0.0.1:8780** dans Chrome ou Edge → moteur « Daydream » → **Démarrer le live IA**.
4. Les premières secondes, le modèle se charge ; ensuite la sortie IA apparaît à droite.

## 3. Chemin A — ton propre moteur StreamDiffusion

### Sur ton Legion (RTX 4070, 8 Go) — gratuit

```bash
# 1) PyTorch CUDA (voir pytorch.org pour la version adaptée à ton pilote NVIDIA), puis :
pip install "git+https://github.com/daydreamlive/StreamDiffusion.git@main#egg=streamdiffusion[tensorrt,controlnet]"
python -m streamdiffusion.tools.install-tensorrt
pip install -e ".[worker]"

# 2) Le worker (1er lancement : compilation TensorRT, plusieurs minutes)
#   PowerShell : $env:WORKER_PROCESSOR="streamdiffusion"; $env:WORKER_TOKEN="secret"; python -m live.worker
WORKER_PROCESSOR=streamdiffusion WORKER_TOKEN=secret python -m live.worker --port 8890

# 3) La console, dans un autre terminal
SELFHOST_URL=http://127.0.0.1:8890 SELFHOST_TOKEN=secret SELFHOST_MODEL=stabilityai/sd-turbo python -m live
```

Avec 8 Go de VRAM : commence par `stabilityai/sd-turbo` en 512×512, sans ControlNet
(`SELFHOST_CONTROLNETS=0`, valeur par défaut). Mesure les i/s affichés en haut de la console.

Pour tester le tunnel sans GPU : `WORKER_PROCESSOR=demo` (effet de couleur CPU).

### Sur un GPU loué (RunPod, Vast.ai… — RTX 4090/5090)

Même commandes sur la machine louée, avec le worker exposé en HTTPS (proxy HTTP du
fournisseur ou tunnel Cloudflare) et `WORKER_PUBLIC_URL=https://…`. La console reste
sur ton VPS ou ton PC : `SELFHOST_URL=https://…`. **Éteins la machine après usage** :
la facturation court tant qu'elle est allumée.

## 3 bis. GPU à la demande (Vast.ai / RunPod) — le chemin recommandé

La console loue elle-même une machine, y lance ton worker, attend qu'il soit prêt, puis
la libère. Tu choisis un **modèle** ; la console affiche toutes les offres compatibles
(GPU, lieu, prix/heure, **prix/minute**) triées par prix.

| Modèle | VRAM mini | Pour |
|---|---|---|
| Rapide — SD-Turbo 512px | 12 Go | le moins cher, style marqué |
| Polyvalent — Dreamshaper 8 + ControlNet | 16 Go | personnages, garde la pose |
| Qualité — SDXL-Turbo + ControlNet | 24 Go | meilleur rendu |

**Prix** : coût réel de la machine × marge du modèle. En **mode propriétaire**
(`LIVE_OWNER_MODE=1`, par défaut), la marge est 1 : tu paies le prix coûtant. Pour tes futurs
clients, `LIVE_OWNER_MODE=0` applique la marge du catalogue (`live/gpu/catalog.py`).

**Garde-fous** (la facture qui tourne sans toi est le risque n°1) :
- une seule machine louée à la fois, prix horaire maximal (`LIVE_GPU_MAX_USD_H`, défaut 1,5 $) ;
- libération automatique après `LIVE_GPU_IDLE_MIN` minutes sans live (défaut 10), durée max `LIVE_GPU_MAX_HOURS` (défaut 4 h), abandon si la machine ne démarre pas en 30 min ;
- état enregistré dans `data/gpu_state.json` : après un redémarrage de la console, la location est retrouvée et surveillée ;
- un arrêt non confirmé par le fournisseur est signalé (« vérifie sur le site du fournisseur ») au lieu d'être supposé réussi ;
- chaque machine reçoit un jeton secret unique.

### Ce qu'il faut faire une fois (décisions et actions humaines)

1. **Image du worker** : construite automatiquement par GitHub Actions (`.github/workflows/live-worker-image.yml`)
   et publiée sur `ghcr.io/ramiconstruct/x402-live-worker:<branche>` à chaque modification du worker.
   Rends le paquet **public** (GitHub → Packages → x402-live-worker → Package settings → Change visibility)
   pour que Vast.ai et RunPod puissent le télécharger. Construction manuelle possible :
   `docker build -f Dockerfile.worker -t ghcr.io/<toi>/ai-live-worker:1 . && docker push …`
   puis `LIVE_WORKER_IMAGE=ghcr.io/<toi>/ai-live-worker:1`. Elle n'a pas encore été construite : le
   premier essai sur un GPU validera versions CUDA/TensorRT.
2. **Clés** : `VAST_API_KEY` (console.vast.ai → Account → API keys) et/ou `RUNPOD_API_KEY`.
   Recharge quelques dollars seulement au début.
3. **Relais vidéo TURN** — indispensable : les machines louées sont derrière un NAT, et RunPod
   n'accepte pas l'UDP. Un script installe tout sur ton VPS (Ubuntu/Debian), voir
   [`deploy/TURN.md`](deploy/TURN.md) : `sudo bash ai_live/deploy/install_turn.sh`.
   Il affiche à la fin `LIVE_TURN_SECRET` et `LIVE_TURN_URLS` à donner à la console ; la console
   fabrique ensuite des identifiants temporaires pour le navigateur, la page OBS et le GPU loué.

### Utilisation

Console → « GPU à la demande » → choisir un modèle → **Voir les GPU disponibles** → **Louer** →
attendre « Prêt » (premier lancement : téléchargement de l'image + compilation TensorRT,
compter 5 à 15 min) → moteur « Mon GPU loué » → **Démarrer le live IA** → **Libérer le GPU** à la fin.

## 4. Brancher OBS

1. Ajoute ta source caméra habituelle.
2. Copie l'« URL de sortie OBS » depuis la console → **Source navigateur** au-dessus de la caméra, même taille (ex. 1080×1080 ou 1920×1080).
3. « RETOUR À L'ORIGINAL » rend la sortie transparente : ta vraie caméra apparaît instantanément, sans couper le stream.

Remarque : la caméra ne peut être ouverte que par une application à la fois sous Windows.
Si OBS l'utilise déjà, ouvre la console avec une caméra virtuelle ou un second appareil
(téléphone en navigateur, en HTTPS) — c'est la prochaine amélioration prévue.

## 5. Commandes vocales

Bouton « Écoute vocale » (reconnaissance vocale gratuite intégrée à Chrome/Edge, en français).

| Tu dis | Effet |
|---|---|
| « transforme-moi en chevalier / robot / pirate / dragon rouge… » | personnage (catalogue ou description libre) |
| « change le décor en ville médiévale », « décor espace » | décor |
| « style anime / BD / peinture / pixel / pâte à modeler » | style |
| « ajoute de la neige / pluie / orage », « enlève la neige » | effets |
| « plus fort », « plus subtil » | intensité 1–5 |
| « retour à l'original », « remets l'effet », « annule » | bascule, réactivation, annulation |
| « chevalier et décor cyberpunk, style anime » | commandes enchaînées |

**Personnalités publiques** (Macron, etc.) : uniquement en **caricature non
photoréaliste**, avec un bandeau « PARODIE IA · ce n'est pas … » affiché sur la sortie.
Contenus sexuels, violents ou haineux : refusés avant tout envoi au moteur.

## 6. Configuration

| Variable | Rôle |
|---|---|
| `DAYDREAM_API_KEY`, `DAYDREAM_MODEL` (déf. `stabilityai/sdxl-turbo`), `DAYDREAM_USD_PER_MIN` | moteur Daydream ; tarif pour l'estimation de coût (vide = inconnu) |
| `SELFHOST_URL`, `SELFHOST_TOKEN`, `SELFHOST_MODEL` (déf. `stabilityai/sd-turbo`), `SELFHOST_CONTROLNETS`, `SELFHOST_USD_PER_MIN` | ton worker |
| `LIVE_ACCESS_TOKEN` | protège la console si elle est exposée sur Internet (elle dépense tes crédits) |
| `LIVE_MAX_SESSION_MIN` (déf. 60) | coupe automatiquement une session trop longue |
| `VAST_API_KEY`, `RUNPOD_API_KEY`, `LIVE_WORKER_IMAGE`, `LIVE_GPU_MAX_USD_H`, `LIVE_GPU_IDLE_MIN`, `LIVE_GPU_MAX_HOURS`, `LIVE_OWNER_MODE`, `LIVE_DATA_DIR` | location de GPU |
| `LIVE_CF_TURN_KEY_ID`, `LIVE_CF_TURN_API_TOKEN` | relais Cloudflare Realtime TURN (recommandé) |
| `LIVE_TURN_SECRET`, `LIVE_TURN_URLS` | relais TURN du VPS (identifiants temporaires générés par la console) ; `LIVE_ICE_SERVERS` pour une liste statique |
| `WORKER_PROCESSOR` (`demo` / `streamdiffusion`), `WORKER_TOKEN`, `WORKER_PUBLIC_URL`, `WORKER_WARMUP_PARAMS`, `WORKER_ICE_SERVERS`, `SD_ACCELERATION`, `SD_ENGINE_DIR` | worker |
| `WORKER_STATS_LOG_S` (déf. 10, `0` = désactivé) | résumé périodique dans le journal du worker : images/s et durée moyenne/p95 de chaque étape |
| `SD_TENSOR_IO` (déf. `0`) | `1` = l'image reste en tenseur sur le GPU autour du modèle (sans PIL) ; à comparer avec `0` sur ton GPU |
| `WORKER_RTMP_SUBPROCESS` (déf. `auto`), `WORKER_RTMP_CODEC` | diffusion directe : `auto` = un processus `ffmpeg` par plateforme si `ffmpeg` est installé, `0` = envoi direct par PyAV ; codec vidéo forcé |

## 7. Mesurer le worker (avant toute optimisation)

Le worker chronomètre chaque étape d'une image et l'affiche dans son terminal toutes les
`WORKER_STATS_LOG_S` secondes, par exemple :

```
i/s entrée 30.0, sortie 18.2, abandonnées 214 | to_rgb 1.1/1.6 ms | process 52.3/61.0 ms | sd_pre 3.9/4.4 ms | sd_model 45.0/53.2 ms | sd_post 2.8/3.1 ms | from_rgb 0.9/1.2 ms | rtmp_prep 6.2/7.0 ms | rtmp_encode 2.1/3.4 ms
```

(valeurs d'illustration). Les mêmes chiffres sont renvoyés par `GET /v1/streams/{id}`
(champ `timings`, et `stats.frames_dropped`).

| Étape | Ce qu'elle mesure |
|---|---|
| `to_rgb` / `from_rgb` | conversion de l'image reçue en tableau, puis retour en image vidéo (CPU) |
| `process` | tout le traitement IA, attente d'un fil libre comprise |
| `sd_pre` / `sd_model` / `sd_post` | StreamDiffusion : préparation de l'image, modèle, récupération du résultat |
| `rtmp_prep` / `rtmp_encode` | diffusion directe : mise au format (bandes noires, YUV) et encodage H.264, **une seule fois** pour toutes les plateformes |

« abandonnées » = images de la caméra arrivées pendant que le GPU travaillait (politique
« dernière image ») : c'est normal quand le GPU est plus lent que la caméra.

Essai sur ton Legion : lance le worker avec `SD_TENSOR_IO=0`, note la ligne au bout d'une
minute, relance avec `SD_TENSOR_IO=1`, compare `sd_pre`, `sd_post` et les images/s de sortie.
Garde `1` seulement si c'est mieux et que l'image est correcte.

L'encodage vidéo vers OBS (WHEP) est fait par aiortc et n'apparaît pas dans ces étapes :
surveille l'utilisation du processeur pendant le live pour l'estimer.

## Limites connues

- L'API Daydream et le processeur GPU n'ont pas encore été exécutés en conditions réelles.
- Le bandeau PARODIE est ajouté par la page de sortie (pas incrusté dans la vidéo du moteur).
- StreamDiffusion transforme toute l'image : visage et identité peuvent varier d'une image à l'autre ; l'intensité basse et les ControlNets (profondeur, pose) limitent ce défaut.
- Sessions en mémoire (un redémarrage de la console les perd) ; facturation non branchée (le grand livre de `ai_studio/` sera réutilisé).
- Diffusion directe sans l'exécutable `ffmpeg` (repli PyAV) : une plateforme qui accepte la connexion puis ne répond plus fige tout le worker, car PyAV garde le verrou de Python pendant l'ouverture. Installe `ffmpeg` (déjà présent dans l'image Docker du worker ; sous Windows : `winget install ffmpeg`).
- Une plateforme qui coupe n'est pas reconnectée automatiquement : relance la session.
