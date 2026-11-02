#!/usr/bin/env bash
# Installe la console AI LIVE (+ un worker de démonstration CPU) sur le VPS, derrière le tunnel Cloudflare.
#
#   sudo bash install_console_vps.sh /chemin/vers/ai_live
#
# Résultat :
#   * service ai-live-console : console sur 127.0.0.1:8780 (publiée par le tunnel sur live.labotory.site)
#   * service ai-live-worker  : moteur « démo » (effet de couleur CPU) sur 127.0.0.1:8890, vidéo via le relais TURN local
#   * /etc/ai-live/console.env : jeton d'accès de la console (affiché une fois), secrets lisibles par root uniquement
# Les deux services n'écoutent qu'en local : seul le tunnel Cloudflare les expose.
set -euo pipefail
SRC="${1:?usage : sudo bash $0 /chemin/vers/ai_live}"
[[ $EUID -eq 0 ]] || { echo "Lance avec sudo."; exit 1; }
[[ -f /etc/ai-live-turn.secret ]] || { echo "Installe d'abord le relais : install_turn.sh"; exit 1; }

echo "==> Dépendances système"
export DEBIAN_FRONTEND=noninteractive
apt-get install -y -q python3-venv python3-dev libopus0 libvpx-dev >/dev/null 2>&1 || apt-get install -y -q python3-venv >/dev/null

id ai-live >/dev/null 2>&1 || useradd --system --home /opt/ai-live --shell /usr/sbin/nologin ai-live
install -d -o ai-live -g ai-live /opt/ai-live /var/lib/ai-live
install -d -m 750 /etc/ai-live

echo "==> Code et environnement Python"
rm -rf /opt/ai-live/app && cp -r "$SRC" /opt/ai-live/app && chown -R ai-live:ai-live /opt/ai-live
[[ -x /opt/ai-live/venv/bin/python ]] || python3 -m venv /opt/ai-live/venv
/opt/ai-live/venv/bin/pip install -q --upgrade pip
/opt/ai-live/venv/bin/pip install -q "/opt/ai-live/app[worker]"

TURN_SECRET="$(cat /etc/ai-live-turn.secret)"
if [[ ! -f /etc/ai-live/console.env ]]; then
  ACCESS="$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-20)"
  WTOKEN="$(openssl rand -hex 24)"
  cat > /etc/ai-live/console.env <<ENV
LIVE_ACCESS_TOKEN=$ACCESS
LIVE_TURN_SECRET=$TURN_SECRET
LIVE_TURN_URLS=["turn:turn.labotory.site:3478?transport=udp","turn:turn.labotory.site:3478?transport=tcp"]
SELFHOST_URL=http://127.0.0.1:8890
SELFHOST_TOKEN=$WTOKEN
SELFHOST_MODEL=demo-cpu
SELFHOST_USD_PER_MIN=0
LIVE_DATA_DIR=/var/lib/ai-live
LIVE_MAX_SESSION_MIN=30
ENV
  NEW_ACCESS="$ACCESS"
fi
# shellcheck disable=SC1091
WTOKEN="$(grep ^SELFHOST_TOKEN= /etc/ai-live/console.env | cut -d= -f2-)"

# Identifiants TURN longue durée pour le worker local (le relais tourne sur la même machine).
EXP=$(( $(date +%s) + 365*24*3600 ))
TUSER="$EXP:worker"
TPASS="$(printf '%s' "$TUSER" | openssl dgst -sha1 -hmac "$TURN_SECRET" -binary | base64)"
cat > /etc/ai-live/worker.env <<ENV
WORKER_PROCESSOR=demo
WORKER_TOKEN=$WTOKEN
WORKER_ICE_SERVERS=[{"urls":["turn:127.0.0.1:3478?transport=udp"],"username":"$TUSER","credential":"$TPASS"}]
ENV
chmod 640 /etc/ai-live/*.env && chgrp ai-live /etc/ai-live /etc/ai-live/*.env

echo "==> Services systemd"
cat > /etc/systemd/system/ai-live-worker.service <<UNIT
[Unit]
Description=AI LIVE worker (démo CPU)
After=network-online.target coturn.service
[Service]
User=ai-live
EnvironmentFile=/etc/ai-live/worker.env
WorkingDirectory=/opt/ai-live/app
ExecStart=/opt/ai-live/venv/bin/python -m live.worker --host 127.0.0.1 --port 8890
Restart=always
RestartSec=3
MemoryMax=600M
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/ai-live
[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/systemd/system/ai-live-console.service <<UNIT
[Unit]
Description=AI LIVE console
After=network-online.target ai-live-worker.service
[Service]
User=ai-live
EnvironmentFile=/etc/ai-live/console.env
WorkingDirectory=/var/lib/ai-live
ExecStart=/opt/ai-live/venv/bin/python -m live --host 127.0.0.1 --port 8780
Restart=always
RestartSec=3
MemoryMax=300M
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/ai-live
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now ai-live-worker ai-live-console >/dev/null 2>&1
systemctl restart ai-live-worker ai-live-console
sleep 4
systemctl is-active --quiet ai-live-worker && systemctl is-active --quiet ai-live-console \
  || { journalctl -u ai-live-worker -u ai-live-console -n 40 --no-pager; exit 1; }
curl -fsS http://127.0.0.1:8780/api/catalog >/dev/null && echo "OK : console et worker actifs (local)."
[[ -n "${NEW_ACCESS:-}" ]] && echo "JETON D'ACCÈS DE LA CONSOLE (à garder) : $NEW_ACCESS"
exit 0
