#!/usr/bin/env bash
# ============================================================================
# ClawPanel — All-in-One Setup (Panel + Node on same server)
#
# Installs:
#   - Panel (FastAPI + uvicorn + Caddy reverse proxy)
#   - Node  (xray-hy + agent + nginx TLS frontend + fake site)
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/pqhaz3925/clawpanel/main/setup-all.sh | bash
#
# Requirements:
#   - Ubuntu/Debian, root access
#   - Domain pointed to this server (A record)
#   - Port 443, 2053, 53, 9053 available
# ============================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log() { echo -e "${GREEN}[ClawAll]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err() { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

[[ $EUID -ne 0 ]] && err "Run as root"

echo -e "${CYAN}
   ██████╗██╗      █████╗ ██╗    ██╗
  ██╔════╝██║     ██╔══██╗██║    ██║
  ██║     ██║     ███████║██║ █╗ ██║
  ██║     ██║     ██╔══██║██║███╗██║
  ╚██████╗███████╗██║  ██║╚███╔███╔╝
   ╚═════╝╚══════╝╚═╝  ╚═╝ ╚══╝╚══╝  All-in-One Installer
${NC}"

# ── Collect info ─────────────────────────────────────────────────────────────

read -rp "$(echo -e "${CYAN}Domain for this server (e.g. nl2.clawvpn.lol):${NC} ")" DOMAIN
[[ -z "$DOMAIN" ]] && err "Domain required"

read -rp "$(echo -e "${CYAN}Panel admin password [ClawVPN2025]:${NC} ")" ADMIN_PASS
ADMIN_PASS="${ADMIN_PASS:-ClawVPN2025}"

read -rp "$(echo -e "${CYAN}Node name (e.g. NL1):${NC} ")" NODE_NAME
[[ -z "$NODE_NAME" ]] && err "Node name required"

echo ""
log "Domain: $DOMAIN | Node: $NODE_NAME"
echo ""

PANEL_DIR="/opt/clawpanel"
AGENT_DIR="/opt/claw-agent"
XRAY_BIN="/usr/local/bin/xray-hy"
REPO_RAW="https://raw.githubusercontent.com/pqhaz3925/clawpanel/main"
AGENT_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"

# ── 1. System dependencies ──────────────────────────────────────────────────

log "[1/8] Installing system packages..."
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip curl nginx certbot \
    python3-certbot-nginx caddy > /dev/null 2>&1
log "  Dependencies installed"

# ── 2. TLS certificates ─────────────────────────────────────────────────────

log "[2/8] Obtaining TLS certificates..."
CERT_DIR="/var/lib/marzban/certs"
mkdir -p "$CERT_DIR"

# Stop nginx/caddy temporarily for standalone cert
systemctl stop nginx 2>/dev/null || true
systemctl stop caddy 2>/dev/null || true

if [[ ! -f "$CERT_DIR/fullchain.pem" ]]; then
    certbot certonly --standalone -d "$DOMAIN" --non-interactive --agree-tos \
        --register-unsafely-without-email \
        --fullchain-path "$CERT_DIR/fullchain.pem" \
        --key-path "$CERT_DIR/key.pem" \
        || warn "Certbot failed — you'll need to set up certs manually"
    # certbot puts certs in /etc/letsencrypt, symlink if needed
    if [[ ! -f "$CERT_DIR/fullchain.pem" && -d /etc/letsencrypt/live/$DOMAIN ]]; then
        ln -sf "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" "$CERT_DIR/fullchain.pem"
        ln -sf "/etc/letsencrypt/live/$DOMAIN/privkey.pem" "$CERT_DIR/key.pem"
    fi
fi

if [[ -f "$CERT_DIR/fullchain.pem" ]]; then
    log "  Certs ready: $CERT_DIR/"
else
    warn "  No certs found — configure manually in .env"
fi

# ── 3. Panel setup ──────────────────────────────────────────────────────────

log "[3/8] Setting up panel..."
mkdir -p "$PANEL_DIR"/{data,templates,static}

# Download panel files
for f in main.py xray.py; do
    curl -fsSL -o "$PANEL_DIR/$f" "$REPO_RAW/panel/$f"
done
curl -fsSL -o "$PANEL_DIR/models.py" "$REPO_RAW/panel/models.py"

# Download templates if they exist
for t in login.html base.html; do
    curl -fsSL -o "$PANEL_DIR/templates/$t" "$REPO_RAW/panel/templates/$t" 2>/dev/null || true
done

# Python venv
python3 -m venv "$PANEL_DIR/venv"
"$PANEL_DIR/venv/bin/pip" install -q fastapi 'uvicorn[standard]' jinja2 python-multipart aiosqlite

