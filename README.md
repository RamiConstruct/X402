# Atelier x402 — découverte de services (lot 1)

CLI Python locale qui **collecte, normalise et compare** des descriptions de
services d'IA susceptibles d'être payés via x402. Elle n'achète rien, n'appelle
aucun service pour une prestation payante et ne détient aucun secret.

| Ce que le lot 1 fait | Ce qu'il ne fait pas |
|---|---|
| Fixtures JSON **fictives**, utilisables sans réseau | Aucun paiement, aucune transaction, aucun portefeuille, aucune clé |
| Découverte HTTP publique **optionnelle, désactivée par défaut** | Aucun appel facturable (verrou en dur `BILLABLE_CALLS_ALLOWED = False`) |
| Normalisation avec provenance et inconnues explicites | Aucune conversion de devise, aucune devise devinée |
| Export JSON + synthèse Markdown | Aucun dashboard, aucun framework multi-agents |
| Simulation hors ligne du parcours x402 | Aucune compatibilité x402 revendiquée (voir `docs/parcours_x402.md`) |

Contexte budgétaire : budget annoncé de **17, devise non confirmée**.
**Aucune dépense n'est autorisée.** Tant que la devise n'est pas confirmée,
`CostGuard` refuse toute dépense, même hypothétique.

## Prérequis

Python 3 (testé uniquement avec 3.13.17), sans aucune dépendance (bibliothèque standard uniquement).
Toutes les commandes se lancent depuis la racine du dépôt.

## Commandes

```bash
make test                                  # = python3 -m unittest discover -s tests -t . -v
python3 -m atelier_x402 discover           # fixtures -> sorties/decouverte.json + sorties/synthese.md
python3 -m atelier_x402 compare            # comparaison JSON + couverture, erreurs et 402 observées
python3 -m atelier_x402 providers          # fournisseurs IA et leur état
python3 -m atelier_x402 simulate-x402 --all
python3 -m atelier_x402 check-cost --price 0.01 --currency USDC --unit per_request
python3 -m atelier_x402 bazaar --all      # normalise les fixtures Bazaar (hors ligne)
```

Découverte HTTP (désactivée par défaut, ne pas utiliser sans décision explicite) :

```bash
python3 -m atelier_x402 discover --enable-http \
  --allow-host catalogue.exemple.org --http-source https://catalogue.exemple.org/services.json
```

Elle n'attend que le **format de l'atelier** (`{"services": [...], "next": "..."}`
ou une liste). Ce n'est pas le format d'une API de découverte x402 (Bazaar, MCP
ou autre) : aucune compatibilité n'est revendiquée. Un document qui ne respecte
pas ce schéma est signalé comme « schéma invalide », jamais comme une liste vide.

**Couverture et code retour** : `discover` et `compare` indiquent une couverture
`complete`, `partielle` (erreurs, 402 ou éléments invalides à côté de services
lus), `echec` (aucun service lu) ou `vide` (aucune donnée : ce n'est pas une
réussite). Le code retour vaut 0 seulement si la couverture est `complete`, et 3
sinon. Les montants JSON sont lus en `Decimal` exact (`parse_float=Decimal`) et
exportés en texte, sans passer par un flottant.

## Bazaar (x402 v2), hors ligne

`atelier_x402/bazaar.py` normalise les réponses de découverte Bazaar **déjà
chargées**, avec des fonctions pures : il n'appelle ni facilitateur, ni ressource,
ni outil MCP, et ne charge jamais une référence de schéma externe.

Formats couverts, et seulement eux : ceux du dépôt `x402-foundation/x402` au
commit `14bc0fb` (voir `fixtures/bazaar/MANIFEST.json`) :

| Réponse | Enveloppe | Couverture |
|---|---|---|
| Liste `GET /discovery/resources` | `x402Version`, `items`, `pagination{limit, offset, total}` | `complete` si tout le total est lu ; `partial` sinon ; `unknown` sans pagination |
| Recherche `GET /discovery/search` | `x402Version`, `resources`, `partialResults?`, `pagination?` (objet `{limit, cursor}` ou `null`) | `partial` si `partialResults` vaut vrai ou si un curseur est présent ; `complete` si `partialResults` vaut faux ; `unknown` sinon |
| Variante de recherche | `limit` et `cursor` à la racine (pagination propre au facilitateur, citée par la doc) | signalée comme `racine` |

- Une enveloppe avec `items` **et** `resources` est rejetée, sans choix arbitraire.
- Toutes les offres `accepts` sont conservées dans l'ordre. `amount` reste une
  chaîne d'entier exacte, même au-delà de 2^53. Aucune décimale d'actif ni
  conversion USD n'est supposée, et un montant absent n'est jamais zéro.
  `offer_cost_estimate` renvoie un prix inconnu : `CostGuard` refuse toujours.
