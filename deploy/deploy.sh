#!/bin/bash
#
# Deploy Heating Oil Monitor to Home Assistant via SSH
#
# Usage:
#   HA_HOST=homeassistant.local HA_USER=hassio HA_PASS=yourpassword ./deploy.sh
#
# Environment variables (required):
#   HA_HOST  - Home Assistant hostname or IP
#   HA_USER  - SSH username
#   HA_PASS  - SSH password
#
# Optional:
#   HA_TOKEN - Long-lived access token for HA restart (if not set, restart is skipped)
#

set -euo pipefail

# Validate required environment variables
if [[ -z "${HA_HOST:-}" ]]; then
    echo "ERROR: HA_HOST is not set"
    exit 1
fi
if [[ -z "${HA_USER:-}" ]]; then
    echo "ERROR: HA_USER is not set"
    exit 1
fi
if [[ -z "${HA_PASS:-}" ]]; then
    echo "ERROR: HA_PASS is not set"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPONENT_DIR="$PROJECT_DIR/custom_components/heating_oil_monitor"
REMOTE_BASE="/config/custom_components/heating_oil_monitor"

echo "=== Heating Oil Monitor Deployment ==="
echo "Host:      $HA_HOST"
echo "User:      $HA_USER"
echo "Source:    $COMPONENT_DIR"
echo "Target:    $HA_HOST:$REMOTE_BASE"
echo ""

# Check sshpass is available
if ! command -v sshpass &> /dev/null; then
    echo "ERROR: sshpass is required but not installed."
    echo "  Install with: brew install hudochenkov/sshpass/sshpass"
    exit 1
fi

SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"

ssh_cmd() {
    sshpass -p "$HA_PASS" ssh $SSH_OPTS "$HA_USER@$HA_HOST" "$@"
}

sudo_ssh() {
    ssh_cmd "echo '$HA_PASS' | sudo -S $* 2>/dev/null"
}

echo "[1/4] Cleaning remote directory..."
sudo_ssh "rm -rf $REMOTE_BASE"
sudo_ssh "mkdir -p $REMOTE_BASE/translations"

echo "[2/4] Copying component files via tar over SSH..."
# Upload tar to a temp location (writable by hassio), then sudo-extract
REMOTE_TMP="/tmp/heating_oil_monitor_deploy.tar"
tar --exclude='__pycache__' --exclude='*.pyc' \
    -cf - -C "$PROJECT_DIR" custom_components/heating_oil_monitor | \
    ssh_cmd "cat > $REMOTE_TMP"
sudo_ssh "tar -xf $REMOTE_TMP -C /config --strip-components=0"
sudo_ssh "rm -f $REMOTE_TMP"

echo "[3/4] Verifying deployment..."
ssh_cmd "ls -la $REMOTE_BASE/"
DEPLOYED_VERSION=$(ssh_cmd "cat $REMOTE_BASE/manifest.json" | grep '"version"' | sed 's/.*: *"\(.*\)".*/\1/')
echo "Deployed version: $DEPLOYED_VERSION"

echo "[4/4] Restarting Home Assistant..."
if [[ -n "${HA_TOKEN:-}" ]]; then
    RESTART_RESULT=$(curl -sf -X POST \
        "http://$HA_HOST:8123/api/services/homeassistant/restart" \
        -H "Authorization: Bearer $HA_TOKEN" \
        -H "Content-Type: application/json" 2>&1) && \
        echo "Home Assistant restart triggered." || \
        echo "WARNING: Restart via API failed. Please restart HA manually."
else
    echo "SKIPPED: HA_TOKEN not set. Please restart Home Assistant manually."
    echo "  Go to: http://$HA_HOST:8123 → Developer Tools → Restart"
fi

echo ""
echo "=== Deployment complete ==="
