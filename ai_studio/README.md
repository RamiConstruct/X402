# AI STUDIO — pilote A

Un utilisateur ouvre le site, importe une vidéo, sélectionne une plage, décrit la
modification, **voit le prix avant exécution**, accepte, suit le traitement et
télécharge le résultat. Chaque tâche, chaque appel moteur, chaque coût et chaque
erreur sont enregistrés.

Conception de référence : [`docs/ai_live_studio/ANALYSE_STRATEGIQUE.md`](../docs/ai_live_studio/ANALYSE_STRATEGIQUE.md) §4, §8, §9 et §14.1.

## État du lot 1

| Fonctionne et est testé | Pas encore fait |
|---|---|
| Comptes (e-mail + mot de passe, jetons de session) | Paiement réel (Stripe/Merchant of Record) — crédits de test en mode dev |
| Import vidéo avec contrôle du format, du poids et de la durée (FFprobe) | Stockage S3/R2 et upload direct navigateur → bucket |
| Planificateur FR/EN : instruction → étapes (génératif + montage local) | Planificateur LLM (même interface) |
| Registre de moteurs par manifestes YAML, routage Économique / Qualité, moteurs exclus expliqués | Masques par clic (SAM 2) |
| Devis signé avec durée de validité, plafond par tâche et plafond journalier | Modération par classifieur et contrôle des sorties |
| Grand livre en partie double : réservation → capture au coût réel (≤ devis) → libération ; remboursement automatique en cas d'échec ; idempotence | Timeline multi-pistes, export ProRes/OTIO |
| Édition **d'une plage seulement** : le reste de la vidéo est conservé intact et non facturé | Réconciliation automatique avec les factures fournisseurs |
| Versions non destructives (chaque résultat est une nouvelle version), comparaison avant/après | |
| Cache : même demande sur la même vidéo = résultat réutilisé gratuitement | |
| Montage local FFmpeg : vertical 9:16, carré, noir et blanc, étalonnage cinéma, tons chauds/froids, ralenti, accéléré, son coupé | |
| Simulateur hors ligne d'un moteur génératif payant (facturé au tarif Aleph, marqué « Simulation ») | |
| Adaptateurs **Runway** et **fal.ai** (testés contre des serveurs simulés, **jamais contre les vraies API**) | |
| Interface web responsive (clair/sombre), journal des tâches, mouvements de crédits, état des moteurs | |
| Reprise après plantage : tâches interrompues échouées et remboursées au redémarrage | |

## Démarrer en local

Prérequis : Python ≥ 3.11 et FFmpeg (`ffmpeg`, `ffprobe` dans le PATH).

```bash
cd ai_studio
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q          # 24 tests, hors ligne
.venv/bin/python -m studio serve       # http://127.0.0.1:8000
```

Sous Windows (ton Legion) : `py -m venv .venv`, `.venv\Scripts\pip install -e .[dev]`,
`.venv\Scripts\python -m studio serve` ; FFmpeg via `winget install Gyan.FFmpeg`.

Par défaut : **aucun fournisseur payant n'est appelé**. Le moteur génératif disponible
est le simulateur ; chaque compte reçoit 100 crédits de bienvenue et un bouton
« + 500 crédits de test » existe en mode développement.

## Activer un vrai fournisseur (décision humaine)

1. Vérifier sur la page officielle l'identifiant du modèle, l'endpoint et le tarif ;
   les reporter dans `engines/runway_aleph.yaml` (ou `fal_video_edit.yaml`) avec `verified_on`.
2. Définir un plafond de dépense **chez le fournisseur** (tableau de bord Runway / fal).
3. Lancer avec :
   ```bash
   STUDIO_ALLOW_PAID_PROVIDERS=true RUNWAYML_API_SECRET=... \
   STUDIO_PUBLIC_BASE_URL=https://ton-domaine \
   .venv/bin/python -m studio serve
   ```
   `STUDIO_PUBLIC_BASE_URL` permet au fournisseur de télécharger le segment via une URL
   signée de 1 h ; sans elle, l'adaptateur envoie un data URI (petits fichiers uniquement).
4. Faire un premier test de 2–3 secondes, puis comparer `python -m studio report` à la facture.

Quand les fournisseurs réels sont actifs, le simulateur est automatiquement retiré des devis.

## Ajouter un modèle

Créer un fichier `engines/<id>.yaml` (capacités, limites, tarif daté, marge, paramètres).
S'il passe par fal.ai, l'adaptateur `fal` générique suffit ; sinon écrire un adaptateur
dans `studio/providers/` (méthode `run(ctx) -> StepResult`) et l'enregistrer dans
`studio/providers/__init__.py`.

## Commandes d'administration

```bash
python -m studio engines          # état et tarifs des moteurs
python -m studio grant --email x@y.z --credits 500
python -m studio report           # coûts estimés vs réels par moteur, tâches, revenu
python -m studio check-ledger     # vérifie l'équilibre du grand livre
```

## Configuration (variables d'environnement)

Voir [`.env.example`](.env.example). Hors mode développement (`STUDIO_DEV_MODE=false`),
`STUDIO_SECRET_KEY` est obligatoire et le bouton de crédits de test disparaît.

## Déploiement sur le VPS

```bash
docker build -t ai-studio ai_studio
docker run -d --name ai-studio -p 127.0.0.1:8000:8000 -v /srv/ai-studio:/data \
  --env-file /srv/ai-studio/.env ai-studio
```

Placer un reverse proxy HTTPS devant (Caddy ou Cloudflare Tunnel). Un seul processus
(SQLite + worker intégré) suffit pour le pilote ; le passage à PostgreSQL se fait via
`STUDIO_DATABASE_URL` sans modifier le code (prévoir alors un worker séparé).

## Structure

```
ai_studio/
├── engines/            manifestes des moteurs (données, pas du code)
├── studio/
│   ├── api.py          routes HTTP + interface statique
│   ├── service.py      import, devis, acceptation, exécution, règlement, worker
│   ├── planner.py      instruction → étapes
│   ├── quotes.py       routage et chiffrage par mode
│   ├── engines.py      registre, tarifs, disponibilité
│   ├── ledger.py       grand livre en partie double
│   ├── money.py        unités entières et arrondis explicites
│   ├── media.py        FFmpeg (analyse, découpe, opérations, réassemblage)
│   ├── moderation.py   filtres avant exécution
│   ├── providers/      adaptateurs : local_ffmpeg, simulated, runway, fal
│   └── static/         interface web
└── tests/
```
