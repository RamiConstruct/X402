#!/bin/bash
# Premier démarrage de la machine Ampere A1 (exécuté par cloud-init, en root).
# Rend la machine joignable immédiatement par son propre tunnel Cloudflare (ssh-a1.labotory.site)
# et applique les protections de base. __TUNNEL_TOKEN__ est remplacé au moment de la création.
set -eux
export DEBIAN_FRONTEND=noninteractive
# Mémoire de secours (même avec 12 Go : filet de sécurité)
fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo "/swapfile none swap sw 0 0" >> /etc/fstab
# Tunnel Cloudflare dédié (arm64)
curl -fsSL -o /tmp/cf.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb
dpkg -i /tmp/cf.deb
install -d -m 700 /etc/cloudflared
printf '%s' '__TUNNEL_TOKEN__' > /etc/cloudflared/token && chmod 600 /etc/cloudflared/token
cat > /etc/systemd/system/cloudflared.service <<'U'
[Unit]
Description=Cloudflare Tunnel client
After=network-online.target
Wants=network-online.target
[Service]
ExecStart=/usr/bin/cloudflared --no-autoupdate --protocol http2 --metrics 127.0.0.1:20241 tunnel run --token-file /etc/cloudflared/token
Restart=always
RestartSec=5s
OOMScoreAdjust=-800
[Install]
WantedBy=multi-user.target
U
systemctl daemon-reload && systemctl enable --now cloudflared
# Outils de base pour la suite de l'installation (AI Live, AI Studio, TURN)
apt-get update -q && apt-get install -yq python3-venv python3-pip ffmpeg git coturn iproute2 >/dev/null
echo "labo-a1 prêt" > /etc/motd
