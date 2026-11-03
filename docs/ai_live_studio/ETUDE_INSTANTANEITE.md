# Étude : instantanéité et qualité 1080p pour AI Live (novembre 2026)

## 1. Quel modèle tourne où

Ce n'est pas un LLM (modèle de texte) qui transforme l'image : c'est un **modèle de diffusion** (image ou vidéo).
Un modèle de langage n'intervient que pour comprendre la commande vocale, et nos règles locales suffisent déjà.

| Où | Ce qui tourne | Pourquoi là |
|---|---|---|
| **Téléphone** | caméra, encodage, reconnaissance vocale (navigateur), **agrandissement 1080p**, **lissage et prédiction du mouvement** (§4) | gratuit pour nous, zéro délai réseau |
| **GPU proche de l'utilisateur** (Singapour, Tokyo…) | modèle de diffusion temps réel | seul calcul lourd ; la distance fixe le délai |
| **Petit serveur (console)** | sessions, crédits, commandes → paramètres | aucune vidéo ne le traverse |

Budget de délai visé (du geste à l'image transformée) : **< 150 ms**, dont le réseau est la plus grosse part
si le GPU est loin (Europe → Asie : +150 à 250 ms aller-retour). D'où le GPU en Asie.

## 2. Le 1080p

Générer directement en 1080p, c'est environ **8 fois plus de pixels** qu'en 512×512, donc environ 8 fois plus de
calcul : impossible en temps réel sur une carte abordable. Les acteurs du secteur font autrement :

1. **Générer en 512 à 720p**, là où le modèle est rapide et stable.
2. **Agrandir en 1080p** avec un modèle de super-résolution rapide : quelques millisecondes par image sur RTX 4090
   (Real-ESRGAN compact, NVIDIA VSR). Il peut même tourner **sur le téléphone** (WebGPU), donc sans frais serveur.
3. **Réinjecter les détails réels** : contours et visage viennent de la caméra en pleine résolution.

Les super-résolutions « diffusion » (FlashVSR, Stream-DiffVSR) sont plus belles mais pas encore temps réel en 1080p
(environ 17 images/s sur A100 pour FlashVSR, 0,33 s par image en 720p pour Stream-DiffVSR) : à suivre pour AI Studio.
Preuve que le 1080p est atteignable : Decart annonce son modèle Lucy 2.0 en **1080p à 30 images/s** en temps réel,
sur de gros GPU.

**Plan :** proposer 480p, 720p et 1080p (agrandi) ; mode automatique selon le réseau ; pas de 4K pour l'instant.

## 3. Stable Diffusion ou notre propre modèle ?

| Génération | Exemples | Limite |
|---|---|---|
| **Image par image** (notre base actuelle) | StreamDiffusion + SD-Turbo / SDXL-Turbo (Daydream) | chaque image est refaite sans mémoire : scintillement, visage qui « bouge » |
| **Vidéo causale** (nouvelle génération) | StreamDiffusionV2 (Wan 2.1 1.3B, MLSys 2026), MirageLSD et Lucy 2.0 (Decart) | garde la mémoire des images précédentes : image stable, cohérente |

Entraîner un modèle **à partir de zéro** coûte des millions de dollars : non. En revanche, avoir **notre modèle
adapté**, c'est réaliste et c'est la bonne piste :

- partir d'un modèle ouvert causal (Wan 1.3B via StreamDiffusionV2) ;
- **le distiller** en 1 à 2 étapes de calcul, puis le compiler (TensorRT, FP8) : 2 à 3 fois plus rapide ;
- **un petit module (LoRA) par personnage** (chevalier, robot…), entraîné sur nos images de référence :
  quelques dizaines de dollars de GPU chacun, et un rendu plus fidèle qu'une simple description texte.

## 4. La prédiction (ton idée)

L'intuition est juste, et c'est ainsi que fonctionnent la réalité virtuelle et les jeux en ligne. Mais il faut
prédire **au bon niveau** :

- ❌ **Prédire et calculer à l'avance les images futures** : chaque image possible coûte autant qu'une vraie image.
  Et si la personne fait autre chose, on affiche une erreur visible. Pas rentable.
- ✅ **Prédire le mouvement** (squelette, flux de pixels) : presque gratuit, quelques millisecondes.
  Le téléphone **déforme la dernière image transformée** selon le mouvement réel de la caméra, en attendant la
  suivante, comme le « reprojection » des casques VR.
  Résultat : le GPU produit 12 à 15 images/s, l'écran en affiche 30 à 60, et le geste paraît instantané.
- ✅ **Réutiliser plutôt que recalculer** : les modèles causaux gardent en mémoire (cache) ce qu'ils ont déjà
  calculé ; seule la nouveauté est traitée. Le fond immobile n'a pas besoin d'être refait à chaque image.
- ✅ **Mettre en tampon ce qui ne bouge pas** : le personnage choisi (son module, sa description, son visage de
  référence) est préparé une fois, avant le début du direct. Le changement de personnage devient immédiat.
- ⚠️ **Tampon d'images** : il lisse le débit mais **ajoute du délai**. On le garde minimal (1 à 2 images).

## 5. Feuille de route

| Étape | Quoi | Gain attendu |
|---|---|---|
| 1. Tout de suite | GPU en Asie ; 720p + agrandissement 1080p côté téléphone | −150 à 250 ms ; image nette |
| 2. | Lissage et reprojection du mouvement sur le téléphone | fluidité 30–60 images/s perçues |
| 3. | Essai StreamDiffusionV2 sur notre GPU (Vast.ai, quelques heures) vs Daydream | mesure qualité, délai et coût réels |
| 4. | Distillation et compilation, puis un module par personnage | ×2–3 vitesse, personnages fidèles |
| 5. | Notre modèle maison (base ouverte + entraînement ciblé) | atout propriétaire, coût par minute plus bas |

Aucune de ces étapes n'engage de dépense sans accord.

## Sources

- [StreamDiffusionV2 — article MLSys 2026](https://proceedings.mlsys.org/paper_files/paper/2026/file/698cfaf72a208aef2e78bcac55b74328-Paper-Conference.pdf) ; [code](https://github.com/chenfengxu714/StreamDiffusionV2) ; [résumé](https://www.emergentmind.com/topics/streamdiffusionv2)
- [Portage StreamDiffusionV2 sur Trainium2](https://github.com/KrishJani/Live-Streaming-Video-Diffusion-on-Trainium2) ; [Cerebrium — délai par image](https://cerebrium.ai/resources/real-time-video-generation-latency-per-frame-serverless-gpu)
- [Decart — MirageLSD / Lucy 2.0](https://decart.ai/mirage-lsd) ; [PetaPixel](https://petapixel.com/2025/07/18/mirage-is-the-worlds-first-ai-video-that-can-transform-live-footage-in-real-time)
- [FlashVSR (CVPR 2026)](https://zhuang2002.github.io/FlashVSR) ; [Stream-DiffVSR](https://arxiv.org/html/2512.23709)
