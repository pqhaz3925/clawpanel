# ClawPanel

Self-hosted VPN management panel for [Xray-core](https://github.com/XTLS/Xray-core) with router → node architecture.

Built for modern anti-censorship protocols: **VLESS XHTTP**, **Hysteria2 XDNS**, **Hysteria2 XICMP**.

---

## Features

- **Web UI** — dark glassmorphism dashboard, user/node management, subscription links
- **Router → Node** — panel generates configs, agents on nodes auto-sync every 60s
- **4 protocols per node**:
  - `:443` VLESS XHTTP EXIT (via corp exit / VLESS Reality)
  - `:2052` VLESS XHTTP DIRECT
  - `:53` Hysteria2 XDNS (finalmask)
  - `:9053` Hysteria2 XICMP (finalmask)
- **Subscriptions** — base64-encoded, compatible with V2Box / Streisand / Hiddify
- **Traffic tracking** — per-user stats via Xray Stats API, delta-based with `--reset`
- **Lightweight** — Python + FastAPI + SQLite, no Docker, no Postgres, no Node.js

## Architecture

```
┌─────────────────────────────────┐
│         ClawPanel (router)      │
│  FastAPI + SQLite + Caddy       │
│  https://panel.example.com      │
└──────────┬──────────┬───────────┘
           │  HTTPS   │
     ┌─────▼──┐  ┌────▼────┐
     │ Node 1 │  │ Node 2  │
     │ Agent  │  │ Agent   │
     │ Xray-HY│  │ Xray-HY │
     └────────┘  └─────────┘

Agent pulls config every 60s via:
  GET /agent/config/{node_name}
  POST /agent/heartbeat (traffic stats)
```

## Quick Start

### Panel (router server)

```bash
git clone https://github.com/pqhaz3925/clawpanel.git
cd clawpanel
bash install.sh
```

Edit config:
```bash
nano /opt/clawpanel/.env          # corp exit, certs, xdns domain
nano /etc/caddy/Caddyfile         # your panel domain
```

Start:
```bash
systemctl start clawpanel
systemctl reload caddy
```

Open `https://your-domain/` → login `admin` / `ClawVPN2025`

### Node (each VPN server)

```bash
# On the node server:
git clone https://github.com/pqhaz3925/clawpanel.git
cd clawpanel
bash install-agent.sh
```

Place the [xray-hy (finalmask)](https://github.com/niceDreamer/Xray-core) binary:
```bash
# Download or build xray-hy with XDNS/XICMP support
chmod +x xray-hy
mv xray-hy /usr/local/bin/
```

Configure:
```bash
nano /etc/claw-agent/env
# Set PANEL_URL, AGENT_SECRET (from panel Settings), NODE_NAME
```

Start:
```bash
systemctl start claw-xray-hy claw-agent
```

## Project Structure

```
clawpanel/
├── panel/
│   ├── main.py           # FastAPI app (routes, auth, API)
│   ├── models.py          # SQLite models (users, nodes, traffic)
│   ├── xray.py            # Xray config generator
│   ├── requirements.txt
│   ├── .env.example
│   └── templates/         # Jinja2 HTML (Tailwind CSS)
│       ├── base.html
│       ├── login.html
│       ├── dashboard.html
│       ├── users.html
│       ├── nodes.html
│       ├── settings.html
│       └── sub_info.html
├── agent/
│   ├── agent.py           # Node daemon (config sync + heartbeat)
│   └── env.example
├── deploy/
│   ├── clawpanel.service
│   ├── claw-agent.service
│   ├── claw-xray-hy.service
│   └── Caddyfile.example
├── install.sh             # Panel installer
├── install-agent.sh       # Node agent installer
└── README.md
```

## API

### Agent API (authenticated via `X-Agent-Secret` header)

| Endpoint | Method | Description |
|---|---|---|
| `/agent/config/{node}` | GET | Get xray config for node |
| `/agent/heartbeat` | POST | Send heartbeat + traffic stats |

### Subscription API

| Endpoint | Method | Description |
|---|---|---|
| `/sub/{token}` | GET | Get base64 subscription (V2Box/Streisand) |

### Panel API

| Endpoint | Method | Description |
|---|---|---|
| `/api/stats` | GET | Dashboard stats JSON |

## Environment Variables

### Panel (`/opt/clawpanel/.env`)

| Variable | Default | Description |
|---|---|---|
| `CORP_EXIT_ADDRESS` | — | Corp VLESS Reality exit server IP |
| `CORP_EXIT_PORT` | — | Corp exit port |
| `CORP_EXIT_UUID` | — | Corp exit UUID |
| `CORP_EXIT_PUBKEY` | — | Reality public key |
| `CORP_EXIT_SNI` | `yr.no` | Reality SNI |
| `CORP_EXIT_SHORT_ID` | — | Reality short ID |
| `CERT_VLESS_FULLCHAIN` | `/etc/ssl/xray/fullchain.pem` | TLS cert for VLESS |
| `CERT_HY2_FULLCHAIN` | `/etc/ssl/xray/fullchain.pem` | TLS cert for HY2 |
| `XDNS_DOMAIN` | `t.example.com` | XDNS finalmask domain |

### Agent (`/etc/claw-agent/env`)

| Variable | Default | Description |
|---|---|---|
| `PANEL_URL` | — | Panel URL (https://...) |
| `AGENT_SECRET` | — | Shared secret (from panel Settings) |
| `NODE_NAME` | — | Node name (must match panel) |
| `SYNC_INTERVAL` | `60` | Config sync interval (seconds) |

## Stack

- **Backend**: Python 3.11+ / FastAPI / aiosqlite
- **Frontend**: Jinja2 + Tailwind CSS (CDN)
- **Database**: SQLite (WAL mode)
- **Reverse proxy**: Caddy (auto HTTPS)
- **Xray**: xray-hy finalmask build (XDNS + XICMP support)

## License

MIT
