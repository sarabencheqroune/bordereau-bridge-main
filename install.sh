#!/usr/bin/env bash
set -euo pipefail
[[ $(id -u) -eq 0 ]] || { echo 'Exécuter sudo bash install.sh'; exit 1; }
[[ $(uname -m) == aarch64 ]] || { echo 'Utiliser Raspberry Pi OS 64 bits.'; exit 1; }
src=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
apt-get update
apt-get install -y python3 python3-venv cups cups-client curl
id bordereau >/dev/null 2>&1 || useradd --system --user-group --home-dir /var/lib/bordereau --shell /usr/sbin/nologin bordereau
usermod -aG lp bordereau
install -d -m 0755 /opt/bordereau
install -d -m 0750 -o root -g bordereau /etc/bordereau
install -d -m 0700 -o bordereau -g bordereau /var/lib/bordereau
# Arrêter le service existant avant de remplacer l'application.
systemctl stop bordereau.service 2>/dev/null || true
if [[ "$src" != /opt/bordereau ]]; then
 cp -R "$src/app" /opt/bordereau/
 install -m 0644 "$src/requirements.txt" /opt/bordereau/requirements.txt
fi
python3 -m venv /opt/bordereau/.venv
/opt/bordereau/.venv/bin/python -m pip install -r /opt/bordereau/requirements.txt
if [[ ! -f /etc/bordereau/config.env ]]; then
 python3 - <<'PY'
from pathlib import Path
import secrets
Path('/etc/bordereau/config.env').write_text('API_TOKEN='+secrets.token_hex(32)+'\nPRINTER_NAME=\nDATA_DIR=/var/lib/bordereau\nCUPS_SERVER=/run/cups/cups.sock\n')
PY
fi
chown root:bordereau /etc/bordereau/config.env
chmod 0640 /etc/bordereau/config.env
install -m 0644 "$src/bordereau.service" /etc/systemd/system/bordereau.service
systemctl daemon-reload
systemctl enable --now cups bordereau
echo 'Configurer PRINTER_NAME dans /etc/bordereau/config.env puis redémarrer bordereau.'
