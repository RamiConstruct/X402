# Installer le relais vidéo TURN sur ton VPS

**Pourquoi** : la vidéo temps réel (WebRTC) a besoin d'un chemin réseau entre ton navigateur
et le GPU loué. Les machines Vast.ai sont derrière un NAT, RunPod n'accepte pas l'UDP, et les
Wi-Fi d'hôtel bloquent souvent tout. Le relais TURN sur ton VPS sert de point de passage
garanti. Il ne voit que des paquets chiffrés (WebRTC chiffre toujours la vidéo de bout en bout).

## 1. Récupérer le script sur le VPS

```bash
ssh ton_user@IP_DU_VPS
git clone https://github.com/ramiconstruct/x402.git && cd x402
git checkout claude/ai-live-studio-architecture-2td5sl
```
(Dépôt privé : GitHub te demandera un jeton d'accès. Sinon, depuis ton PC :
`scp ai_live/deploy/install_turn.sh ton_user@IP_DU_VPS:~` puis `sudo bash ~/install_turn.sh`.)

## 2. Lancer l'installation (2 minutes)

```bash
sudo bash ai_live/deploy/install_turn.sh
```
Options : `--ip 203.0.113.7` si l'IP n'est pas détectée ; `--domain turn.mondomaine.com` pour
ajouter TURN chiffré sur le port 5349 (utile sur les réseaux très filtrés ; le nom de domaine
doit pointer vers le VPS et le port 80 doit être libre pour Let's Encrypt).

Le script :
- installe coturn, génère un **secret** (`/etc/ai-live-turn.secret`) ;
- configure des **identifiants temporaires** (le secret ne quitte jamais tes serveurs) ;
- **interdit le relais vers localhost et les réseaux privés** (personne ne peut utiliser ton relais pour atteindre l'intérieur du VPS) ;
- plafonne débit et nombre de sessions ;
- ouvre le pare-feu `ufw` s'il est actif, démarre le service, vérifie qu'il écoute ;
- affiche et enregistre dans `/root/ai-live-turn.env` les deux valeurs pour la console.

## 3. Ouvrir le pare-feu de l'hébergeur

Si ton hébergeur a un pare-feu dans son tableau de bord (Hetzner Cloud Firewall, OVH, AWS
Security Groups, Oracle…), ouvre : **3478 TCP + UDP** et **49160-49800 UDP** (+ **5349 TCP** avec `--domain`).

### Oracle Cloud (OCI) — deux pare-feu à ouvrir

1. **Dans la machine** : les images Ubuntu d'Oracle contiennent des règles `iptables` qui rejettent
   tout sauf SSH. Le script les détecte, ajoute les ouvertures et les rend permanentes
   (`netfilter-persistent`). Rien à faire.
2. **Dans la console Oracle** : Menu → *Networking* → *Virtual Cloud Networks* → ton VCN →
   *Security Lists* → *Default Security List* → **Add Ingress Rules** :

   | Source CIDR | Protocole | Port de destination |
   |---|---|---|
   | 0.0.0.0/0 | UDP | 3478 |
   | 0.0.0.0/0 | TCP | 3478 |
   | 0.0.0.0/0 | UDP | 49160-49800 |
   | 0.0.0.0/0 | TCP | 5349 (seulement avec `--domain`) |

   (Si ton instance utilise un *Network Security Group*, ajoute les mêmes règles dans ce NSG.)

Les instances Oracle ont une IP privée derrière une IP publique (NAT 1:1) : le script le détecte
et configure `external-ip=IP_PUBLIQUE/IP_PRIVÉE` automatiquement. Les instances Ampere (ARM)
fonctionnent : coturn est disponible en arm64.

## 4. Vérifier depuis ton PC

```bash
cd ai_live
python -m live.check_turn --urls '<LIVE_TURN_URLS>' --secret '<LIVE_TURN_SECRET>'
```
Résultat attendu :
```
✓ turn:IP:3478?transport=udp — adresse relayée IP:49xxx
✓ turn:IP:3478?transport=tcp — adresse relayée IP:49xxx
```
`401 Unauthorized` = secret incorrect ; délai dépassé = pare-feu (étape 3) ou service arrêté
(`sudo systemctl status coturn`).

## 5. Donner les valeurs à la console AI LIVE

```bash
# Linux/Mac
export LIVE_TURN_SECRET='…'
export LIVE_TURN_URLS='["turn:IP:3478?transport=udp","turn:IP:3478?transport=tcp"]'
# Windows PowerShell
$env:LIVE_TURN_SECRET='…'
$env:LIVE_TURN_URLS='["turn:IP:3478?transport=udp","turn:IP:3478?transport=tcp"]'
python -m live
```
La console génère des identifiants valables quelques heures pour le navigateur et la page OBS,
et pour la durée de location quand elle loue un GPU.

## Coût et charge

coturn consomme très peu de CPU. Le facteur limitant est la **bande passante** : environ
3 Mb/s entrant + 3 Mb/s sortant par live relayé, en double (caméra → GPU, GPU → OBS).
Un VPS avec 1 Gb/s de port et quelques To de trafic mensuel suffit largement pour toi seul.

## Testé

Le script a été exécuté sur Ubuntu 24.04 (conteneur) : installation, configuration, démarrage,
puis allocation relayée réussie en UDP et en TCP avec des identifiants temporaires, et refus
(401) avec un mauvais secret. Non testé : un VPS réel derrière le pare-feu d'un hébergeur, et l'option `--domain`.
