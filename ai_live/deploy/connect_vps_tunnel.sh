#!/usr/bin/env bash
# Relie le VPS à Cloudflare par un tunnel sortant (aucun port à ouvrir chez l'hébergeur).
# Le tunnel « ai-live-vps » est déjà créé côté Cloudflare et publie ssh.labotory.site → SSH du VPS.
#
#   sudo bash connect_vps_tunnel.sh <JETON_DU_TUNNEL>
#
# Le jeton est secret : ne le publie pas (il permet de faire tourner ce tunnel ailleurs).
set -euo pipefail
TOKEN="${1:-}"
[[ -n "$TOKEN" ]] || { echo "usage : sudo bash $0 <JETON_DU_TUNNEL>"; exit 2; }
[[ $EUID -eq 0 ]] || { echo "Lance avec sudo."; exit 1; }
case "$(uname -m)" in
  x86_64) ARCH=amd64 ;; aarch64|arm64) ARCH=arm64 ;; *) echo "architecture non gérée : $(uname -m)"; exit 1 ;;
esac
echo "==> Installation de cloudflared ($ARCH)"
curl -fsSL -o /tmp/cloudflared.deb "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-$ARCH.deb"
dpkg -i /tmp/cloudflared.deb >/dev/null
echo "==> Démarrage du tunnel (service permanent, redémarre avec la machine)"
cloudflared service uninstall >/dev/null 2>&1 || true
cloudflared service install "$TOKEN"
sleep 3
systemctl is-active --quiet cloudflared && echo "OK : tunnel actif. Tu peux fermer cette fenêtre." \
  || { journalctl -u cloudflared -n 20 --no-pager; echo "⚠ le tunnel ne démarre pas"; exit 1; }
