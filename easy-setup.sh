#!/usr/bin/env bash
# ClawPanel Easy Setup — single-server (panel + node on same machine)
# Usage: curl -fsSL https://raw.githubusercontent.com/pqhaz3925/clawpanel/main/easy-setup.sh | bash
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log() { echo -e "${GREEN}[ClawPanel]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err() { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# --- Prereqs ---
[[ $EUID -ne 0 ]] && err "Run as root"
[[ ! -f /etc/debian_version ]] && err "Only Debian/Ubuntu supported"

log "ClawPanel Easy Setup — single-server mode"
echo ""

# --- Collect info ---
read -rp "$(echo -e "${CYAN}Domain for this server (e.g. vpn.example.com):${NC} ")" DOMAIN
[[ -z "$DOMAIN" ]] && err "Domain required"

read -rp "$(echo -e "${CYAN}Node name (e.g. NL1):${NC} ")" NODE_NAME
[[ -z "$NODE_NAME" ]] && NODE_NAME="node1"

read -rp "$(echo -e "${CYAN}Node flag emoji (e.g. 🇳🇱):${NC} ")" NODE_FLAG
[[ -z "$NODE_FLAG" ]] && NODE_FLAG="🌍"

echo ""
log "Domain: $DOMAIN | Node: $NODE_NAME $NODE_FLAG"
echo ""

# --- Install dependencies ---
log "Installing packages..."
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip curl > /dev/null

# --- Install Caddy ---
if ! command -v caddy &>/dev/null; then
    log "Installing Caddy..."
    apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https > /dev/null
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg 2>/dev/null
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list > /dev/null
    apt-get update -qq
    apt-get install -y -qq caddy > /dev/null
fi

# --- Download xray-hy ---
XRAY_BIN="/usr/local/bin/xray-hy"
if [[ ! -f "$XRAY_BIN" ]]; then
    log "Downloading xray-hy (finalmask build)..."
    curl -fsSL -o "$XRAY_BIN" \
        "https://github.com/pqhaz3925/clawpanel/releases/download/v2.1.0/xray-hy-linux-amd64"
    chmod +x "$XRAY_BIN"
    log "xray-hy: $("$XRAY_BIN" version 2>&1 | head -1)"
fi

# --- Setup panel ---
log "Setting up panel..."
PANEL_DIR="/opt/clawpanel"
mkdir -p "$PANEL_DIR"/{data,templates,static}

# Download panel files from repo
REPO_RAW="https://raw.githubusercontent.com/pqhaz3925/clawpanel/main"
for f in main.py models.py xray.py; do
    curl -fsSL -o "$PANEL_DIR/$f" "$REPO_RAW/panel/$f"
done
for f in base.html login.html dashboard.html users.html nodes.html settings.html sub_info.html; do
    curl -fsSL -o "$PANEL_DIR/templates/$f" "$REPO_RAW/panel/templates/$f"
done

# Download pre-built React frontend
for f in index.html vite.svg; do
    curl -fsSL -o "$PANEL_DIR/static/$f" "$REPO_RAW/panel/static/$f" 2>/dev/null || true
done
mkdir -p "$PANEL_DIR/static/assets"
# Get asset filenames from index.html
if [[ -f "$PANEL_DIR/static/index.html" ]]; then
    for asset in $(grep -oP 'assets/[^"]+' "$PANEL_DIR/static/index.html"); do
        curl -fsSL -o "$PANEL_DIR/static/$asset" "$REPO_RAW/panel/static/$asset" 2>/dev/null || true
    done
fi

# Python venv
if [[ ! -d "$PANEL_DIR/venv" ]]; then
    python3 -m venv "$PANEL_DIR/venv"
fi
"$PANEL_DIR/venv/bin/pip" install -q fastapi uvicorn[standard] jinja2 python-multipart aiosqlite

# Generate agent secret
AGENT_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")

# --- TLS certs via Caddy (auto) ---
# Caddy handles TLS automatically, but xray-hy needs certs too.
# We'll use Caddy's managed certs or generate self-signed for local.
CERT_DIR="/etc/ssl/clawpanel"
mkdir -p "$CERT_DIR"

# --- Panel env ---
cat > "$PANEL_DIR/.env" << ENVEOF
# ClawPanel Environment
# TLS cert paths for xray-hy (will be set after Caddy provisions certs)
CERT_VLESS_FULLCHAIN=$CERT_DIR/fullchain.pem
CERT_VLESS_KEY=$CERT_DIR/key.pem
CERT_HY2_FULLCHAIN=$CERT_DIR/fullchain.pem
CERT_HY2_KEY=$CERT_DIR/key.pem
XDNS_DOMAIN=t.$DOMAIN
PANEL_HOST=$DOMAIN
ENVEOF

# --- Panel systemd service ---
cat > /etc/systemd/system/clawpanel.service << SVCEOF
[Unit]
Description=ClawPanel - VPN Management Panel
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$PANEL_DIR
ExecStart=$PANEL_DIR/venv/bin/uvicorn main:app --host 127.0.0.1 --port 3100
Restart=always
RestartSec=3
EnvironmentFile=$PANEL_DIR/.env
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
SVCEOF

# --- Agent setup ---
log "Setting up node agent..."
AGENT_DIR="/opt/claw-agent"
AGENT_ENV="/etc/claw-agent"
mkdir -p "$AGENT_DIR" "$AGENT_ENV" "/etc/claw-xray-hy"

curl -fsSL -o "$AGENT_DIR/agent.py" "$REPO_RAW/agent/agent.py"

cat > "$AGENT_ENV/env" << AEOF
PANEL_URL=https://$DOMAIN
AGENT_SECRET=$AGENT_SECRET
NODE_NAME=$NODE_NAME
XRAY_HY_BIN=$XRAY_BIN
XRAY_HY_CFG=/etc/claw-xray-hy/config.json
XRAY_HY_SERVICE=claw-xray-hy
XRAY_API_PORT=10085
SYNC_INTERVAL=60
AEOF

# --- Agent systemd ---
cat > /etc/systemd/system/claw-agent.service << ASEOF
[Unit]
Description=ClawAgent - Xray config sync daemon
After=network.target clawpanel.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 $AGENT_DIR/agent.py
EnvironmentFile=$AGENT_ENV/env
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
ASEOF

# --- Xray-hy systemd ---
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

# --- Caddy config ---
cat > /etc/caddy/Caddyfile << CEOF
$DOMAIN {
    reverse_proxy 127.0.0.1:3100
}
CEOF

# --- Cert provisioning ---
# Use Caddy to get certs, then symlink for xray-hy
log "Provisioning TLS certificate via Caddy..."
systemctl restart caddy
sleep 5

# Find Caddy's cert storage
CADDY_CERT_DIR="/var/lib/caddy/.local/share/caddy/certificates/acme-v02.api.letsencrypt.org-directory/$DOMAIN"
if [[ -d "$CADDY_CERT_DIR" ]]; then
    ln -sf "$CADDY_CERT_DIR/$DOMAIN.crt" "$CERT_DIR/fullchain.pem"
    ln -sf "$CADDY_CERT_DIR/$DOMAIN.key" "$CERT_DIR/key.pem"
    log "Certs linked from Caddy"
else
    # Fallback: generate self-signed (for testing)
    warn "Caddy cert not found yet. Generating self-signed cert..."
    openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 \
        -keyout "$CERT_DIR/key.pem" -out "$CERT_DIR/fullchain.pem" \
        -days 365 -nodes -subj "/CN=$DOMAIN" 2>/dev/null
    warn "Using self-signed cert. Caddy will provision real cert shortly."
    warn "After Caddy gets the cert, run:"
    warn "  ln -sf /var/lib/caddy/.local/share/caddy/certificates/acme-v02.api.letsencrypt.org-directory/$DOMAIN/$DOMAIN.crt $CERT_DIR/fullchain.pem"
    warn "  ln -sf /var/lib/caddy/.local/share/caddy/certificates/acme-v02.api.letsencrypt.org-directory/$DOMAIN/$DOMAIN.key $CERT_DIR/key.pem"
    warn "  systemctl restart claw-agent"
fi

# --- Start services ---
log "Starting services..."
systemctl daemon-reload
systemctl enable --now clawpanel claw-xray-hy claw-agent caddy

# --- Init DB with the node ---
log "Waiting for panel to start..."
sleep 3

# Add node and set agent secret via API
curl -sk "https://127.0.0.1:3100/api/auth/login" \
    --resolve "127.0.0.1:3100:127.0.0.1" \
    -X POST -H "Content-Type: application/json" \
    -d '{"username":"admin","password":"ClawVPN2025"}' \
    -c /tmp/claw-setup-cookies 2>/dev/null || true

# Wait for panel to be ready
for i in $(seq 1 10); do
    if curl -sf http://127.0.0.1:3100/api/auth/login -X POST \
        -H "Content-Type: application/json" \
        -d '{"username":"admin","password":"ClawVPN2025"}' \
        -c /tmp/claw-setup-cookies -o /dev/null 2>/dev/null; then
        break
    fi
    sleep 2
done

# Set agent secret in DB
"$PANEL_DIR/venv/bin/python3" -c "
import sqlite3
c = sqlite3.connect('$PANEL_DIR/data/claw.db')
c.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', ('agent_secret', '$AGENT_SECRET'))
c.commit()
c.close()
"

# Create node via API
curl -sf http://127.0.0.1:3100/api/nodes \
    -X POST -H "Content-Type: application/json" \
    -b /tmp/claw-setup-cookies \
    -d "{\"name\":\"$NODE_NAME\",\"address\":\"$DOMAIN\",\"flag\":\"$NODE_FLAG\",\"label\":\"$NODE_NAME\"}" \
    -o /dev/null 2>/dev/null || true

rm -f /tmp/claw-setup-cookies

# --- Done ---
echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║            ClawPanel installed successfully!          ║${NC}"
echo -e "${GREEN}╠═══════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║${NC} Panel:    ${CYAN}https://$DOMAIN${NC}"
echo -e "${GREEN}║${NC} Login:    ${CYAN}admin / ClawVPN2025${NC}"
echo -e "${GREEN}║${NC} Node:     ${CYAN}$NODE_NAME ($DOMAIN)${NC}"
echo -e "${GREEN}║${NC} Agent:    ${CYAN}$AGENT_SECRET${NC}"
echo -e "${GREEN}║${NC}"
echo -e "${GREEN}║${NC} ${YELLOW}CHANGE THE DEFAULT PASSWORD IMMEDIATELY!${NC}"
echo -e "${GREEN}║${NC}"
echo -e "${GREEN}║${NC} Services:"
echo -e "${GREEN}║${NC}   systemctl status clawpanel"
echo -e "${GREEN}║${NC}   systemctl status claw-agent"
echo -e "${GREEN}║${NC}   systemctl status claw-xray-hy"
echo -e "${GREEN}║${NC}   systemctl status caddy"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════╝${NC}"
