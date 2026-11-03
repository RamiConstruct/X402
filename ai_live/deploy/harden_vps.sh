#!/usr/bin/env bash
# Durcit le petit VPS (1 Go) contre les blocages : mémoire de secours, tunnel robuste, gardien,
# redémarrage automatique en cas de gel complet. Idempotent : peut être relancé sans risque.
set -euo pipefail

# 1) Mémoire de secours (swap) 2 Go
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q "^/swapfile" /etc/fstab || echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi
echo "vm.swappiness=20" > /etc/sysctl.d/90-labo-swap.conf && sysctl -q -p /etc/sysctl.d/90-labo-swap.conf

# 2) Tunnel Cloudflare : TCP (http2) au lieu de QUIC, relance systématique, protégé de l'OOM, sonde /ready
mkdir -p /etc/systemd/system/cloudflared.service.d
cat > /etc/systemd/system/cloudflared.service.d/labo.conf <<'U'
[Service]
ExecStart=
ExecStart=/usr/bin/cloudflared --no-autoupdate --protocol http2 --metrics 127.0.0.1:20241 tunnel run --token-file /etc/cloudflared/token
Restart=always
RestartSec=5s
OOMScoreAdjust=-800
U
mkdir -p /etc/systemd/system/ssh.service.d
printf '[Service]\nOOMScoreAdjust=-800\n' > /etc/systemd/system/ssh.service.d/labo.conf

# 3) Services de l'application : relance systématique et mémoire bornée (le swap absorbe les pics)
for s in ai-live-console ai-live-worker ai-studio; do
  mkdir -p /etc/systemd/system/$s.service.d
  printf '[Service]\nRestart=always\nRestartSec=5s\nMemoryHigh=350M\nMemoryMax=600M\n' > /etc/systemd/system/$s.service.d/labo.conf
done

# 4) Gardien toutes les 2 minutes
cat > /usr/local/bin/labo-watchdog.sh <<'W'
#!/usr/bin/env bash
check() { curl -s -o /dev/null -m 8 -w "%{http_code}" "$1"; }
log() { logger -t labo-watchdog "$*"; }
[ "$(check http://127.0.0.1:20241/ready)" = "200" ] || { log "tunnel injoignable → redémarrage de cloudflared"; systemctl restart cloudflared; }
[ "$(check http://127.0.0.1:8780/api/catalog)" = "200" ] || { log "AI Live ne répond pas → redémarrage"; systemctl restart ai-live-console; }
c=$(check http://127.0.0.1:8790/); [ "$c" = "000" ] || [ "${c:0:1}" = "5" ] && { log "AI Studio ne répond pas ($c) → redémarrage"; systemctl restart ai-studio; }
exit 0
W
chmod 755 /usr/local/bin/labo-watchdog.sh
cat > /etc/systemd/system/labo-watchdog.service <<'U'
[Unit]
Description=Gardien du laboratoire (tunnel, AI Live, AI Studio)
[Service]
Type=oneshot
ExecStart=/usr/local/bin/labo-watchdog.sh
U
cat > /etc/systemd/system/labo-watchdog.timer <<'U'
[Unit]
Description=Gardien du laboratoire toutes les 2 minutes
[Timer]
OnBootSec=3min
OnUnitActiveSec=2min
[Install]
WantedBy=timers.target
U

# 5) Gel complet du système → redémarrage automatique (chien de garde logiciel du noyau)
echo softdog > /etc/modules-load.d/softdog.conf
modprobe softdog || true
mkdir -p /etc/systemd/system.conf.d
printf '[Manager]\nRuntimeWatchdogSec=60s\nRebootWatchdogSec=5min\n' > /etc/systemd/system.conf.d/labo-watchdog.conf

# 6) Service inutile sur une machine virtuelle
systemctl disable --now fwupd.service fwupd-refresh.timer 2>/dev/null || true

systemctl daemon-reload
systemctl daemon-reexec
systemctl enable --now labo-watchdog.timer
systemctl restart cloudflared
echo "durcissement appliqué"
