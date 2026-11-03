# Sentinelle du laboratoire — https://sentinelle.labotory.site

Worker Cloudflare indépendant du serveur Oracle. Toutes les 5 minutes (cron), il vérifie
AI Live (`live.labotory.site/api/catalog`) et AI Studio. S'ils sont tous deux injoignables
3 fois de suite (≥ 10 min) et qu'aucun redémarrage n'a eu lieu depuis 30 min, il demande à
Oracle de redémarrer l'instance (`action=RESET`) via l'API OCI signée (clé RSA).

## Accès manuel (jeton requis : `Authorization: Bearer <SENT_TOKEN>`)

- `GET /etat` : état de l'instance chez Oracle + historique de la sentinelle
- `POST /verifier` : lance une vérification tout de suite
- `POST /redemarrer` : redémarre l'instance

## Où sont les secrets (jamais dans le dépôt)

Espace KV privé `coffre-labo` (compte Cloudflare, non relié à une page publique) :
`oci_api_key.pem` (clé privée de l'API Oracle), `oci_config.json` (identifiants non secrets :
utilisateur, empreinte, location, région, instance), `sentinelle_token`.
Le Worker les reçoit sous forme de secrets (`OCI_KEY`, `SENT_TOKEN`) et de variables.

État de la sentinelle : espace KV `sentinelle-labo`, clé `etat`.

## Ligne de commande

`ai_live/tools/oci_instance.py` (list / status / reboot / start) avec un fichier de config
au format `~/.oci/config` (variable `OCI_CONFIG`).
