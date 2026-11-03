# Remise en question — 3 novembre 2026

Relecture critique de tout ce qui a été fait, à la lumière de ce qui est sorti entre juin et novembre 2026
(mes connaissances s'arrêtent en juin ; les nouveautés ci-dessous viennent de recherches faites aujourd'hui).

## 1. Ce que je ferais différemment

| Sujet | Ce qui a été fait | Ce que j'aurais dû faire | Gravité | Correction |
|---|---|---|---|---|
| **Branche principale** | Tout le travail (75 enregistrements) est sur une branche de travail ; `main` est resté au 2 novembre | Fusionner régulièrement de petits lots dans `main` | Haute : `main` ne reflète pas le projet | Demande de fusion à ouvrir (avec ton accord) |
| **Tests sur GitHub** | Seule l'image GPU était construite automatiquement | Tous les tests à chaque envoi | Moyenne | ✅ fait aujourd'hui (`tests.yml`) |
| **Versions anti-cache** | Mises à jour à la main à chaque mise en ligne | Calcul automatique | Moyenne (oubli = vieille version servie) | ✅ fait (`tools/versionner.py`, vérifié par les tests) |
| **Secrets** | Clés collées dans la discussion, gardées dans l'espace temporaire | Variables d'environnement dès le premier jour | Haute | Coffre Cloudflare + liste des variables ; reste à régénérer les clés exposées |
| **Mise en ligne** | Archive + scp + ssh à la main, 2 copies du code sur le serveur | Un script ou une action GitHub, une seule copie | Moyenne | À faire (script `tools/deployer.sh`) |
| **Serveur** | Oracle gratuit 1 Go à Sydney | 5–20 $/mois à Singapour plus tôt | Haute : panne de 5 h, plus loin de l'Asie | À décider (aucune dépense sans ton accord) |
| **Daydream** | Fonctions avancées construites pour Daydream (images de référence, visage) | Tester notre propre GPU dès le début (≈ 10 $) | Moyenne : effort en partie perdu | Phase 1 de la feuille de route |
| **Dépendance externe** | Bibliothèque de silhouette chargée depuis un CDN public | L'héberger chez nous | Faible | À faire |
| **Code du navigateur** | JavaScript sans types ni outil de construction | TypeScript + esbuild (types, empreintes de fichiers automatiques) | Faible aujourd'hui, monte avec la taille | Quand on attaque la phase 2 |

**Ce que je referais pareil** : petits lots testés, documents honnêtes (« estimation » / « mesuré »), calculs sur le
téléphone (gratuit pour nous), flotte de GPU sans dépendance, garde-fous de dépense, 15 langues dès le départ.

## 2. Nouveautés de juin à novembre 2026 et ce qu'elles changent

| Nouveauté | Ce que c'est | Impact pour nous | Décision |
|---|---|---|---|
| **Modèles vidéo « causaux » temps réel** : StreamDiffusionV2 (MLSys 2026), **Causal Forcing** (ICML 2026, annoncé temps réel sur une seule RTX 4090), Krea Realtime 14B (11 i/s sur B200) | Génèrent la vidéo image après image avec mémoire : image stable, cohérente | **Le plus important.** Notre moteur (StreamDiffusion image par image) est la génération d'avant | Le banc d'essai de la phase 1 compare : StreamDiffusion, StreamDiffusionV2, Causal Forcing. Krea 14B trop lent pour le direct |
| **WebGPU partout** (iPhone avec iOS 26, Chrome Android ; manque Firefox Android) | Calcul généraliste sur la puce graphique du navigateur | Le calcul du mouvement pourrait passer du processeur (Rust) à la puce graphique, encore plus vite ; petits modèles d'IA sur le téléphone | Passer `rendu.js` en WebGPU avec WebGL2 en secours (phase 2–3) |
| **Mojo 1.0, open source** (août 2026, Apache 2.0 ; Modular racheté par Qualcomm) | Langage proche de Python pour écrire des calculs GPU rapides, sur NVIDIA, AMD et Apple | Utile pour nos propres noyaux GPU (agrandissement, images intermédiaires) sans CUDA | À essayer en phase 3–4, pas avant ; preuves de production encore surtout indirectes |
| **LiveKit** (relais vidéo open source en Go, agents) | Gère pour des milliers d'utilisateurs : relais, reconnexion, enregistrement, envoi vers YouTube/Twitch | Remplacerait notre WebRTC fait main quand on passera à des centaines d'utilisateurs | Recommandé pour la phase 2 (bêta) ; notre code actuel suffit pour les tests |
| **Cloudflare Containers** (disponible depuis avril 2026) | Conteneurs courts sur le réseau Cloudflare | Pas de GPU trouvé ; conteneurs éphémères peu adaptés à la console | Non pour l'instant |
| **Python 3.14** (exécution sans verrou global, compilateur JIT) | Plus rapide pour le calcul en parallèle | Notre serveur attend surtout le réseau : gain quasi nul ; le JIT reste déconseillé en production | Rester en Python 3.12–3.13 |
| **MoQ / WebTransport** | Nouveau transport vidéo | Normes encore en brouillon, iPhone incertain | Surveiller |

