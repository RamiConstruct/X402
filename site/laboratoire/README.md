# Le Laboratoire — https://labotory.site

Page publique d'avancement des projets, servie par un Worker Cloudflare (indépendante du serveur Oracle).

| Fichier | Rôle |
|---|---|
| `avancement.json` | **Source de vérité** : où on en est, projets, infrastructure, journal |
| `worker.js` | Génère la page à partir des données stockées dans le KV `laboratoire` (clé `avancement`) |
| `preview.mjs` | Aperçu local : `node site/laboratoire/preview.mjs` → `apercu.html` |
| `wrangler.jsonc` | Déploiement manuel possible : `npx wrangler deploy` |

## Pages servies par le Worker

| Chemin | Contenu |
|---|---|
| `/` | Page d'accueil commerciale (AI Live & AI Studio), statique dans `worker.js` (`landing()`) |
| `/suivi` | Suivi du projet (non indexé), rendu depuis le KV (`render()`) ; `/avancement` redirige ici |
| `/avancement.json` | Données en lecture (GET) et mise à jour authentifiée (PUT) |
| `POST /liste-attente` | Formulaire de liste d'attente (accord obligatoire, pot de miel anti-robots, même origine) ; stocké dans le KV sous `attente:<sha256 e-mail>` |
| `/liste-attente.json` | Export privé des inscrits (même jeton que la mise à jour) ; `python3 site/laboratoire/liste_attente.py > liste.csv` |

Le menu commun vient de `site/nav/nav.html` ; `python3 site/nav/apply_nav.py` le recopie dans les pages
AI Live / AI Studio et dans `worker.js` (constante `NAV_HTML`). CSS seul, sans JavaScript (CSP du Worker).

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
