# Déployer la page de suivi sur laboratory.site

Page **publique** (décision de l'utilisateur), servie par un Worker Cloudflare
avec fichiers statiques, sur l'offre gratuite.

| Adresse | Contenu |
|---|---|
| `projets.laboratory.site` | page générale (tous les projets) |
| `labo.laboratory.site` | laboratoire de trading |
| `x402.laboratory.site` | atelier x402 |
| `vendeur.laboratory.site` | bot vendeur x402 (en attente) |

Le domaine racine `laboratory.site` n'est **pas** utilisé : il peut déjà servir
le VPS. Cloudflare refuse un « Custom Domain » sur un nom qui a déjà un
enregistrement CNAME : supprimer d'abord un éventuel CNAME existant sur l'un de
ces sous-domaines.

## Prérequis (une seule fois)

1. **Jeton API** limité, créé dans Cloudflare : *My Profile → API Tokens →
   Create Token*, avec les permissions *Account · Workers Scripts · Edit* et
   *Zone · Workers Routes · Edit* + *Zone · DNS · Edit* limitées à la zone
   `laboratory.site`.
2. Dans les réglages de l'environnement Claude Code (jamais dans le chat ni
   dans le dépôt) :
   - `CLOUDFLARE_API_TOKEN` = le jeton ;
   - `CLOUDFLARE_ACCOUNT_ID` = l'identifiant de compte (page *Overview* du domaine).
3. Accès réseau de l'environnement : autoriser `api.cloudflare.com` (npm est
   déjà autorisé pour installer Wrangler).

## Construire et déployer

```bash
python3 site/build_site.py --avec-tests    # génère site/dist et site/worker/projets.generated.js
node --test site/worker/index.test.mjs     # aiguillage des sous-domaines
cd site && npx --yes wrangler@4 deploy     # utilise CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID
```

Ajouter un projet : une entrée dans `site/projets.json` (slug en minuscules)
et la route correspondante dans `site/wrangler.jsonc` ; `tests/test_site.py`
vérifie que les deux listes concordent.

## Contenu publié

Uniquement l'état des projets, les scénarios synthétiques du laboratoire, le
résultat des tests et les titres des derniers commits. Ni secret, ni
identifiant, ni e-mail. Des en-têtes de sécurité sont servis via `dist/_headers`.
