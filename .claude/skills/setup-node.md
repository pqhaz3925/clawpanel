# ClawPanel — Setup Node (VPN Server)

## When to use
User wants to add a new VPN node that connects to an existing ClawPanel router.

## Prerequisites
- Node server with Debian/Ubuntu
- TLS certificate for the node's domain (Let's Encrypt, acme.sh, etc.)
- Panel already running with the node added in the UI

## Steps

### 1. Add node in panel first
In the ClawPanel UI → Nodes → Add Node:
- Name: internal ID like `NL1`, `DE1` (must match agent config)
- Address: node domain like `nl.clawvpn.lol`
- Flag: emoji like 🇳🇱
- Label: display name

### 2. Run setup on the node server
```bash
curl -fsSL https://raw.githubusercontent.com/pqhaz3925/clawpanel/main/setup-node.sh | bash
```

### 3. Or manual setup
```bash
# Download xray-hy
curl -fsSL -o /usr/local/bin/xray-hy \
    https://github.com/pqhaz3925/clawpanel/releases/download/v2.1.0/xray-hy-linux-amd64
chmod +x /usr/local/bin/xray-hy

# Agent
mkdir -p /opt/claw-agent /etc/claw-agent /etc/claw-xray-hy
# Download agent.py to /opt/claw-agent/

# Agent env
cat > /etc/claw-agent/env << 'EOF'
PANEL_URL=https://panel.example.com
AGENT_SECRET=<from panel Settings>
NODE_NAME=NL1
XRAY_HY_BIN=/usr/local/bin/xray-hy
XRAY_HY_CFG=/etc/claw-xray-hy/config.json
XRAY_HY_SERVICE=claw-xray-hy
EOF

# Systemd services (claw-agent + claw-xray-hy)
systemctl daemon-reload
systemctl enable --now claw-xray-hy claw-agent
```

## How it works
- Agent polls panel every 60s: `GET /agent/config/{NODE_NAME}`
- Receives full xray-hy JSON config with all active users
- Writes config atomically, restarts xray-hy if changed
- Sends heartbeat with traffic stats: `POST /agent/heartbeat`

## TLS certs
Node needs TLS certs for xray-hy (VLESS + HY2 inbounds). Common locations:
- acme.sh: `/root/.acme.sh/domain_ecc/fullchain.cer` + `.key`
- Marzban: `/var/lib/marzban/certs/fullchain.pem` + `key.pem`
- Let's Encrypt: `/etc/letsencrypt/live/domain/fullchain.pem` + `privkey.pem`

The panel's cert paths (in .env) are what get written into xray-hy config.

## Ports required
| Port | Protocol | Usage |
|------|----------|-------|
| 443 | TCP | VLESS XHTTP EXIT |
| 2052 | TCP | VLESS XHTTP DIRECT |
| 53 | UDP | HY2 XDNS |
| 9053 | UDP | HY2 XICMP |

## Troubleshooting
- Agent not connecting: check `journalctl -u claw-agent -f`
- xray-hy crash loop: likely wrong cert paths, check `journalctl -u claw-xray-hy -f`
- Node shows offline in panel: check heartbeat, agent secret mismatch
- Special chars in SSH password: use paramiko instead of sshpass
