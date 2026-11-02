# Pilote AI LIVE — se transformer en direct pendant un stream : deux chemins

> 2 novembre 2026. Objectif : pendant un stream (webcam, téléphone, OBS), transformer
> en temps réel son corps, son apparence, son personnage et son décor, par la voix,
> pour le divertissement et l'humour.
>
> Étiquettes : **[VENDEUR]** chiffre annoncé par le fournisseur, **[À VÉRIFIER]** à
> confirmer sur la source officielle, **[HYP]** hypothèse à mesurer.

---

## 0. Trois clarifications avant de choisir un chemin

**1. Ce n'est pas un LLM qui transforme l'image.** Il y a deux types de modèles différents :

| Rôle | Type de modèle | Exemples |
|---|---|---|
| Comprendre « transforme-moi en chevalier » | **LLM** (langage) | Claude Haiku, Gemini Flash, Llama/Qwen auto-hébergé |
| Produire 25–30 images par seconde transformées | **Modèle de diffusion vidéo temps réel** | StreamDiffusion (SD-Turbo / SDXL-Turbo), StreamDiffusionV2, LongLive, Krea Realtime, Decart Lucy (propriétaire) |

Le LLM est petit et bon marché. Le gros du coût et de la difficulté est dans le modèle de diffusion.

**2. Éviter Runway est cohérent ici.** Runway (Aleph) ne fait de toute façon pas de temps réel :
c'est de l'édition différée. Pour le live, les acteurs pertinents sont l'open source
(StreamDiffusion, Daydream Scope) et Decart. Mais attention : **tout fournisseur d'API
est aussi un concurrent potentiel** (Decart vend sa propre appli). C'est pourquoi le plan
ci-dessous mène au chemin auto-hébergé.

**3. « Devenir Emmanuel Macron » : ce qui est faisable, et la ligne que je recommande.**

| Ce que tu veux faire | Statut | Pourquoi |
|---|---|---|
| Devenir un personnage fictif (chevalier, robot, personnage de dessin animé, monstre, vieux pirate…) | ✅ Cœur du produit | Aucun problème de droit à l'image |
| Changer de décor, de vêtements, de style, ajouter neige, néons, etc. | ✅ | idem |
| **Caricature** reconnaissable d'une personnalité publique (style dessin, marionnette, Guignols), avec une mention **« PARODIE · IA »** incrustée en permanence dans l'image | ✅ Possible, avec garde-fous | La parodie des personnalités publiques est une tradition protégée, **à condition qu'il soit évident ou expressément indiqué qu'il s'agit d'un montage** |
| Visage **photoréaliste** d'une personne réelle (Macron ou autre), sans son accord, indiscernable du vrai | ❌ Je ne le construirai pas dans la plateforme | Voir ci-dessous |

Pourquoi la dernière ligne pose problème, même « pour rigoler » :
- **Droit français** : l'art. 226-8 du Code pénal (renforcé par la loi SREN de 2024) sanctionne la diffusion d'un
  contenu généré par algorithme reproduisant l'image ou la parole d'une personne sans son consentement, **sauf s'il
  apparaît à l'évidence qu'il s'agit d'un montage ou si c'est expressément mentionné** ; peines alourdies en cas de
  diffusion en ligne **[À VÉRIFIER : montants exacts]**.
- **UE (AI Act, art. 50)** : les « deepfakes » doivent être signalés comme tels.
- **Plateformes** : Twitch et YouTube sanctionnent l'usurpation d'identité trompeuse et exigent l'étiquetage des contenus
  synthétiques réalistes. Un clip sorti de son contexte (sans ton overlay) peut circuler comme une fausse déclaration
  d'un chef d'État : c'est là que le risque devient réel, pour toi et pour ta plateforme.
- **Fournisseurs** : les conditions d'utilisation des API temps réel interdisent en général l'usurpation de personnes
  réelles **[À VÉRIFIER pour Decart]** → risque de suspension du compte.
