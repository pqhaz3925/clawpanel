#!/usr/bin/env bash
set -euo pipefail

# ============================================================================
# ClawPanel Agent — install on each VPN node
# Usage: bash install-agent.sh
# ============================================================================

GREEN='\033[0;32m'
NC='\033[0m'

echo -e "${GREEN}Installing ClawPanel Agent...${NC}"

mkdir -p /opt/claw-agent /etc/claw-agent /etc/claw-xray-hy

# Agent
cp agent/agent.py /opt/claw-agent/

# Env
if [ ! -f /etc/claw-agent/env ]; then
    cp agent/env.example /etc/claw-agent/env
    echo "  Created /etc/claw-agent/env — edit with your panel URL and secret"
fi

# Systemd
cp deploy/claw-agent.service /etc/systemd/system/
cp deploy/claw-xray-hy.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable claw-agent claw-xray-hy

echo ""
echo -e "${GREEN}✅ Agent installed!${NC}"
echo ""
echo "  Next steps:"
echo "  1. Place xray-hy binary at /usr/local/bin/xray-hy"
echo "  2. Place TLS certs for your domain"
echo "  3. Edit /etc/claw-agent/env"
echo "  4. systemctl start claw-xray-hy claw-agent"
echo ""
