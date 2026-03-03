# ClawPanel — Setup Router (Panel Server)

## When to use
User wants to set up the ClawPanel management server (the "router" that manages VPN nodes).

## Steps

1. **Prerequisites**: Debian/Ubuntu server with a domain pointing to it
2. **Install**: `curl -fsSL https://raw.githubusercontent.com/pqhaz3925/clawpanel/main/easy-setup.sh | bash`
3. **Or manual install**: Follow steps below

### Manual Install

```bash
# Install deps
apt-get update && apt-get install -y python3 python3-venv caddy

# Download panel
mkdir -p /opt/clawpanel/{data,templates,static}
cd /opt/clawpanel
# Copy panel/*.py, panel/templates/*.html, panel/static/*

# Python venv
python3 -m venv venv
venv/bin/pip install fastapi uvicorn[standard] jinja2 python-multipart aiosqlite

# Create .env
cat > .env << 'EOF'
CERT_VLESS_FULLCHAIN=/path/to/fullchain.pem
CERT_VLESS_KEY=/path/to/key.pem
CERT_HY2_FULLCHAIN=/path/to/fullchain.pem
CERT_HY2_KEY=/path/to/key.pem
XDNS_DOMAIN=t.example.com
# Optional corp exit:
# CORP_EXIT_ADDRESS=x.x.x.x
# CORP_EXIT_PORT=51659
# CORP_EXIT_UUID=...
# CORP_EXIT_PUBKEY=...
# CORP_EXIT_SNI=yr.no
# CORP_EXIT_SHORT_ID=...
EOF

# Systemd service
cat > /etc/systemd/system/clawpanel.service << 'EOF'
[Unit]
Description=ClawPanel
After=network.target
[Service]
Type=simple
WorkingDirectory=/opt/clawpanel
ExecStart=/opt/clawpanel/venv/bin/uvicorn main:app --host 127.0.0.1 --port 3100
EnvironmentFile=/opt/clawpanel/.env
Environment=PYTHONUNBUFFERED=1
Restart=always
[Install]
WantedBy=multi-user.target
EOF

# Caddyfile
cat > /etc/caddy/Caddyfile << 'EOF'
your-domain.com {
    reverse_proxy 127.0.0.1:3100
}
EOF

systemctl daemon-reload
systemctl enable --now clawpanel caddy
```

## Key facts
- Default login: `admin / ClawVPN2025` — CHANGE IMMEDIATELY
- Panel runs on port 3100 behind Caddy reverse proxy
- Agent secret is auto-generated, visible in Settings page
- DB is at `/opt/clawpanel/data/claw.db` (SQLite)
- Corp exit is optional — configured entirely via .env

## Troubleshooting
- Panel won't start: check `journalctl -u clawpanel -f`
- 502 from Caddy: panel not running on :3100
- Sub links wrong domain: set `PANEL_HOST=your-domain.com` in .env
