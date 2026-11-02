# Le Laboratoire — https://labotory.site

Page publique d'avancement des projets, servie par un Worker Cloudflare (indépendante du serveur Oracle).

| Fichier | Rôle |
|---|---|
| `avancement.json` | **Source de vérité** : où on en est, projets, infrastructure, journal |
| `worker.js` | Génère la page à partir des données stockées dans le KV `laboratoire` (clé `avancement`) |
| `preview.mjs` | Aperçu local : `node site/laboratoire/preview.mjs` → `apercu.html` |
| `wrangler.jsonc` | Déploiement manuel possible : `npx wrangler deploy` |

## Mettre à jour la page

1. Modifier `avancement.json` (date `mis_a_jour`, `maintenant`, projets, ajout en tête du `journal`).
2. Envoyer le fichier (le jeton est un secret du Worker, copie sur le serveur dans `/root/labo/update.token`) :
   ```bash
   curl -X PUT -H "Authorization: Bearer $LABO_UPDATE_TOKEN" --data-binary @site/laboratoire/avancement.json https://labotory.site/avancement.json
   ```
   (ou `npx wrangler kv key put --binding LABO avancement --path avancement.json --remote`).
   La page change en moins d'une minute, sans redéploiement.
3. Vérifier : la page en ligne doit être identique à `apercu.html`.

Règle : page **publique** — jamais de secret, d'adresse IP, d'identifiant ni de donnée personnelle.
