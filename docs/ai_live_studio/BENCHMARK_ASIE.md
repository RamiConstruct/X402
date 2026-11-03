# Comparatif Asie : serveurs, GPU, stockage (novembre 2026)

Prix relevés le 3 novembre 2026 sur des comparateurs et pages fournisseurs : **ordres de grandeur, à vérifier sur la
page de commande** (ils varient selon la région, la taxe et changent souvent ; plusieurs hausses en 2026).

## Ce qui compte pour notre projet

- **AI Live** : la vidéo va directement du téléphone à la carte graphique (WebRTC). Le délai dépend donc surtout de
  la **distance utilisateur ↔ GPU**. Le petit serveur « console » ne voit passer aucune vidéo : il n'a pas besoin
  d'être gros, seulement fiable.
- **AI Studio** : traitements par lots ; le prix par heure de GPU et le stockage des vidéos comptent plus que la distance.
- **Singapour** est le carrefour de l'Asie du Sud-Est (bonnes liaisons vers l'Indonésie, la Malaisie, la Thaïlande,
  le Vietnam, les Philippines) ; **Tokyo** pour l'Asie du Nord-Est. Notre serveur Oracle actuel est à **Sydney** (plus loin).

## 1. Serveurs (VPS) — pour la console AI Live, AI Studio, la sentinelle