- La comparaison n'a lieu qu'entre offres `exact` de même réseau et de même
  actif, en unités atomiques. `upto` est un plafond, jamais un coût final.
- MCP : l'identifiant est le couple (`resource`, `toolName`). Deux outils d'une
  même ressource restent séparés. Un `toolName` manquant est diagnostiqué, et
  `mcp://…` est un identifiant, pas une URL à appeler.
- Métadonnées `serviceName`, `tags` et `iconUrl` : règles d'écartement de la
  spécification (l'icône n'est jamais chargée).
- Les fixtures `fixtures/bazaar/` sont **synthétiques** (provenance `fictif`) :
  seule leur structure suit les sources. Le chargeur refuse un fichier absent du
  manifeste ou dont l'empreinte SHA-256 diffère.

La commande `bazaar` est séparée : `discover` et `compare` (format historique de
l'atelier) restent inchangées.

## Modèle normalisé

Chaque service devient un enregistrement avec : `provider`, `service_name`,
`capability` (`texte`, `code`, `recherche`, `image`, `audio`, `embeddings`,
`inconnue`), `source` (type, URI, date UTC de collecte), `observed_at_utc`,
`price` (`amount` décimal, `currency`, `unit`, valeur brute), `payment_protocol`,
`network`, `provenance`, `verification_status`, `unknowns`, `warnings`, `raw`
(brut, secrets masqués).

**Provenance**, imposée par la source et jamais par la donnée :

| Valeur | Sens | Produite dans ce lot ? |
|---|---|---|
| `fictif` | Donnée inventée (fixtures) | oui |
| `declaration_commerciale` | Affirmation publiée par un tiers, non vérifiée | oui (HTTP) |
| `teste_reellement` | Résultat d'un test exécuté par l'atelier | **non**, refusée par `normalize_item` |

Une source qui se déclare « testée » ou « vérifiée » reste `non_verifie` et
reçoit un avertissement.

**Inconnues** : champ absent ou illisible, montant négatif ou non fini, symbole
ambigu (`$`, `€`…), date sans fuseau ou unité non reconnue donnent tous `None` et
une entrée dans `unknowns`. La comparaison ne classe que des prix complets de
même capacité, devise et unité. USDC n'est pas USD.

## Architecture

```
atelier_x402/
  models.py, normalize.py, redact.py, report.py, cli.py
  discovery/   base.py (interface) · fixtures.py · http_public.py · netguard.py
  providers/   base.py (interface) · simulated.py · registry.py (adaptateurs désactivés)
  costs/       guard.py (CostGuard, BudgetPolicy, CostEstimate)
  bazaar.py    adaptateurs Bazaar hors ligne (liste, recherche, offres, MCP)
  x402/        flow.py (simulation hors ligne)
fixtures/      services_fictifs.json · x402_scenarios_fictifs.json   (marqués "fictif": true)
               bazaar/ (10 fixtures synthétiques + MANIFEST.json)
tests/         unittest, réseau bloqué pendant les tests
docs/          parcours_x402.md · VISION.md (boussole du projet)
```

Les trois interfaces sont séparées : `DiscoverySource` (découverte),
`AIProvider` (fournisseurs d'IA), `CostGuard` (coûts). Un fournisseur ne peut
rien exécuter sans une décision `CostGuard`.

### Fournisseurs IA

Seul `simule` est actif : sorties déterministes, coût nul, marquées
`SIMULATION`. Les emplacements `api_generique_payante`, `service_x402` et
`abonnement_chat` sont désactivés, sans point d'accès ni prix, et leur coût
est inconnu. **Un abonnement de chat n'est pas un accès API** : il est refusé
même si on l'active par erreur.

### Contrôle des coûts

Une seule règle non satisfaite suffit à refuser ; toutes les raisons sont listées :
1. caractère facturable, prix, devise, unité ou estimation de consommation inconnus ;
2. devise du budget non confirmée ou différente (aucune conversion) ;
3. plafonds par appel ou par session non configurés ou dépassés ;
4. réessai payant, refusé dans tous les cas ;
5. verrou du lot : appels facturables bloqués.

Tout montant non `Decimal`, non fini (NaN, infini) ou négatif (prix, quantité,
plafonds, dépense de session) est refusé avant toute comparaison. Une estimation
« non facturable » avec un prix non nul ou invalide est refusée comme incohérente.

`evaluate_hypothetical` évalue les règles 1 à 4 pour la simulation, mais
n'autorise jamais une dépense réelle.

### Garde-fous HTTP

| Limite | Valeur par défaut | Borne CLI |
|---|---|---|
| Activation | désactivée | `--enable-http` obligatoire |
| Hôtes | liste blanche vide | `--allow-host` |
| Schéma / port | HTTPS / 443 | — |
| Sources | 3 | 5 |
| Délai par requête (connexion → fin du corps) | 5 s | 15 s |
| Échéance globale (DNS, connexion, TLS, en-têtes, corps, pauses) | 30 s | — |
| Taille de réponse | 256 Ko | 1 Mo |
| Pages | 3 | 5 |
| Éléments par source | 200 | — |
| Tentatives | 2 : erreur réseau sans statut reçu, ou 5xx avec corps complet | — |
| Redirections | 1, même hôte uniquement, revalidée | — |

Sont refusés : les noms locaux (`localhost`, `*.local`, `*.internal`…), les IP
littérales, toute résolution DNS vers une adresse non publique (loopback,
privée, lien local, CGNAT, multicast, adresses mappées IPv4), les identifiants
dans l'URL et les ports non autorisés. La connexion est épinglée sur l'adresse
validée. Aucun en-tête d'authentification n'est envoyé.

**HTTP 402** : arrêt de la source, observation enregistrée (en-têtes masqués),
sans réessai ni paiement, y compris quand le corps de la 402 est coupé, trop long
ou hors délai (`body_error` renseigné). Plus généralement, dès qu'un statut est
reçu, aucune nouvelle tentative n'est faite si le corps est incomplet.

**Budget de temps, ce qui est garanti et ce qui ne l'est pas :**
- le corps est lu par blocs, avec un délai de socket recalculé avant chaque
  lecture, et un minuteur ferme la connexion à l'échéance (connexion, TLS,
  en-têtes, corps). Le minuteur agit sur le socket **actif** : `wrap_socket`
  détache le socket brut, donc la connexion enregistre le socket TLS avant de
  lancer la négociation, sous verrou, pour qu'elle soit interruptible ;
- un corps plus court que le `Content-Length` annoncé est un corps **tronqué**
  (`read1()` peut renvoyer une fin vide sans erreur) : il n'est jamais classé
  comme complet, et aucune nouvelle tentative n'est faite ;
- les pauses entre tentatives ne dépassent jamais l'échéance : une pause trop
  longue arrête les tentatives ;
- la résolution DNS (`getaddrinfo`) ne peut pas être interrompue en Python :
  l'atelier cesse **d'attendre** à l'échéance, mais le fil de résolution (démon)
  peut continuer en arrière-plan jusqu'au délai du système ;
- le retour peut dépasser l'échéance d'une **marge de nettoyage** (fermeture de
  socket, ordonnancement des fils), courte en pratique mais non garantie.
L'échéance est donc un budget d'exécution, pas une limite absolue.

### Secrets

`redact.py` masque les clés sensibles (`api_key`, `authorization`, `secret`,
`token`, `private`, `mnemonic`, `signature`, `payment-signature`…) et les motifs
(`0x` + 64 hex, `sk-…`, `Bearer …`, phrase mnémonique probable) dans les
données brutes, les observations 402, les exports et les journaux (filtre posé
sur les handlers). Les URL présentes dans ces textes sont aussi nettoyées :
identifiants (`user:mdp@`) et paramètres sensibles de requête ou de fragment
(`api_key`, `token`, `key`, `sig`, `code`, `session`…). Le masquage est
volontairement large.

## Limites connues

- Le transport HTTP réel (`HttpsTransport`) est testé avec des doubles de
  connexion contrôlés (corps coupé, lecture lente, minuteur, taille), mais
  **jamais contre un vrai serveur** : le réseau est bloqué pendant les tests. La
  classe `_PinnedHTTPSConnection` est testée sur une paire de sockets locale
  (vraie négociation TLS bloquée puis interrompue), mais sa connexion TCP réelle
  (`socket.create_connection`) n'est jamais exécutée. Elle se connecte en
  direct, sans proxy HTTP(S).
- Sans `Content-Length` (lecture jusqu'à la fermeture), une troncature côté
  serveur ne peut pas être distinguée d'une fin normale.
- Les détections de secrets sont heuristiques : un secret au format inattendu
  sous une clé neutre peut passer.
- Le schéma de découverte HTTP (`discover --enable-http`) reste propre à l'atelier. Bazaar n'est couvert qu'en hors ligne, pour les formats ci-dessus : aucune revendication universelle Bazaar ou MCP, aucun client HTTP Bazaar.
- docs.x402.org n'a pas pu être consultée (connexion refusée par le proxy) ; les sources sont celles du dépôt officiel, au commit noté dans le manifeste.
- Les fixtures sont fictives : aucune conclusion commerciale ou de rentabilité
  ne peut en être tirée.