- **Licence** : l'outil de face-swap le plus répandu (modèle `inswapper` d'InsightFace, utilisé par Deep-Live-Cam)
  est sous **licence non commerciale** : inutilisable dans un produit payant de toute façon.

**Ce que la plateforme fera donc** : personnages fictifs illimités ; caricatures de personnalités publiques en
**style non photoréaliste** avec bandeau « PARODIE · IA » incrusté côté serveur (impossible à retirer, il reste sur
les clips) ; visage réaliste d'une personne réelle **uniquement si cette personne a donné son accord vérifié**
(par exemple un ami, ou toi-même). Ça garde tout l'humour, et c'est aussi ce qui rend le produit vendable aux
streamers sans risque de bannissement.

---

## 1. Le « tunnel » commun aux deux chemins

Quel que soit le moteur, le transport vidéo est le même. C'est la partie que **tu possèdes dans les deux cas**.

```
 SOURCE                      TON SERVEUR (cloud)                          SORTIE
┌──────────────┐  WebRTC  ┌──────────────────────────────────────────┐  WebRTC  ┌──────────────────┐
│ Webcam / OBS │ ───────▶ │ 1. Réception du flux (LiveKit / aiortc)   │ ───────▶ │ Page « sortie »   │
│ Téléphone    │  ou SRT  │ 2. Décodage → images (GPU)                │          │ = Browser Source  │
│ (navigateur, │          │ 3. Segmentation (toi / décor)             │          │   dans OBS        │
│ IRL Pro,     │          │ 4. MOTEUR DE TRANSFORMATION  ◀── chemin A ou B       │ → Twitch/YouTube/ │
│ Larix)       │          │ 5. Recomposition + bandeau PARODIE si besoin│        │   Kick (RTMP)     │
└──────────────┘          │ 6. Encodage → retour                      │          └──────────────────┘
        ▲                 │ 7. Flux original toujours conservé        │
        │ voix            │    (bouton « RETOUR ORIGINAL » < 200 ms)  │
        └───────────────▶ │ 8. STT → LLM (outils typés) → change le   │
                          │    prompt / le personnage sans couper     │
                          └──────────────────────────────────────────┘
```

Briques du tunnel (identiques A et B) :

| Brique | Choix recommandé | Remarque |
|---|---|---|
| Transport temps réel | **LiveKit** (open source, auto-hébergeable, ou LiveKit Cloud) ; alternative minimale : `aiortc` en Python | WebRTC = faible latence, fonctionne depuis un navigateur de téléphone |
| Ingest OBS / téléphone pro | **MediaMTX** (SRT, WHIP, RTMP → WebRTC) | IRL Pro / Larix / Moblin en SRT |
| Retour vers OBS | Page web « sortie » chargée en **Browser Source** | le plus simple ; WHEP en option |
| Segmentation | MediaPipe (personne, cheveux, visage) | permet « change le décor mais garde-moi » |
| Voix | STT en streaming (Deepgram / AssemblyAI / Whisper auto-hébergé) + LLM rapide avec outils `set_character`, `set_background`, `set_style`, `revert_original` | « retour à l'original » traité par mot-clé, sans LLM |
| Mesure | horloge à l'écran filmée + horodatage → latence p50/p95, images/s, coût/min | indispensable pour comparer A et B |
| Facturation | le grand livre déjà écrit dans `ai_studio/` (réservation par tranches de minutes) | réutilisé tel quel |

---

## 2. Chemin A — ton propre moteur sur un GPU loué

### Ce que ça veut dire concrètement

Tu loues une machine avec une carte graphique (RunPod, Vast.ai, Lambda…), tu y installes un modèle
open source de diffusion temps réel, et ton serveur lui envoie les images du stream.

### Modèles candidats

