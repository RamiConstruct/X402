# Parcours du laboratoire de trading (LAB-001)

> SIMULATION SYNTHÉTIQUE — PAS UNE PREUVE DE RENTABILITÉ.
> Ce parcours explique des mécanismes. Ce n'est pas un conseil d'achat ou de
> vente, ni une recommandation adaptée à ta situation.

Chaque notion est reliée à un scénario de `fixtures/lab/`. Pour le rejouer :

```bash
python3 -m labtrading list
python3 -m labtrading run --scenario net_positif_complet
python3 -m labtrading run --all --out sorties/labo   # laboratoire.json + laboratoire.md
```

## 1. Bid, ask et spread

- **Ask** : le prix le plus bas auquel quelqu'un accepte de vendre.
- **Bid** : le prix le plus haut auquel quelqu'un accepte d'acheter.
- **Spread** : l'écart entre les deux sur une même plateforme. Entre deux
  plateformes, « l'écart d'arbitrage » est le bid de l'une moins l'ask de l'autre.

**Exercice.** Dans `net_positif_complet`, relève le meilleur ask de A et le
meilleur bid de B dans la section `visible`. Retrouve l'écart brut par unité
affiché (1,00).

## 2. Liquidité et profondeur

Un prix n'est valable que pour la quantité affichée à ce niveau. Pour acheter
plus, il faut monter dans le carnet, à des prix moins bons : c'est le
glissement. Le laboratoire calcule un prix moyen par profondeur et n'ajoute
aucun glissement supplémentaire, puisque le carnet le contient déjà.

**Exercice.** Dans `profondeur_insuffisante`, le bid de B à 101,00 ne porte
que 0,0005 unité. Explique pourquoi l'ordre est refusé alors que l'écart par
unité paraît grand.

## 3. Frais maker / taker

- **Taker** : on prend une offre déjà présente (exécution immédiate). Les deux
  jambes d'un arbitrage sont en général taker.
- **Maker** : on dépose une offre qui attend dans le carnet.

Les frais du laboratoire sont des **hypothèses de scénario**, pas des tarifs
vérifiés d'une plateforme.

**Exercice.** Compare `net_positif_complet` (frais de 0,1 %) et
`brut_positif_net_negatif` (frais de 0,6 %). Le même écart brut (0,50) devient
un net négatif (-0,16). Calcule à partir de quel taux de frais le net passe
sous zéro.

## 4. Devises de cotation

USD, USDC et USDT sont trois devises distinctes : leur taux de change n'est pas
toujours exactement 1. Le laboratoire refuse de comparer deux carnets cotés
dans des devises différentes.

**Exercice.** Lis le motif de refus de `devise_incompatible`.

## 5. Fraîcheur, latence et données futures (look-ahead)

Trois horloges sont séparées : l'heure de marché, l'heure de réception et
l'heure de décision. À la décision, on ne voit que ce qui est déjà reçu. Les
ordres arrivent après une latence et trouvent le carnet réel de ce moment-là.

- `carnet_perime` : l'écart affiché date de 5 s, il n'est plus fiable.
- `donnee_future` : une hausse arrive APRÈS la décision. L'utiliser serait
  du « look-ahead », c'est-à-dire tricher avec l'avenir dans un test.
- `latence_detruit_ecart` : le plan semblait rentable, mais l'écart a disparu
  avant l'arrivée des ordres.

**Exercice.** Dans `donnee_future`, à partir de quelle heure de décision
l'écart devient-il visible ? (Les tests en montrent un exemple.)

## 6. Risque d'exécution et inventaire

Les soldes sont **prépositionnés** sur chaque plateforme : aucun transfert
instantané n'est supposé. Si une seule jambe est exécutée, il reste une
**exposition ouverte** : un actif acheté et non revendu, qui peut perdre de la
valeur. Aucun gain n'est compté tant que la paire n'est pas terminée.

**Exercice.** Dans `une_seule_jambe`, quelle quantité reste exposée ? Pourquoi
le P&L réalisé est-il vide alors que le net planifié était positif ?

## 7. Arbitrage ou signal directionnel

- **Arbitrage** : acheter et vendre presque en même temps le même actif sur deux
  plateformes. Le risque principal est l'exécution, pas la direction du marché.
- **Signal directionnel** : parier que le prix va monter ou baisser. Le risque
  principal est de se tromper de direction.

Ce laboratoire ne traite que le premier cas.

## 8. Notions pour les lots suivants (non simulées ici)

- **Drawdown** : la baisse maximale depuis un sommet du capital simulé. Une
  stratégie peut être gagnante en moyenne et pourtant subir des chutes
  insupportables.
- **Surapprentissage** : une stratégie réglée sur le passé, qui l'« apprend par
  cœur » et échoue sur des données nouvelles. Antidotes : séparation
  chronologique entraînement/validation/test, walk-forward, période finale
  jamais touchée, et registre de tous les essais, y compris les rejetés.
- **Rendement seul trompeur** : il faut aussi mesurer coûts, exposition,
  rotation, taux de remplissage et incertitude.

Ces notions seront mesurées seulement dans des lots dédiés, sur des données
autorisées, après revue.
