#!/usr/bin/env bash
# ClawPanel — Add remote node setup
# Run on the NODE server (not the panel server)
# Usage: curl -fsSL https://raw.githubusercontent.com/pqhaz3925/clawpanel/main/setup-node.sh | bash
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log() { echo -e "${GREEN}[ClawNode]${NC} $*"; }
err() { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

[[ $EUID -ne 0 ]] && err "Run as root"

log "ClawPanel — Node Setup"
echo ""

# --- Collect info ---
read -rp "$(echo -e "${CYAN}Panel URL (e.g. https://panel.clawvpn.lol):${NC} ")" PANEL_URL
[[ -z "$PANEL_URL" ]] && err "Panel URL required"

read -rp "$(echo -e "${CYAN}Agent secret (from panel Settings page):${NC} ")" AGENT_SECRET
[[ -z "$AGENT_SECRET" ]] && err "Agent secret required"

read -rp "$(echo -e "${CYAN}Node name (must match panel, e.g. NL1):${NC} ")" NODE_NAME
[[ -z "$NODE_NAME" ]] && err "Node name required"

read -rp "$(echo -e "${CYAN}TLS cert fullchain path:${NC} ")" CERT_FULL
[[ -z "$CERT_FULL" ]] && CERT_FULL="/var/lib/marzban/certs/fullchain.pem"

read -rp "$(echo -e "${CYAN}TLS cert key path:${NC} ")" CERT_KEY
[[ -z "$CERT_KEY" ]] && CERT_KEY="/var/lib/marzban/certs/key.pem"

echo ""
log "Panel: $PANEL_URL | Node: $NODE_NAME"

# --- Download xray-hy ---
XRAY_BIN="/usr/local/bin/xray-hy"
if [[ ! -f "$XRAY_BIN" ]]; then
    log "Downloading xray-hy..."
    curl -fsSL -o "$XRAY_BIN" \
        "https://github.com/pqhaz3925/clawpanel/releases/download/v2.1.0/xray-hy-linux-amd64"
    chmod +x "$XRAY_BIN"
fi

# --- Agent setup ---
log "Setting up agent..."
AGENT_DIR="/opt/claw-agent"
mkdir -p "$AGENT_DIR" "/etc/claw-agent" "/etc/claw-xray-hy"

REPO_RAW="https://raw.githubusercontent.com/pqhaz3925/clawpanel/main"
curl -fsSL -o "$AGENT_DIR/agent.py" "$REPO_RAW/agent/agent.py"

cat > /etc/claw-agent/env << EOF
PANEL_URL=$PANEL_URL
AGENT_SECRET=$AGENT_SECRET
NODE_NAME=$NODE_NAME
XRAY_HY_BIN=$XRAY_BIN
XRAY_HY_CFG=/etc/claw-xray-hy/config.json
XRAY_HY_SERVICE=claw-xray-hy
XRAY_API_PORT=10085
SYNC_INTERVAL=60
CERT_VLESS_FULLCHAIN=$CERT_FULL
CERT_VLESS_KEY=$CERT_KEY
CERT_HY2_FULLCHAIN=$CERT_FULL
CERT_HY2_KEY=$CERT_KEY
EOF

# --- Systemd services ---
cat > /etc/systemd/system/claw-agent.service << SEOF
[Unit]
Description=ClawAgent - Xray config sync daemon
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 $AGENT_DIR/agent.py
EnvironmentFile=/etc/claw-agent/env
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SEOF

cat > /etc/systemd/system/claw-xray-hy.service << XEOF
[Unit]
Description=Claw Xray-HY (finalmask)
After=network.target

[Service]
Type=simple
ExecStart=$XRAY_BIN run -config /etc/claw-xray-hy/config.json
Restart=always
RestartSec=5
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
XEOF

systemctl daemon-reload
systemctl enable --now claw-xray-hy claw-agent

echo ""
log "Node setup complete!"
log "Agent will sync config from panel every 60 seconds."
log "Make sure you've added node '$NODE_NAME' in the panel first!"
echo ""
echo -e "${YELLOW}Check status:${NC}"
echo "  systemctl status claw-agent"
echo "  systemctl status claw-xray-hy"
echo "  journalctl -u claw-agent -f"
