# Parcours x402 futur — simulation hors ligne (lot 1)

> Ce document décrit un parcours **simulé**. Aucune clé n'est générée,
> aucun portefeuille n'est créé, aucune transaction n'est construite, signée
> ni envoyée. Une simulation réussie n'est **ni** un paiement réussi, **ni**
> une preuve de rentabilité.

## État des vérifications (2026-10-29)

| Source | Résultat |
|---|---|
| https://docs.x402.org | **Non consultée** : hôte injoignable depuis l'environnement de développement (DNS bloqué par la politique réseau). |
| https://github.com/x402-foundation/x402 (README) | Consultée. Cite les en-têtes `PAYMENT-REQUIRED` (objet PaymentRequired renvoyé avec la 402), `PAYMENT-SIGNATURE` (PaymentPayload du client), `PAYMENT-RESPONSE` (réponse de règlement), les schémas `exact`, `upto`, `batch-settlement`, les champs `scheme`, `network`, `accepts`, et le paquet Python `x402`. **Ni la version du protocole ni le format des identifiants réseau ne sont indiqués.** |

Conséquence : la simulation reprend uniquement `accepts`, `scheme` et
`network`. Les autres champs (`amount_atomic`, `asset_symbol`,
`asset_decimals`, `unit`, `pay_to`) sont **propres à l'atelier**. Aucune
compatibilité avec une version de x402 n'est revendiquée. Le réseau
`testnet-fictif` et l'actif `JETONTEST` sont inventés.

## Étapes simulées

| # | Étape | Ce que fait la simulation | Arrêt si |
|---|---|---|---|
| 1 | `decouverte` | Lit un service d'une fixture fictive (provenance `fictif`). | — |
| 2 | `reponse_402` | Lit une réponse 402 scriptée ; en-têtes masqués ; **arrêt et observation**. | statut ≠ 402 (`arret`) |
| 3 | `verification_conditions` | Contrôle `accepts[0]` : schéma pris en charge (`exact` seulement), réseau dans la liste testnet simulée, montant interprétable (décimales connues), devise et unité connues. | une condition manque (`refus`) |
| 4 | `autorisation` | Décision **réelle** de `CostGuard` (toujours refusée : appels facturables bloqués) + évaluation **hypothétique** avec un budget de simulation (plafonds par appel et par session, même devise). | évaluation hypothétique refusée (`refus`) |
| 5 | `paiement_testnet` | Statut `simule_non_execute` : `cle_generee=false`, `portefeuille_cree=false`, `transaction=null`. | — |
| 6 | `resultat` | Réponse du fournisseur simulé, marquée `simule`. | — |

Chaque rapport porte `simulation: true`, `paiement_reel_effectue: false`,
`transaction: null`, `rentabilite: "non évaluée"`.

## Scénarios fournis (`fixtures/x402_scenarios_fictifs.json`)

`ok`, `prix_inconnu`, `devise_inconnue`, `reseau_non_testnet`,
`depasse_plafond`, `schema_inconnu`, `pas_de_402`.

```bash
python3 -m atelier_x402 simulate-x402 --all
python3 -m atelier_x402 simulate-x402 --scenario prix_inconnu
```

## Prérequis du futur lot « intégration testnet réelle » (séparé)

1. Consulter docs.x402.org (autoriser l'hôte dans la politique réseau) et le
   dépôt x402-foundation/x402 ; noter **la version exacte** du protocole et du
   SDK utilisés.
2. Remplacer les champs propres à l'atelier par le schéma officiel vérifié ;
   écrire des tests de contrat sur des exemples officiels.
3. Fixer la devise du budget (actuellement **non confirmée**) et les plafonds
   par appel et par session.
4. Gestion des clés hors dépôt (jamais dans le code, les journaux ou les
   rapports), décidée et validée explicitement par le responsable.
5. Lever `BILLABLE_CALLS_ALLOWED` seulement dans ce lot dédié, après revue,
   et pour un réseau de test uniquement.