| Modèle | Ce qu'il sait faire | Images/s | GPU nécessaire | Licence | Verdict pilote |
|---|---|---|---|---|---|
| **StreamDiffusion + SD-Turbo** (512 px) | Stylisation forte de toute l'image (dessin animé, peinture, cyberpunk) | ~20–60 **[VENDEUR/HYP]** | 1 × RTX 4090/5090 | Code Apache-2.0 ; poids SD-Turbo : licence Stability Community (gratuit sous 1 M$ de CA) | ✅ **Démarrage** |
| **StreamDiffusion + SDXL-Turbo + ControlNet (pose/profondeur) + IP-Adapter** | Personnage défini par une **image de référence**, qui suit tes mouvements | ~15–25 **[VENDEUR]** | 1 × RTX 5090 ou L40S | idem SDXL ; vérifier chaque ControlNet/IP-Adapter | ✅ **Cible pilote** (« deviens ce personnage ») |
| **StreamDiffusionV2 / LongLive (Wan 1,3B)** via **Daydream Scope** | Transformation vidéo plus cohérente d'une image à l'autre | ~64 sur **4 × H100** (mesuré, article) ; bien moins sur 1 GPU | 1–4 × H100 | Wan : Apache-2.0 | ⚠️ Phase 2 (cher) |
| Krea Realtime 14B | Haute qualité, long | 11 sur 1 × B200 **[VENDEUR]** | B200 | Apache-2.0 **[À VÉRIFIER]** | ❌ trop cher pour un flux par utilisateur |

**Le point faible honnête du chemin A** : avec StreamDiffusion, la transformation « scintille » d'une
image à l'autre et ton identité peut dériver. Remèdes (à coder) : masque de segmentation, lissage
temporel, recomposition du décor « préparé » derrière toi, prompts et références fixes par personnage.

### Étapes

| Semaine | Ce que tu fais | Résultat mesurable |
|---|---|---|
| 1 | Installer StreamDiffusion **sur ton Legion (RTX 4070, 8 Go)** avec SD-Turbo + TensorRT ; webcam → fenêtre de sortie | Premier effet en direct, **0 € de serveur** ; nombre d'images/s mesuré (estimé 8–20 **[HYP]**) |
| 2 | Louer un RTX 5090 à l'heure (RunPod ~0,69 $/h **[À VÉRIFIER]**) ; même code dans un conteneur Docker | Images/s et qualité sur un vrai GPU |
| 3 | Le tunnel : navigateur/OBS → LiveKit → GPU → page de sortie → OBS Browser Source | Stream test sur Twitch ; latence p95 mesurée |
| 4 | Personnages par image de référence (IP-Adapter) + ControlNet pose ; segmentation + décors préparés | « Deviens ce personnage », « change le décor » |
| 5 | Voix → LLM → changement de personnage sans couper ; bouton retour original ; bandeau PARODIE | Démo complète pilotée à la voix |
| 6 | Arrêt automatique des GPU inactifs, facturation à la minute, 5–10 testeurs streamers | Coût réel/minute, retours utilisateurs |

### Coûts (ordres de grandeur)

