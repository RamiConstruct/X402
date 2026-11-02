#!/usr/bin/env bash
# Installe et configure le relais vidéo TURN (coturn) pour AI LIVE sur un VPS Ubuntu/Debian.
#
#   (sur le VPS, après avoir récupéré le dépôt avec git clone, ou copié ce fichier avec scp)
#   sudo bash ai_live/deploy/install_turn.sh  # IP publique détectée automatiquement
#   sudo bash install_turn.sh --ip 203.0.113.7 --domain turn.mondomaine.com   # + TLS (port 5349)
#
# Sécurité :
#  * identifiants TEMPORAIRES (use-auth-secret) : la console fabrique des mots de passe valables
#    quelques heures à partir d'un secret ; le secret ne quitte jamais tes serveurs ;
#  * relais interdit vers les réseaux privés et localhost (empêche d'atteindre l'intérieur du VPS) ;
#  * débit et quotas plafonnés.
set -euo pipefail

PUBLIC_IP=""
DOMAIN=""
PORT=3478
TLS_PORT=5349
MIN_PORT=49160
MAX_PORT=49800
MAX_BPS=$((3 * 1024 * 1024))   # ~24 Mb/s par session TURN : large pour un flux 512–1080p
SECRET_FILE=/etc/ai-live-turn.secret

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ip) PUBLIC_IP="$2"; shift 2 ;;
    --domain) DOMAIN="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    *) echo "option inconnue : $1"; exit 2 ;;
  esac
done

[[ $EUID -eq 0 ]] || { echo "Lance ce script avec sudo."; exit 1; }
command -v apt-get >/dev/null || { echo "Ce script vise Ubuntu/Debian (apt-get introuvable)."; exit 1; }

echo "==> Installation de coturn"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q coturn curl openssl iproute2

if [[ -z "$PUBLIC_IP" ]]; then
  PUBLIC_IP="$(curl -fsS4 --max-time 5 https://api.ipify.org || curl -fsS4 --max-time 5 https://ifconfig.me || true)"
