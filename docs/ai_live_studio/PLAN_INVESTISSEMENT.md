# Plan d'investissement — 1 000 $ (à partir du 2026-11-03)

Objectif : passer de « ça marche pour moi » à « des inconnus paient et reviennent », sans brûler l'argent.
Règle : chaque dépense doit soit **prouver** quelque chose (qualité, coût par minute, envie d'acheter),
soit **débloquer** l'encaissement. Les prix sont des ordres de grandeur à vérifier au moment d'acheter.

## Le tunnel visé

Visiteur (accueil multilingue) → liste d'attente → e-mail d'invitation → premier essai gratuit (quelques minutes)
→ achat de crédits → utilisation → partage de vidéos (marque discrète) → nouveaux visiteurs.

Ce qui existe déjà : accueil 15 langues, liste d'attente, AI Live avec vraie IA (Daydream), AI Studio (crédits et
devis déjà codés, sans paiement réel), suivi du projet.
Ce qui manque : paiement, e-mails, comptes clients pour AI Live, essai gratuit encadré, mentions légales,
mesure des coûts réels.

## Priorités et budget

| Priorité | Quoi | Pourquoi | Budget |
|---|---|---|---|
| **P0** | Mesurer le coût réel de Daydream par minute (crédits payants) et la fluidité depuis des téléphones | Sans coût par minute, impossible de fixer un prix rentable | 60 $ |
| **P0** | Louer un GPU (RTX 4090 ou 5090, Vast.ai / RunPod, ~0,3–0,7 $/h) et lancer notre moteur + StreamDiffusionV2 | Comparer qualité/latence/coût avec Daydream ; c'est là que se fait la marge | 80 $ |
| **P1** | Paiement Stripe (gratuit à l'ouverture, commission par vente) + statut d'entreprise | Encaisser | 0–100 $ selon le pays |
| **P1** | E-mails (domaine labotory.site, service d'envoi type Resend/Postmark, offre gratuite au début) | Inviter la liste d'attente, reçus, récupération de compte | 0–20 $ |
| **P1** | Pages légales (CGU, confidentialité, cookies) — je rédige, relecture par un juriste conseillée | Obligatoire avant d'encaisser en Europe | 0–150 $ |
| **P2** | Relais vidéo Cloudflare (TURN) pour les réseaux difficiles (4G, entreprises) | Moins d'échecs de connexion ; coût quasi nul au début | 20 $ |
| **P2** | Supervision (erreurs, disponibilité) — offres gratuites | Savoir avant les clients quand ça casse | 0 $ |
| **P3** | Contenu de démonstration : 10 à 20 vidéos courtes faites avec AI Live | Le produit se vend en le montrant | 50 $ (GPU/crédits) |
| **P3** | Relecture des traductions par des natifs (anglais, espagnol, arabe en premier) | Crédibilité sur les marchés visés | 90 $ |
| **P3** | Test publicitaire très ciblé (TikTok/YouTube Shorts) vers la liste d'attente | Mesurer le coût d'une inscription | 200 $ |
| Réserve | Imprévus, prolongation GPU, outils | | 230 $ |
| **Total** | | | **≈ 1 000 $** |

L'abonnement Claude Team est en dehors de ce budget (tarif sur claude.com/pricing). Il sert surtout à disposer de
plus d'utilisation pour que je travaille plus longtemps sans interruption.

## Ordre des opérations

**Semaine 1 — prouver**
1. Recharger des crédits Daydream ; mesurer coût/minute et images/seconde en 4G et en Wi-Fi (outil déjà prêt).
2. Rendre public le paquet `x402-live-worker` et me donner une clé Vast.ai ou RunPod : je loue, je teste, je libère
   (arrêt automatique déjà codé). Comparatif chiffré Daydream / GPU loué.
3. Fixer le prix : coût/minute × marge (viser ≥ 60 %), avec un essai gratuit plafonné.

**Semaine 2 — encaisser**
4. Comptes clients AI Live (aujourd'hui : un seul mot de passe), crédits partagés avec AI Studio.
5. Stripe (achat de crédits), reçus par e-mail, pages légales.
6. Invitation automatique de la liste d'attente par vagues, dans la langue de chaque inscrit.

**Semaine 3 — faire venir**
7. Commandes vocales multilingues (les 15 langues du site).
8. Vidéos de démonstration et page « exemples ».
9. Petit test publicitaire, mesure : visite → inscription → essai → achat.

## Optimisation vidéo — fait et à venir

Fait (2026-11-02) : capture en 512×512 au lieu de 1280×720 (≈3,5× moins de données), débit plafonné à 1,5 Mbit/s,
priorité à la fluidité, tampon de lecture minimal, démarrage en parallèle, collecte réseau écourtée, micro coupé en
mode essai, mesures réseau affichées, 3 modes de rendu, graine fixe anti-scintillement.

À venir (demande l'argent ci-dessus) :
- **GPU loué proche de l'utilisateur** (choix de la région) : la latence réseau baisse directement.
- **Moteurs TensorRT précompilés** dans l'image GPU : démarrage en secondes au lieu de minutes.
- **StreamDiffusionV2** : rendu plus stable d'une image à l'autre.
- **Connexion directe navigateur ↔ GPU** (déjà le cas avec Daydream), relais TURN seulement en secours.
- **Ajustement automatique** du mode (Rapide/Équilibré/Qualité) selon la qualité réseau mesurée.

## Ce dont j'aurai besoin de toi

- Crédits Daydream et/ou clé Vast.ai ou RunPod (avec un plafond de dépense côté fournisseur).
- Rendre public le paquet GitHub `x402-live-worker`.
- Compte Stripe à ton nom (je fais l'intégration).
- Choix du pays/statut de l'entreprise (pour les mentions légales et la TVA).