| Poste | Estimation |
|---|---|
| GPU RTX 5090 loué, 1 flux par GPU | 0,69 $/h ≈ **0,012 $/min** (+ 30–50 % de temps d'inactivité au début) **[À VÉRIFIER]** |
| Développement | 6 semaines de ton temps + agents IA (150–400 $/mois) + ~50–150 $ de GPU de test |
| Prix de vente possible | 0,08–0,15 $/min → marge brute élevée **si** l'utilisation des GPU est bonne |

**Avantages** : marge forte, indépendance, aucune règle de fournisseur, données privées, c'est **ce qui fait de toi un concurrent**.
**Inconvénients** : qualité inférieure à Decart au départ, plusieurs semaines de travail, tu gères les pannes et la montée en charge.

---

## 3. Chemin B — payer une API temps réel

### Fournisseurs (sans Runway)

| Fournisseur | Offre | Accès | Coût | À vérifier |
|---|---|---|---|---|
| **Decart — Lucy 2.5** | Transformation de flux en temps réel par prompt (personnage, vêtements, décor) ; 30 i/s, < 40 ms **[VENDEUR]** | API + SDK WebRTC (`@decartai/sdk`), aussi via **fal.ai** (`decart/lucy-2-5/realtime`) | ~3 $/h cité par une source secondaire **[À VÉRIFIER]** | Tarif officiel, conditions sur les personnes réelles, rétention des données |
| **Daydream (Livepeer)** | StreamDiffusion hébergé (le même moteur que le chemin A, géré pour toi) | API | **[À VÉRIFIER]** | Tarif, qualité, disponibilité |
| **fal.ai** (temps réel) | Point d'accès unique à plusieurs moteurs temps réel | API WebRTC | à l'usage | Liste des modèles temps réel disponibles |

### Étapes

| Semaine | Ce que tu fais | Résultat |
|---|---|---|
| 1 | Compte Decart (jetons gratuits pour développeurs) ; page web : webcam → SDK Decart → sortie ; ajout dans OBS | **Démo en quelques jours**, qualité maximale |
| 2 | Voix + LLM qui change le prompt ; bandeau PARODIE ; bouton retour original | Démo complète pilotée à la voix |
| 3 | Mesure du coût réel/minute, plafonds, facturation à la minute | Prix de vente fondé sur des chiffres |

### Coûts

| Poste | Estimation |
|---|---|
| API Decart | ~3 $/h ≈ **0,05 $/min** **[À VÉRIFIER]** |
| Prix de vente possible | 0,12–0,20 $/min → marge plus faible et dépendante du fournisseur |

**Avantages** : résultat spectaculaire tout de suite, presque rien à gérer côté GPU.
**Inconvénients** : marge faible, dépendance totale, règles d'usage du fournisseur, tu revends le produit d'un concurrent.

---

## 4. Comparaison et recommandation

| Critère | A — GPU loué + open source | B — API (Decart, Daydream) |
|---|---|---|
| Délai pour une démo | 3–5 semaines | **3–7 jours** |
| Qualité au départ | Moyenne (scintillement) | **Haute** |
| Coût par minute | **~0,012–0,02 $** | ~0,05 $ **[À VÉRIFIER]** |
| Marge | **Forte** | Faible |
| Indépendance | **Totale** | Nulle |
| Règles d'usage | **Les tiennes** (dans le cadre de la loi) | Celles du fournisseur |
| Difficulté technique | Élevée | Faible |
| Fait de toi un concurrent | **Oui** | Non |

### Ma recommandation : les deux, dans cet ordre, derrière le même tunnel

1. **Semaine 1 – en parallèle :**
   - chemin B (Decart) pour avoir **la démo de référence** et savoir ce que « bien » veut dire ;
   - chemin A en local sur ton Legion (StreamDiffusion SD-Turbo) pour **apprendre le moteur gratuitement**.
2. **Semaines 2–4** : tu construis **le tunnel** (LiveKit, page de sortie OBS, voix, bascule original) une seule fois, avec un « interrupteur » de moteur, comme le registre de moteurs de `ai_studio/`.
3. **Semaines 4–6** : tu passes le chemin A sur GPU loué et tu le compares au chemin B **sur les mêmes mesures** (images/s, latence, qualité notée par des testeurs, coût/minute).
4. **Ensuite** : le moteur auto-hébergé devient le moteur par défaut (marge, indépendance) ; l'API ne sert plus que de repli ou de mode « qualité maximale ». C'est le chemin pour devenir un concurrent, pas un revendeur.

Ce qui est déjà prêt dans le dépôt et se réutilise : grand livre de crédits, devis, registre de moteurs
par manifestes, modération, journal des coûts (`ai_studio/`). Le pilote Studio n'est donc pas perdu :
c'est le socle de facturation du pilote Live.

---

## 5. Décisions à prendre (toi)

1. **Ouvrir un compte Decart** (jetons développeur gratuits) pour la démo de référence — oui / non.
2. **Budget GPU de test** pour le chemin A (je propose 100 $ maximum, avec arrêt automatique des machines).
3. **Personnages du pilote** : je propose 5 personnages fictifs + 1 caricature « PARODIE » non photoréaliste.

Dès que tu valides, je commence par la semaine 1 : installation de StreamDiffusion utilisable sur ton
Legion sous Windows, et la page web webcam → moteur → sortie OBS.