fi
[[ "$PUBLIC_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "IP publique introuvable : relance avec --ip <IP>"; exit 1; }
PRIVATE_IP="$( (ip -4 route get 1.1.1.1 2>/dev/null || true) | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')"

if [[ ! -s "$SECRET_FILE" ]]; then
  umask 077
  openssl rand -hex 32 > "$SECRET_FILE"
fi
SECRET="$(cat "$SECRET_FILE")"

EXTERNAL="$PUBLIC_IP"
if [[ -n "$PRIVATE_IP" && "$PRIVATE_IP" != "$PUBLIC_IP" ]]; then
  EXTERNAL="$PUBLIC_IP/$PRIVATE_IP"   # VPS derrière un NAT (AWS, GCP, Oracle…)
fi

TLS_BLOCK="no-tls
no-dtls"
if [[ -n "$DOMAIN" ]]; then
  CERT="/etc/letsencrypt/live/$DOMAIN/fullchain.pem"
  KEY="/etc/letsencrypt/live/$DOMAIN/privkey.pem"
  if [[ ! -f "$CERT" ]]; then
    echo "==> Certificat TLS pour $DOMAIN (Let's Encrypt, le port 80 doit être libre)"
    apt-get install -y -q certbot
    certbot certonly --standalone --non-interactive --agree-tos --register-unsafely-without-email -d "$DOMAIN"
  fi
  install -d -m 750 -o turnserver -g turnserver /etc/coturn/certs
  install -m 640 -o turnserver -g turnserver "$CERT" /etc/coturn/certs/fullchain.pem
  install -m 640 -o turnserver -g turnserver "$KEY" /etc/coturn/certs/privkey.pem
  TLS_BLOCK="tls-listening-port=$TLS_PORT
cert=/etc/coturn/certs/fullchain.pem
pkey=/etc/coturn/certs/privkey.pem
no-tlsv1
no-tlsv1_1
no-dtls"
fi

[[ -f /etc/turnserver.conf && ! -f /etc/turnserver.conf.orig ]] && cp /etc/turnserver.conf /etc/turnserver.conf.orig

echo "==> Configuration /etc/turnserver.conf"
cat > /etc/turnserver.conf <<CONF
# AI LIVE — relais TURN (généré par install_turn.sh)
listening-port=$PORT
external-ip=$EXTERNAL
min-port=$MIN_PORT
max-port=$MAX_PORT
realm=ai-live
fingerprint
use-auth-secret
static-auth-secret=$SECRET
stale-nonce=600
$TLS_BLOCK

# Limites anti-abus
max-bps=$MAX_BPS
user-quota=12
total-quota=200

# Interdiction de relayer vers l'intérieur (localhost, réseaux privés, métadonnées cloud)
no-multicast-peers
no-cli
denied-peer-ip=0.0.0.0-0.255.255.255
denied-peer-ip=10.0.0.0-10.255.255.255
denied-peer-ip=100.64.0.0-100.127.255.255
denied-peer-ip=127.0.0.0-127.255.255.255
denied-peer-ip=169.254.0.0-169.254.255.255
denied-peer-ip=172.16.0.0-172.31.255.255
denied-peer-ip=192.168.0.0-192.168.255.255
denied-peer-ip=::1
denied-peer-ip=fc00::-fdff:ffff:ffff:ffff:ffff:ffff:ffff:ffff

log-file=syslog
simple-log
CONF
chmod 640 /etc/turnserver.conf
chgrp turnserver /etc/turnserver.conf 2>/dev/null || true

# Anciens paquets Debian/Ubuntu : le service doit être activé explicitement
if [[ -f /etc/default/coturn ]]; then
  sed -i 's/^#\?TURNSERVER_ENABLED=.*/TURNSERVER_ENABLED=1/' /etc/default/coturn
fi

if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  echo "==> Pare-feu ufw"
  ufw allow "$PORT/tcp" >/dev/null
  ufw allow "$PORT/udp" >/dev/null
  ufw allow "$MIN_PORT:$MAX_PORT/udp" >/dev/null
  [[ -n "$DOMAIN" ]] && ufw allow "$TLS_PORT/tcp" >/dev/null
elif command -v iptables >/dev/null && iptables -S INPUT 2>/dev/null | grep -qE -- "-j (REJECT|DROP)"; then
  # Images Ubuntu d'Oracle Cloud : règles iptables qui rejettent tout sauf SSH, même sans ufw.
  echo "==> Pare-feu iptables (images Oracle Cloud et similaires)"
  open_port() {  # $1 = proto, $2 = port ou plage a:b
    iptables -C INPUT -p "$1" -m state --state NEW --dport "$2" -j ACCEPT 2>/dev/null \
      || iptables -I INPUT 1 -p "$1" -m state --state NEW --dport "$2" -j ACCEPT
  }
  open_port tcp "$PORT"; open_port udp "$PORT"; open_port udp "$MIN_PORT:$MAX_PORT"
  [[ -n "$DOMAIN" ]] && open_port tcp "$TLS_PORT"
  if command -v netfilter-persistent >/dev/null; then
    netfilter-persistent save >/dev/null 2>&1 && echo "    règles enregistrées (netfilter-persistent)"
  else
    apt-get install -y -q iptables-persistent >/dev/null 2>&1 && netfilter-persistent save >/dev/null 2>&1 \
      && echo "    règles enregistrées (iptables-persistent)" || echo "    ⚠ règles actives mais non persistantes après redémarrage"
  fi
fi

echo "==> Démarrage du service"
if [[ -d /run/systemd/system ]]; then
  systemctl enable coturn >/dev/null 2>&1 || true
  systemctl restart coturn
  sleep 2
  systemctl is-active --quiet coturn || { journalctl -u coturn -n 30 --no-pager; echo "coturn ne démarre pas"; exit 1; }
else  # conteneur sans systemd
  pkill -x turnserver 2>/dev/null || true
  turnserver -c /etc/turnserver.conf -o
  sleep 2
fi

echo "==> Vérification de l'écoute"
if ss -lntu 2>/dev/null | grep -q ":$PORT "; then
  echo "    OK : coturn écoute sur le port $PORT (TCP/UDP)."
else
  echo "    ⚠ aucun processus n'écoute sur $PORT — voir : journalctl -u coturn -n 50"; exit 1
fi

URLS="[\"turn:$PUBLIC_IP:$PORT?transport=udp\",\"turn:$PUBLIC_IP:$PORT?transport=tcp\""
[[ -n "$DOMAIN" ]] && URLS="$URLS,\"turns:$DOMAIN:$TLS_PORT?transport=tcp\""
URLS="$URLS]"

umask 077
cat > /root/ai-live-turn.env <<ENV
LIVE_TURN_SECRET=$SECRET
LIVE_TURN_URLS='$URLS'
ENV

cat <<DONE

========================================================================
 Relais TURN installé.

 À ajouter dans l'environnement de la console AI LIVE (copie : /root/ai-live-turn.env) :

   LIVE_TURN_SECRET=$SECRET
   LIVE_TURN_URLS='$URLS'

 Garde LIVE_TURN_SECRET secret (comme un mot de passe).

 ⚠ Oracle Cloud : ajoute aussi des « Ingress Rules » dans la Security List du sous-réseau
   (Networking → Virtual Cloud Networks → ton VCN → Security Lists), source 0.0.0.0/0.
   Autres hébergeurs avec pare-feu dans le tableau de bord (Hetzner, OVH, AWS…), ouvre aussi : $PORT TCP+UDP, $MIN_PORT-$MAX_PORT UDP$([[ -n "$DOMAIN" ]] && echo ", $TLS_PORT TCP").

 Vérification depuis ton PC :
   python -m live.check_turn --urls '$URLS' --secret <LIVE_TURN_SECRET>
========================================================================
DONE