| Fournisseur | Villes en Asie | Prix indicatif | Points forts | Limites |
|---|---|---|---|---|
| **Vultr** | Singapour, Tokyo, Osaka, Séoul, Mumbai, Delhi, Bangalore, Sydney… | dès ~6 $/mois ; 2 vCPU / 4 Go ≈ 20 $ à Singapour | Le plus de villes en Asie, 1 To de trafic dès l'entrée de gamme, GPU disponibles | Pas de services gérés aussi riches que DigitalOcean |
| **Akamai (Linode)** | Singapour, Jakarta, Tokyo, Osaka, Mumbai, Chennai, Sydney | dès ~5 $/mois | **Jakarta** (rare), GPU RTX 4000 Ada à Singapour/Osaka, réseau Akamai | — |
| **DigitalOcean** | Singapour, Bangalore, Sydney | dès ~6 $/mois ; 4 Go ≈ 28 $ à Singapour | Le plus simple, bases de données gérées, plateforme d'applications | Plus cher, peu de villes en Asie |
| **Hetzner** | Singapour | dès ~4–8 € (hausses 2026) | Le moins cher en puissance brute | À Singapour : trafic inclus faible (0,5–5 To, puis ~8,5 $/To), certaines gammes indisponibles |
| **Tencent Lighthouse** | Singapour, Jakarta, Tokyo, Séoul | dès ~5 $/mois (forfaits) | Prix très bas, présent en Indonésie | Interface et support moins pratiques depuis l'Europe |
| **Alibaba Simple Application Server** | Singapour, Bangkok, Jakarta, Manille, Hong Kong | ~8–9 $/mois pour 2 vCPU / 4 Go (revendeur) | **Bangkok et Manille** | Abonnement seulement, prix officiel à vérifier |
| **Oracle (actuel)** | Sydney (région d'origine) | gratuit (1 Go) ; Ampere A1 2 cœurs / 12 Go gratuit si place | Gratuit | Région d'origine non modifiable pour l'offre gratuite ; capacité A1 rare |

**Recommandation :** un **Vultr Singapour 2 vCPU / 4 Go (~20 $/mois)** pour la console et AI Studio : fiable, proche,
paiement à l'heure, GPU chez le même fournisseur. Variante moins chère : **Akamai Singapour**. On garde Oracle
(gratuit) comme machine de secours.

## 2. Cartes graphiques (GPU)

### Pour AI Live (temps réel, 512×512) : une RTX 4090 / 5090 suffit

| Option | Où | Prix indicatif | Pour quoi |
|---|---|---|---|
| **Vast.ai** (place de marché) | partout, dont des hôtes en Asie | RTX 4090 dès ~0,15–0,40 $/h ; H100 ~2,40 $/h | Le moins cher ; fiabilité variable selon l'hôte → bien pour les essais |
| **RunPod** | surtout US/Europe | RTX 4090 ~0,89 $/h ; H100 PCIe ~2,89 $/h | Simple, fiable ; souvent loin de l'Asie |
| **Akamai RTX 4000 Ada** | Singapour, Osaka | ~0,52 $/h | **Stable et proche de l'Asie du Sud-Est** ; moins puissante qu'une 4090 (mode Rapide/Équilibré) |
| **Daydream** (actuel) | réseau mondial Livepeer | à la minute (à mesurer) | Rien à gérer ; coût réel à mesurer avant de fixer nos prix |

### Pour AI Studio (génération vidéo, gros modèles) : H100

| Option | Où | Prix indicatif | Remarque |
|---|---|---|---|
| **FPT AI Factory** | Vietnam (Asie du Sud-Est) | H100 ~2,99 $/h (VM ou conteneur) | Le meilleur rapport prix/proximité en Asie du Sud-Est |
| Néo-clouds mondiaux (Vast, RunPod, Lambda, Spheron…) | US/Europe surtout | H100 ~2,40–2,90 $/h | Moins chers que les géants, loin de l'Asie |
| **AWS / Azure / Google** à Singapour ou Tokyo | Asie | H100 **~12–14 $/h** | À éviter : 4 à 5 fois plus cher |
| Japon (Sakura Internet, GMO) | Tokyo | non relevé | À étudier si clientèle japonaise |

**Recommandation :** GPU **loués à l'heure, seulement pendant l'usage** (déjà codé : libération automatique).
AI Live → Vast.ai pour les essais, puis **Akamai Singapour** ou un hôte 4090 fiable en Asie pour la production.
AI Studio → **FPT (Vietnam)** pour les H100.

## 3. Stockage (vidéos des clients, essais, résultats)

| Option | Où | Prix indicatif | Sortie (téléchargements) | Remarque |
|---|---|---|---|---|
| **Cloudflare R2** | mondial | ~15 $/To/mois | **gratuite** | Déjà notre fournisseur ; idéal pour servir les vidéos aux clients |
| **Wasabi** | Tokyo, Osaka, Singapour, Sydney | ~8 $/To/mois | gratuite (usage raisonnable) | Conservation minimale 90 jours ; bien pour les archives |
| **Vultr Object Storage** | plusieurs villes d'Asie | ~5 $/To | **payante** (~10 $/To) | Bon marché si peu de téléchargements |
| Backblaze B2 | US/Europe | ~7 $/To | payante | Pas de région en Asie |

**Recommandation :** **Cloudflare R2** pour tout ce que les clients regardent ou téléchargent (pas de frais de sortie,
même compte que le site) ; **Wasabi Singapour** si on accumule beaucoup d'archives.

## 4. Relais vidéo (TURN) et réseau

Utiliser le **TURN de Cloudflare** (réseau mondial, payé à l'usage, presque gratuit au début) plutôt que notre relais
sur Oracle : il est proche de chaque utilisateur, où qu'il soit. Le code le gère déjà, il ne manque que la clé.

## 5. Plan pour grandir vite (dans le budget de 1 000 $)

| Étape | Quoi | Coût mensuel estimé |
|---|---|---|
| **Maintenant** | Vultr Singapour 4 Go (console + AI Studio) ; TURN Cloudflare ; R2 ; GPU à l'heure seulement pendant les lives | ~25–40 $ + GPU à l'usage |
| **Premiers clients** | 1 GPU « chaud » en Asie aux heures de pointe (Akamai RTX 4000 Ada ~0,52 $/h) ; mise à l'échelle automatique (GpuManager) | + ~100–200 $ selon les heures |
| **Croissance** | Régions Singapour + Tokyo (+ Mumbai) ; H100 FPT pour AI Studio ; contrats réservés quand l'usage est régulier | selon les ventes (les GPU se paient avec les crédits clients) |

Règle : **chaque heure de GPU est payée par des crédits clients** (marge ≥ 60 %) avant de passer à l'étape suivante.

## Sources

- [Cybernews — Best Singapore VPS (oct. 2026)](https://cybernews.com/vps/best-singapore-vps-services/)
- [VPSLocate — Best VPS Asia 2026](https://vpslocate.com/guides/best-vps-asia-2026.html)
- [1vps — Vultr vs DigitalOcean 2026](https://1vps.com/vultr-vs-digitalocean/)
- [Hetzner — Cloud Singapore](https://www.hetzner.com/cloud-singapore/) ; [Northflank — hausses Hetzner](https://northflank.com/blog/hetzner-cloud-server-price-increases) ; [heise — hausses Hetzner](https://heise.de/-11333037)
- [Tencent Cloud Lighthouse — tarifs](https://intl.cloud.tencent.com/document/product/1103/47794) ; [Alibaba Simple Application Server — tarifs](https://alibabacloud.com/help/en/simple-application-server/product-overview/pricing-of-resource-plans) ; [Zeabur — tableau de prix](https://zeabur.com/pricing/server-price-update)
- [GPUPerHour (nov. 2026)](https://gpuperhour.com/) ; [gpueconomy (nov. 2026)](https://gpueconomy.com/) ; [RunPod — Cloud GPUs](https://www.runpod.io/product/cloud-gpus) ; [DEV — prix GPU oct. 2026](https://dev.to/lanternworks/gpu-rental-prices-compared-h100-a100-rtx-4090-and-more-oct-2026-eha)
- [FPT AI Factory — prix H100](https://factory.fpt.ai/ai-insights/h100-cost) ; [Spheron — GPU en Asie-Pacifique](https://www.spheron.network/blog/gpu-cloud-providers-asia-pacific-2026/)
- [Akamai — GPU RTX 4000 Ada](https://www.akamai.com/blog/developers/2024/dec/new-gpus-nvidia-rtx-4000-ada-generation) ; [computeprices — Akamai RTX 4000 Ada](https://computeprices.com/providers/akamai-cloud/gpus/rtx4000ada)
- [getdeploying — Cloudflare vs Wasabi](https://getdeploying.com/cloudflare-vs-wasabi) ; [Mixpeek — 21 fournisseurs S3](https://mixpeek.com/blog/object-storage-comparison-2026) ; [devshot — prix stockage 1 To](https://devshot.co/blog/object-storage-pricing-compared)
