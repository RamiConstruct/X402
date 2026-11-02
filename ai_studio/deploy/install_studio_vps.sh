#!/usr/bin/env bash
# Installe AI STUDIO sur le VPS, derrière le tunnel Cloudflare (studio.labotory.site).
#
#   sudo bash install_studio_vps.sh /chemin/vers/ai_studio
#
# * service ai-studio : 127.0.0.1:8790 uniquement (publié par le tunnel)
# * création de compte réservée : code d'invitation affiché une fois (/etc/ai-studio/studio.env)
# * aucun fournisseur payant activé (simulateur + montage local FFmpeg)
# * envois limités à 95 Mo (limite des envois via le proxy Cloudflare, offre gratuite : 100 Mo)
set -euo pipefail
SRC="${1:?usage : sudo bash $0 /chemin/vers/ai_studio}"
[[ $EUID -eq 0 ]] || { echo "Lance avec sudo."; exit 1; }
export DEBIAN_FRONTEND=noninteractive
apt-get install -y -q ffmpeg python3-venv >/dev/null

id ai-studio >/dev/null 2>&1 || useradd --system --home /opt/ai-studio --shell /usr/sbin/nologin ai-studio
install -d -o ai-studio -g ai-studio /opt/ai-studio /var/lib/ai-studio
install -d -m 750 /etc/ai-studio
rm -rf /opt/ai-studio/app && cp -r "$SRC" /opt/ai-studio/app && chown -R ai-studio:ai-studio /opt/ai-studio
[[ -x /opt/ai-studio/venv/bin/python ]] || python3 -m venv /opt/ai-studio/venv
/opt/ai-studio/venv/bin/pip install -q --upgrade pip
/opt/ai-studio/venv/bin/pip install -q /opt/ai-studio/app

if [[ ! -f /etc/ai-studio/studio.env ]]; then
  INVITE="$(openssl rand -base64 15 | tr -d '/+=' | cut -c1-16)"
  cat > /etc/ai-studio/studio.env <<ENV
STUDIO_DATA_DIR=/var/lib/ai-studio
STUDIO_ENGINES_DIR=/opt/ai-studio/app/engines
STUDIO_SECRET_KEY=$(openssl rand -hex 32)
STUDIO_DEV_MODE=true
STUDIO_INVITE_CODE=$INVITE
STUDIO_SIGNUP_CREDITS=500
STUDIO_MAX_UPLOAD_MB=95
STUDIO_MAX_DURATION_S=60
STUDIO_PUBLIC_BASE_URL=https://studio.labotory.site
STUDIO_ALLOW_PAID_PROVIDERS=false
ENV
  NEW_INVITE="$INVITE"
fi
chmod 640 /etc/ai-studio/studio.env && chgrp ai-studio /etc/ai-studio /etc/ai-studio/studio.env

cat > /etc/systemd/system/ai-studio.service <<UNIT
[Unit]
Description=AI STUDIO
After=network-online.target
[Service]
User=ai-studio
EnvironmentFile=/etc/ai-studio/studio.env
WorkingDirectory=/var/lib/ai-studio
ExecStart=/opt/ai-studio/venv/bin/python -m studio serve --host 127.0.0.1 --port 8790
Restart=always
RestartSec=3
MemoryMax=350M
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/ai-studio
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now ai-studio >/dev/null 2>&1
systemctl restart ai-studio
sleep 4
systemctl is-active --quiet ai-studio || { journalctl -u ai-studio -n 40 --no-pager; exit 1; }
curl -fsS http://127.0.0.1:8790/api/health && echo
[[ -n "${NEW_INVITE:-}" ]] && echo "CODE D'INVITATION (à garder) : $NEW_INVITE"
exit 0
