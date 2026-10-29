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
python3 -m atelier_x402 compare            # comparaison JSON (même capacité, devise et unité)
python3 -m atelier_x402 providers          # fournisseurs IA et leur état
python3 -m atelier_x402 simulate-x402 --all
python3 -m atelier_x402 check-cost --price 0.01 --currency USDC --unit per_request
```

Découverte HTTP (désactivée par défaut, ne pas utiliser sans décision explicite) :

```bash
python3 -m atelier_x402 discover --enable-http \
  --allow-host catalogue.exemple.org --http-source https://catalogue.exemple.org/services.json
```

Elle n'attend que le **format de l'atelier** (`{"services": [...], "next": "..."}`
ou une liste). Ce n'est pas le format d'une API de découverte x402.

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
  x402/        flow.py (simulation hors ligne)
fixtures/      services_fictifs.json · x402_scenarios_fictifs.json   (marqués "fictif": true)
tests/         unittest, réseau bloqué pendant les tests
docs/          parcours_x402.md
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

`evaluate_hypothetical` évalue les règles 1 à 4 pour la simulation, mais
n'autorise jamais une dépense réelle.

### Garde-fous HTTP

| Limite | Valeur par défaut | Borne CLI |
|---|---|---|
| Activation | désactivée | `--enable-http` obligatoire |
| Hôtes | liste blanche vide | `--allow-host` |
| Schéma / port | HTTPS / 443 | — |
| Sources | 3 | 5 |
| Délai par requête | 5 s | 15 s |
| Échéance globale | 30 s | — |
| Taille de réponse | 256 Ko | 1 Mo |
| Pages | 3 | 5 |
| Éléments par source | 200 | — |
| Tentatives | 2 (erreurs réseau et 5xx seulement) | — |
| Redirections | 1, même hôte uniquement, revalidée | — |

Sont refusés : les noms locaux (`localhost`, `*.local`, `*.internal`…), les IP
littérales, toute résolution DNS vers une adresse non publique (loopback,
privée, lien local, CGNAT, multicast, adresses mappées IPv4), les identifiants
dans l'URL et les ports non autorisés. La connexion est épinglée sur l'adresse
validée. Aucun en-tête d'authentification n'est envoyé.

**HTTP 402** : arrêt de la source, observation enregistrée (en-têtes masqués),
sans réessai ni paiement.

### Secrets

`redact.py` masque les clés sensibles (`api_key`, `authorization`, `secret`,
`token`, `private`, `mnemonic`, `signature`, `payment-signature`…) et les motifs
(`0x` + 64 hex, `sk-…`, `Bearer …`, phrase mnémonique probable) dans les
données brutes, les observations 402, les exports et les journaux (filtre posé
sur les handlers). Le masquage est volontairement large.

## Limites connues

- Le transport HTTP réel (`default_transport`) **n'est pas testé** : les tests
  utilisent un transport simulé et bloquent le réseau. Il se connecte en direct,
  sans proxy HTTP(S).
- Les détections de secrets sont heuristiques : un secret au format inattendu
  sous une clé neutre peut passer.
- Le schéma de découverte HTTP est propre à l'atelier, sans format x402 vérifié.
- docs.x402.org n'a pas pu être consultée (voir `docs/parcours_x402.md`).
- Les fixtures sont fictives : aucune conclusion commerciale ou de rentabilité
  ne peut en être tirée.
