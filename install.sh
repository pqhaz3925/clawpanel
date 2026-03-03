#!/usr/bin/env bash
set -euo pipefail

# ============================================================================
# ClawPanel — quick install script
# Usage: bash install.sh
# ============================================================================

PANEL_DIR="/opt/clawpanel"
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}
   ██████╗██╗      █████╗ ██╗    ██╗
  ██╔════╝██║     ██╔══██╗██║    ██║
  ██║     ██║     ███████║██║ █╗ ██║
  ██║     ██║     ██╔══██║██║███╗██║
  ╚██████╗███████╗██║  ██║╚███╔███╔╝
   ╚═════╝╚══════╝╚═╝  ╚═╝ ╚══╝╚══╝  Panel Installer
${NC}"

# --- 1. Dependencies ---
echo -e "${GREEN}[1/5] Installing dependencies...${NC}"
apt-get update -qq
apt-get install -y python3 python3-venv python3-pip caddy curl

# --- 2. Panel files ---
echo -e "${GREEN}[2/5] Setting up panel...${NC}"
mkdir -p "$PANEL_DIR"/{data,templates,static}
cp panel/*.py "$PANEL_DIR/"
cp panel/templates/*.html "$PANEL_DIR/templates/"
cp panel/.env.example "$PANEL_DIR/.env.example"

if [ ! -f "$PANEL_DIR/.env" ]; then
    cp "$PANEL_DIR/.env.example" "$PANEL_DIR/.env"
    echo "  Created .env — edit it with your config"
fi

# --- 3. Python venv ---
echo -e "${GREEN}[3/5] Setting up Python environment...${NC}"
python3 -m venv "$PANEL_DIR/venv"
"$PANEL_DIR/venv/bin/pip" install -q -r panel/requirements.txt

# --- 4. Systemd ---
echo -e "${GREEN}[4/5] Installing systemd service...${NC}"
cp deploy/clawpanel.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable clawpanel

# --- 5. Caddy ---
echo -e "${GREEN}[5/5] Configuring Caddy...${NC}"
if [ ! -f /etc/caddy/Caddyfile ] || ! grep -q "clawpanel" /etc/caddy/Caddyfile 2>/dev/null; then
    echo "  ⚠  Edit /etc/caddy/Caddyfile with your domain (see deploy/Caddyfile.example)"
fi

echo ""
echo -e "${GREEN}✅ ClawPanel installed!${NC}"
echo ""
echo "  Next steps:"
echo "  1. Edit $PANEL_DIR/.env with your config"
echo "  2. Edit /etc/caddy/Caddyfile with your domain"
echo "  3. systemctl start clawpanel"
echo "  4. systemctl reload caddy"
echo ""
echo "  Default login: admin / ClawVPN2025"
echo "  Panel will be at: https://your-domain/"
echo ""
