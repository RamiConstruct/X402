# Activer le paiement Stripe (AI Studio)

Le code est prêt et déployé ; il reste inactif tant que les deux clés ne sont pas installées.

1. Créer le compte Stripe (au nom de l'éditeur) et compléter l'activation (identité, compte bancaire).
2. Développeurs → Clés API : copier la **clé secrète** (`sk_live_…`, ou `sk_test_…` pour essayer).
3. Développeurs → Webhooks → Ajouter un point de terminaison :
   - URL : `https://studio.labotory.site/api/billing/webhook`
   - Événements : `checkout.session.completed`, `checkout.session.async_payment_succeeded`
   - Copier le **secret de signature** (`whsec_…`).
4. Sur le serveur, dans `/etc/ai-studio/studio.env` (lisible par root seulement) :
   ```
   STRIPE_SECRET_KEY=sk_…
   STRIPE_WEBHOOK_SECRET=whsec_…
   STUDIO_PUBLIC_BASE_URL=https://studio.labotory.site
   ```
   puis `sudo systemctl restart ai-studio`.
5. Tester avec une carte de test Stripe (mode test) : le solde augmente une seule fois par paiement.

Packs proposés (1 crédit = 0,01 USD) : 500 crédits = 5 $, 2 000 = 20 $, 5 000 = 50 $ — modifiables dans
`ai_studio/studio/billing.py` (`PACKS`). Aucune donnée de carte ne passe par nos serveurs.