# .env
if [[ ! -f "$PANEL_DIR/.env" ]]; then
    cat > "$PANEL_DIR/.env" << ENVEOF
# ClawPanel environment config
# Corp exit (VLESS Reality proxy chain) — leave empty to skip
CORP_EXIT_ADDRESS=
CORP_EXIT_PORT=
CORP_EXIT_UUID=
CORP_EXIT_PUBKEY=
CORP_EXIT_SNI=
CORP_EXIT_SHORT_ID=
CORP_EXIT_FINGERPRINT=chrome

# DNS domain for HY2 XDNS mask
XDNS_DOMAIN=t.example.com

# Feature flags
ENABLE_XHTTP_H3=1
ENABLE_STEALTH=1
SUDOKU_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_urlsafe(16))')

# Scrape SOCKS proxy (optional)
SCRAPE_SOCKS_PORT=11080
SCRAPE_SOCKS_USER=clawscrape
SCRAPE_SOCKS_PASS=$(python3 -c 'import secrets; print(secrets.token_urlsafe(12))')
SCRAPE_API_TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')

# Cert paths (auto-detected)
CERT_VLESS_FULLCHAIN=$CERT_DIR/fullchain.pem
CERT_VLESS_KEY=$CERT_DIR/key.pem
CERT_HY2_FULLCHAIN=$CERT_DIR/fullchain.pem
CERT_HY2_KEY=$CERT_DIR/key.pem
ENVEOF
    log "  Created $PANEL_DIR/.env"
fi

# Panel systemd service
cat > /etc/systemd/system/clawpanel.service << 'SEOF'
[Unit]
Description=ClawPanel - VPN Management Panel
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/clawpanel
EnvironmentFile=-/opt/clawpanel/.env
ExecStart=/opt/clawpanel/venv/bin/uvicorn main:app --host 127.0.0.1 --port 3100
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
SEOF

log "  Panel installed"

# ── 4. Caddy reverse proxy ──────────────────────────────────────────────────

log "[4/8] Configuring Caddy (panel reverse proxy)..."
PANEL_DOMAIN="panel.$DOMAIN"

# Check if domain starts with a node prefix, derive panel domain
if echo "$DOMAIN" | grep -qE '^[a-z]+[0-9]*\.'; then
    # e.g. nl2.clawvpn.lol → panel.clawvpn.lol
    BASE_DOMAIN=$(echo "$DOMAIN" | sed 's/^[^.]*\.//')
    PANEL_DOMAIN="panel.$BASE_DOMAIN"
fi

read -rp "$(echo -e "${CYAN}Panel domain [$PANEL_DOMAIN]:${NC} ")" CUSTOM_PANEL_DOMAIN
PANEL_DOMAIN="${CUSTOM_PANEL_DOMAIN:-$PANEL_DOMAIN}"

cat > /etc/caddy/Caddyfile << CADEOF
$PANEL_DOMAIN {
    reverse_proxy localhost:3100
}
CADEOF

log "  Caddy → $PANEL_DOMAIN → localhost:3100"

# ── 5. Download xray-hy binary ──────────────────────────────────────────────

log "[5/8] Downloading xray-hy binary..."
if [[ ! -f "$XRAY_BIN" ]]; then
    # Try to download from GitHub releases
    RELEASE_URL="https://github.com/pqhaz3925/clawpanel/releases/download/v2.3.0/xray-hy-linux-amd64"
    curl -fsSL -o "$XRAY_BIN" "$RELEASE_URL" 2>/dev/null \
        || curl -fsSL -o "$XRAY_BIN" \
            "https://github.com/pqhaz3925/clawpanel/releases/download/v2.1.0/xray-hy-linux-amd64" \
        || err "Failed to download xray-hy binary"
    chmod +x "$XRAY_BIN"
fi
log "  xray-hy: $($XRAY_BIN version 2>&1 | head -1)"

# ── 6. Agent setup (local node) ─────────────────────────────────────────────

log "[6/8] Setting up local agent..."
mkdir -p "$AGENT_DIR" "/etc/claw-agent" "/etc/claw-xray-hy"

curl -fsSL -o "$AGENT_DIR/agent.py" "$REPO_RAW/agent/agent.py"

cat > /etc/claw-agent/env << AEOF
PANEL_URL=http://127.0.0.1:3100
AGENT_SECRET=$AGENT_SECRET
NODE_NAME=$NODE_NAME
XRAY_HY_BIN=$XRAY_BIN
XRAY_HY_CFG=/etc/claw-xray-hy/config.json
XRAY_HY_SERVICE=claw-xray-hy
XRAY_API_PORT=10085
SYNC_INTERVAL=60
CERT_VLESS_FULLCHAIN=$CERT_DIR/fullchain.pem
CERT_VLESS_KEY=$CERT_DIR/key.pem
CERT_HY2_FULLCHAIN=$CERT_DIR/fullchain.pem
CERT_HY2_KEY=$CERT_DIR/key.pem
AEOF