## 3. Langages : faut-il changer ?

| Partie | Langage actuel | Verdict | Pourquoi |
|---|---|---|---|
| IA sur GPU | Python (PyTorch, TensorRT) | **Garder** | Tous les modèles sortent en Python ; le temps est passé dans la carte graphique |
| Noyaux GPU sur mesure (plus tard) | — | **Mojo ou CUDA/Triton** | Mojo si on veut aussi AMD/Apple ; à mesurer |
| Serveur (console, flotte, AI Studio) | Python (FastAPI) | **Garder** | Il attend le réseau ; Go ou Rust n'apporteraient pas de gain visible |
| Relais vidéo à grande échelle | WebRTC Python (aiortc) dans le programme GPU | **Passer à LiveKit (Go)** en phase 2 | Conçu pour des milliers de connexions |
| Calcul sur le téléphone | Rust → WebAssembly | **Garder**, puis WebGPU | ×9 mesuré ; WebGPU encore mieux là où il existe |
| Interface du navigateur | JavaScript | **TypeScript** en phase 2 | Moins d'erreurs quand le code grossit |
| Site vitrine | JavaScript (Cloudflare Workers) | **Garder** | Langage natif de Cloudflare |

## 4. Plan d'action (dans l'ordre)
1. ✅ Tests automatiques sur GitHub et versions anti-cache automatiques.
2. Ouvrir une demande de fusion vers `main` (avec ton accord) pour que `main` soit à jour.
3. Script de mise en ligne unique ; héberger la bibliothèque de silhouette chez nous.
4. Phase 1 (compte GPU) : banc d'essai StreamDiffusion / StreamDiffusionV2 / Causal Forcing sur RTX 4090 et H100.
5. Phase 2 : LiveKit, TypeScript, WebGPU, serveur à Singapour.
6. Phase 3–4 : Mojo pour nos noyaux GPU si les mesures le justifient.

## Sources
- [Causal Forcing (ICML 2026)](https://thu-ml.github.io/CausalForcing.github.io) · [code](https://awesome.ecosyste.ms/projects/github.com%2Fthu-ml%2FCausal-Forcing)
- [Krea Realtime 14B](https://github.com/krea-ai/realtime-video) · [notes de version](https://canvas.krea.ai/release-notes/krea-realtime-14b) · [modèle](https://huggingface.co/krea/krea-realtime-video)
- [StreamDiffusionV2 (MLSys 2026)](https://proceedings.mlsys.org/paper_files/paper/2026/file/698cfaf72a208aef2e78bcac55b74328-Paper-Conference.pdf) · [FlashVSR](https://github.com/OpenImagingLab/FlashVSR)
- [Mojo open source (Modular)](https://modular.com/blog/mojo-open-source) · [Phoronix](https://www.phoronix.com/news/Modular-Mojo-Open-Source) · [Better Stack](https://betterstack.com/community/guides/ai/mojo/)
- [LiveKit pour agents IA (Fora Soft)](https://www.forasoft.com/learn/livekit-for-ai-agents-guide) · [guide LiveKit](https://www.forasoft.com/blog/article/livekit-ai-agent-development)
- [Cloudflare Containers GA (Cloudmagazin)](https://www.cloudmagazin.com/en/2026/05/10/cloudflare-containers-outgrowing-workers/)
- [Python 3.14 (The Register)](https://www.theregister.com/2025/10/08/python_314_released_with_cautious/) · [free-threading en pratique](https://www.buildmvpfast.com/blog/free-threaded-python-3-14-should-you-switch-2026)
- [WebGPU dans les navigateurs (web.dev)](https://web.dev/blog/webgpu-supported-major-browsers)
