# Bilan et sauvegarde — 3 novembre 2026

## Vérifications du jour (toutes réussies)
| Contrôle | Résultat |
|---|---|
| Tests AI Live (serveur, flotte, parcours vidéo complets) | 91 / 91 (3 passages consécutifs) |
| Tests navigateur (rendu 1080/1440p, prédiction, Rust = JS, mode auto) | OK |
| Tests AI Studio | 29 / 29 |
| Tests à la racine (atelier x402, site) | 222 / 222 |
| Site : 15 langues | valides |
| Installation sur une copie neuve du dépôt (`tools/installer_pc.sh`) | tout installé, tous les tests passent |
| Pages en ligne : labotory.site (/, /suivi, /en/), live (/, /mobile.html, /api/catalog, motion.wasm, modèle silhouette), studio | 200 |
| Sentinelle | 0 échec, Oracle RUNNING, dernière vérification 200/200 |
| Serveur | en marche depuis 18 h ; 5 services actifs (console, programme GPU, AI Studio, tunnel, TURN) ; disque 14 % |
| Git | tout est poussé sur GitHub, rien en attente |

## Où est sauvegardé quoi
| Quoi | Où |
|---|---|
| Code, documents, scripts | GitHub `RamiConstruct/X402`, branche `claude/ai-live-studio-architecture-2td5sl` (+ export `x402.bundle`) |
| Clés, mots de passe, configuration et données du serveur (base AI Studio, fichiers .env, services, protections, tunnel) | Cloudflare KV `coffre-labo` → `sauvegarde-2026-11-03.tgz.b64` (privé, vérifié par relecture) |
| Clé API Oracle, jeton sentinelle | Cloudflare KV `coffre-labo` (déjà) |
| Liste d'attente, avancement | Cloudflare KV `laboratoire` |
| Mémoire du projet pour Claude | `CLAUDE.md` |

## Ce qui est en ligne
- **AI Live téléphone** : 15 langues, mode auto, rendu 480p à 1440p, fluidité (prédiction du mouvement, calcul en
  Rust/WebAssembly, silhouette), enregistrement d'essai 60 i/s, commandes vocales, personnages et décors.
- **Flotte de GPU automatique** : codée et testée, inactive tant qu'aucun compte GPU n'est configuré.
- **AI Studio** : 15 langues, crédits prêts pour Stripe (inactif).
- **Site** : 15 langues selon le pays, liste d'attente, page de suivi.
- **Protections** : sentinelle (redémarrage automatique via Oracle), chien de garde, mémoire d'échange.

## En attente de toi
1. Compte GPU (Vast.ai ou RunPod) → premier vrai test et activation de la flotte (sans Daydream).
2. Identité pour les pages légales (`docs/legal/`).
3. Compte Stripe (`docs/ai_live_studio/ACTIVER_STRIPE.md`).
4. Essai sur ton téléphone (1080/1440p, fluidité, silhouette).
5. Régénérer les clés passées dans la discussion et les mettre dans les réglages de l'environnement.