# Agent talks to panel on localhost — no need for HTTPS

# Agent systemd
cat > /etc/systemd/system/claw-agent.service << 'ASEOF'
[Unit]
Description=ClawAgent - Xray config sync daemon
After=clawpanel.service network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /opt/claw-agent/agent.py
EnvironmentFile=/etc/claw-agent/env
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
ASEOF

# xray-hy systemd
cat > /etc/systemd/system/claw-xray-hy.service << XSEOF
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
XSEOF

log "  Agent configured (localhost → panel)"

# ── 7. Nginx (TLS frontend for XHTTP) ───────────────────────────────────────

log "[7/8] Nginx will be auto-configured by agent on first sync"
# Remove default nginx site
rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true

# ── 8. Firewall ─────────────────────────────────────────────────────────────

log "[8/8] Configuring firewall..."
if command -v ufw &>/dev/null; then
    ufw allow 22/tcp    >/dev/null 2>&1 || true
    ufw allow 80/tcp    >/dev/null 2>&1 || true
    ufw allow 443/tcp   >/dev/null 2>&1 || true
    ufw allow 2053/tcp  >/dev/null 2>&1 || true
    ufw allow 2054/tcp  >/dev/null 2>&1 || true
    ufw allow 2055/tcp  >/dev/null 2>&1 || true
    ufw allow 4443/tcp  >/dev/null 2>&1 || true
    ufw allow 4444/tcp  >/dev/null 2>&1 || true
    ufw allow 53/udp    >/dev/null 2>&1 || true
    ufw allow 9053/udp  >/dev/null 2>&1 || true
    ufw allow 8443/udp  >/dev/null 2>&1 || true
    ufw allow 8444/udp  >/dev/null 2>&1 || true
    ufw allow 8445/udp  >/dev/null 2>&1 || true
    ufw allow 8446/udp  >/dev/null 2>&1 || true
    ufw allow 11080/tcp >/dev/null 2>&1 || true
    log "  UFW rules added"
else
    warn "  No ufw found — configure firewall manually"
fi

# ── Start everything ─────────────────────────────────────────────────────────

log "Starting services..."
systemctl daemon-reload
systemctl enable --now clawpanel
sleep 2

# Initialize DB and set agent secret
python3 -c "
import sys, asyncio
sys.path.insert(0, '$PANEL_DIR')
import models

async def init():
    await models.init_db()
    await models.set_setting(models.SETTING_AGENT_SECRET, '$AGENT_SECRET')
    # Create admin
    try:
        await models.create_admin('admin', '$ADMIN_PASS')
    except:
        pass
    # Add this node
    try:
        await models.add_node('$NODE_NAME', '$DOMAIN')
    except:
        pass
    print('DB initialized')

asyncio.run(init())
" 2>/dev/null || warn "Auto-init failed — panel will init on first start"

# Restart panel to pick up DB changes
systemctl restart clawpanel
sleep 2

systemctl enable --now caddy
systemctl enable --now claw-xray-hy claw-agent

echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✅ ClawPanel All-in-One setup complete!${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  Panel:    ${CYAN}https://$PANEL_DOMAIN${NC}"
echo -e "  Login:    ${CYAN}admin / $ADMIN_PASS${NC}"
echo -e "  Node:     ${CYAN}$NODE_NAME ($DOMAIN)${NC}"
echo ""
echo -e "  Agent secret: ${YELLOW}$AGENT_SECRET${NC}"
echo -e "  (saved in /etc/claw-agent/env and panel DB)"
echo ""
echo -e "${YELLOW}  Services:${NC}"
echo "    systemctl status clawpanel     — panel"
echo "    systemctl status claw-agent    — agent (config sync)"
echo "    systemctl status claw-xray-hy  — xray-hy (VPN)"
echo "    systemctl status caddy         — reverse proxy"
echo "    systemctl status nginx         — TLS frontend"
echo ""
echo -e "${YELLOW}  The agent syncs config every 60s. Give it a minute and check:${NC}"
echo "    journalctl -u claw-agent -f"
echo ""
echo -e "${YELLOW}  Config files:${NC}"
echo "    Panel env:   $PANEL_DIR/.env"
echo "    Agent env:   /etc/claw-agent/env"
echo "    Xray config: /etc/claw-xray-hy/config.json (auto-managed)"
echo "    Nginx:       /etc/nginx/sites-enabled/claw.conf (auto-managed)"
echo ""
