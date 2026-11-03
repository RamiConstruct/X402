# Objectif : 1440p, 90 images/s, délai ressenti nul (novembre 2026)

## Ce que la physique et l'état de l'art permettent

| Exigence | Faisable ? | Comment |
|---|---|---|
| **90 images/s affichées** | ✅ | L'IA produit 30 i/s ; le téléphone (déjà codé) ou le GPU fabrique 2 images intermédiaires sur 3 à partir du mouvement réel. Sur un écran 90/120 Hz, le rendu suit déjà la fréquence de l'écran. |
| **1440p à l'écran** | ✅ | L'IA génère en 720p ; agrandissement ×2 en 1440p (sur le téléphone dès aujourd'hui, par IA sur le GPU ensuite). |
| **1440p *généré directement* à 90 i/s** | ❌ aujourd'hui | 14 fois plus de pixels qu'en 512. Le record publié (StreamDiffusionV2, MLSys 2026) est ~64 i/s en 512×512 avec **4 H100**. Decart annonce 1080p à 30 i/s. Personne ne génère du 1440p à 90 i/s en direct. |
| **Délai zéro** | ❌ au sens strict, ✅ ressenti | Le réseau seul prend 20–60 ms aller-retour avec un GPU dans la même région. La prédiction du mouvement (déjà en ligne) compense ce délai à l'affichage : le geste paraît immédiat. Visé : < 100 ms réels, ~0 ressenti. |

## Architecture visée

```
Téléphone ──WebRTC──▶ GPU dans la région (Singapour, Tokyo…)
 caméra 720p 30 i/s     1. modèle vidéo causal distillé (1–2 étapes, TensorRT FP8) → 720p 30 i/s
                        2. agrandissement IA 720p → 1440p (quelques ms)
                        3. (option) images intermédiaires → 60–90 i/s
            ◀─WebRTC── 1440p H.265/AV1 (encodeur matériel du GPU)
 Téléphone : prédiction du mouvement + silhouette → 90 i/s affichées, délai compensé
```

## Coût (estimations, à mesurer)

| Niveau | GPU par utilisateur | Prix indicatif / heure / utilisateur |
|---|---|---|
| 720p IA → 1440p agrandi, 30 i/s IA | ½ à 1 H100 | ~1,5–3 $ |
| 1080p IA, 30 i/s | 1 à 2 H100 | ~3–6 $ |
| Record actuel (modèle 14B, 4 H100) | 4 H100 | ~10–12 $ |

Pour 300 utilisateurs simultanés au premier niveau : ~150–300 H100 aux heures de pointe, soit
**~450–900 $/heure**. À répercuter sur une offre « Ultra » vendue plus cher.

## Étapes

1. ✅ Téléphone : option 1440p, rendu à la fréquence de l'écran, enregistrement 60 i/s.
2. Banc d'essai sur 1 H100 (puis 4) : StreamDiffusionV2 en 720p, mesure i/s, délai, qualité.
3. Ajout au programme GPU : agrandissement IA ×2 et sortie 1440p (encodeur matériel).
4. Distillation + compilation TensorRT FP8 du modèle : objectif 720p à 30+ i/s sur 1 H100.
5. Flotte de GPU automatique par région, avec plafond de dépense.
6. Notre modèle maison entraîné pour nos personnages.
