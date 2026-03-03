"""
Xray config generator for ClawPanel.

Builds full xray-core/xray-hy (finalmask) configs for nodes.
Supports: VLESS XHTTP, Hysteria2 XDNS, Hysteria2 XICMP.

Architecture:
  nginx (443/2052 TLS, fake site) → xray (10443/12052 internal, XHTTP)
  xray (53/9053 HY2 UDP, direct TLS — no nginx)
"""
import os
from typing import List, Dict
from urllib.parse import quote as _urlquote


# ---------------------------------------------------------------------------
# Corp exit outbound — configurable via env or panel settings
# ---------------------------------------------------------------------------

def _build_corp_exit_outbound() -> dict | None:
    addr = os.environ.get("CORP_EXIT_ADDRESS", "")
    port = int(os.environ.get("CORP_EXIT_PORT", "0"))
    uuid = os.environ.get("CORP_EXIT_UUID", "")
    pubkey = os.environ.get("CORP_EXIT_PUBKEY", "")
    sni = os.environ.get("CORP_EXIT_SNI", "yr.no")
    short_id = os.environ.get("CORP_EXIT_SHORT_ID", "")
    fp = os.environ.get("CORP_EXIT_FINGERPRINT", "chrome")

    if not all([addr, port, uuid, pubkey]):
        return None

    return {
        "tag": "exit-corp",
        "protocol": "vless",
        "settings": {
            "vnext": [{
                "address": addr,
                "port": port,
                "users": [{
                    "id": uuid,
                    "encryption": "none",
                    "flow": "xtls-rprx-vision"
                }]
            }]
        },
        "streamSettings": {
            "network": "raw",
            "security": "reality",
            "realitySettings": {
                "fingerprint": fp,
                "serverName": sni,
                "publicKey": pubkey,
                "shortId": short_id,
                "spiderX": "/"
            },
            "sockopt": {"tcpFastOpen": True}
        }
    }


DIRECT_OUTBOUND = {
    "tag": "DIRECT",
    "protocol": "freedom",
    "streamSettings": {
        "sockopt": {
            "tcpFastOpen": True,
            "tcpCongestion": "bbr"
        }
    }
}

BLOCK_OUTBOUND = {
    "tag": "BLOCK",
    "protocol": "blackhole"
}


# ---------------------------------------------------------------------------
# TLS certificate paths — override via env
# ---------------------------------------------------------------------------

CERT_VLESS_FULLCHAIN = os.environ.get("CERT_VLESS_FULLCHAIN", "/var/lib/marzban/certs/fullchain.pem")
CERT_VLESS_KEY = os.environ.get("CERT_VLESS_KEY", "/var/lib/marzban/certs/key.pem")
CERT_HY2_FULLCHAIN = os.environ.get("CERT_HY2_FULLCHAIN", "/var/lib/marzban/certs/fullchain.pem")
CERT_HY2_KEY = os.environ.get("CERT_HY2_KEY", "/var/lib/marzban/certs/key.pem")

XDNS_DOMAIN = os.environ.get("XDNS_DOMAIN", "t.example.com")


# ---------------------------------------------------------------------------
# Inbound builders — shared structure, no copy-paste
# ---------------------------------------------------------------------------

def _build_vless_xhttp_inbound(tag: str, port: int, clients: list,
                                xhttp_path: str = "/") -> dict:
    """Build a VLESS XHTTP inbound — behind nginx, no TLS (nginx terminates).

    nginx proxies matching path → 127.0.0.1:{port} via grpc/h2c.
    """
    return {
        "tag": tag,
        "listen": "127.0.0.1",
        "port": port,
        "protocol": "vless",
        "settings": {
            "clients": clients,
            "decryption": "none"
        },
        "streamSettings": {
            "network": "xhttp",
            "xhttpSettings": {
                "mode": "auto",
                "path": xhttp_path
            },
            "security": "none"
        },
        "sniffing": {
            "enabled": True,
            "destOverride": ["http", "tls", "quic"]
        }
    }


def _build_hy2_inbound(tag: str, port: int, clients: list, cert: dict,
                       finalmask_entry: dict) -> dict:
    """Build a Hysteria2 inbound (used for both XDNS and XICMP)."""
    return {
        "tag": tag,
        "listen": "0.0.0.0",
        "port": port,
        "protocol": "hysteria",
        "settings": {
            "version": 2,
            "clients": clients
        },
        "streamSettings": {
            "network": "hysteria",
            "security": "tls",
            "tlsSettings": {
                "certificates": [cert],
                "minVersion": "1.2",
                "alpn": ["h3"]
            },
            "hysteriaSettings": {
                "version": 2,
                "congestion": "brutal",
                "up": "1 gbps",
                "down": "1 gbps",
                "masquerade": {
                    "type": "proxy",
                    "url": "https://www.bing.com",
                    "rewriteHost": False
                }
            },
            "finalmask": {
                "udp": [finalmask_entry]
            }
        }
    }


# ---------------------------------------------------------------------------
# Main config builder
# ---------------------------------------------------------------------------

def build_xray_config(clients: List[Dict], node_address: str) -> dict:
    """
    Build full xray config for a node.

    Args:
        clients: list of {"id": uuid, "email": username}
        node_address: hostname like "nl.example.com"

    Returns:
        Complete xray JSON config dict.
    """
    vless_clients = [
        {"id": c["id"], "email": c["email"], "level": 0}
        for c in clients
    ]

    hy2_clients = [
        {"id": c["id"], "password": c["id"]}
        for c in clients
    ]

    cert_hy2 = {
        "certificateFile": CERT_HY2_FULLCHAIN,
        "keyFile": CERT_HY2_KEY
    }

    # XHTTP path — random-looking but deterministic per node
    xhttp_path = f"/{_urlquote(node_address.split('.')[0], safe='')}"

    # --- Routing rules ---
    corp_exit = _build_corp_exit_outbound()
    rules = [
        {"type": "field", "inboundTag": ["api"], "outboundTag": "api"},
        {"type": "field", "ip": ["geoip:private"], "outboundTag": "BLOCK"},
    ]

    if corp_exit:
        rules.append({
            "type": "field",
            "inboundTag": ["VLESS-XHTTP-EXIT"],
            "outboundTag": "exit-corp"
        })
        direct_inbounds = ["VLESS-XHTTP-DIRECT", "HY2-XDNS", "HY2-XICMP"]
    else:
        direct_inbounds = ["VLESS-XHTTP-EXIT", "VLESS-XHTTP-DIRECT", "HY2-XDNS", "HY2-XICMP"]

    rules.append({
        "type": "field",
        "inboundTag": direct_inbounds,
        "outboundTag": "DIRECT"
    })

    # --- Outbounds ---
    outbounds = []
    if corp_exit:
        outbounds.append(corp_exit)
    outbounds.extend([DIRECT_OUTBOUND, BLOCK_OUTBOUND])

    config = {
        "log": {"loglevel": "warning"},
        "stats": {},
        "api": {
            "tag": "api",
            "services": ["StatsService"]
        },
        "policy": {
            "levels": {
                "0": {
                    "statsUserUplink": True,
                    "statsUserDownlink": True
                }
            },
            "system": {
                "statsInboundUplink": True,
                "statsInboundDownlink": True,
                "statsOutboundUplink": True,
                "statsOutboundDownlink": True
            }
        },
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "rules": rules
        },
        "inbounds": [
            # Stats API (loopback only)
            {
                "tag": "api",
                "listen": "127.0.0.1",
                "port": 10085,
                "protocol": "dokodemo-door",
                "settings": {"address": "127.0.0.1"}
            },
            # VLESS XHTTP — behind nginx, internal ports, no TLS
            _build_vless_xhttp_inbound("VLESS-XHTTP-EXIT", 10443, vless_clients, xhttp_path),
            _build_vless_xhttp_inbound("VLESS-XHTTP-DIRECT", 12052, vless_clients, xhttp_path),
            # Hysteria2 XDNS (:53) and XICMP (:9053) — direct, own TLS
            _build_hy2_inbound("HY2-XDNS", 53, hy2_clients, cert_hy2, {
                "type": "xdns",
                "settings": {"domain": XDNS_DOMAIN}
            }),
            _build_hy2_inbound("HY2-XICMP", 9053, hy2_clients, cert_hy2, {
                "type": "xicmp",
                "settings": {"listenIp": "0.0.0.0"}
            }),
        ],
        "outbounds": outbounds
    }

    return config


# ---------------------------------------------------------------------------
# Nginx config builder — TLS termination + fake site + XHTTP proxy
# ---------------------------------------------------------------------------

NGINX_TEMPLATE = """# Auto-generated by ClawPanel — do not edit manually
# Fake website + XHTTP reverse proxy to xray-hy

server {{
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name {domain};

    ssl_certificate     {cert_fullchain};
    ssl_certificate_key {cert_key};
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 1d;

    # XHTTP proxy — exit (port 443 → internal 10443)
    location {xhttp_path} {{
        proxy_pass http://127.0.0.1:10443;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 24h;
        proxy_send_timeout 24h;
        proxy_buffering off;
    }}

    # Everything else → fake website
    location / {{
        root /var/www/fake;
        index index.html;
        try_files $uri $uri/ /index.html;
    }}
}}

server {{
    listen 2052 ssl;
    listen [::]:2052 ssl;
    http2 on;
    server_name {domain};

    ssl_certificate     {cert_fullchain};
    ssl_certificate_key {cert_key};
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    ssl_session_cache   shared:SSL2:10m;
    ssl_session_timeout 1d;

    # XHTTP proxy — direct (port 2052 → internal 12052)
    location {xhttp_path} {{
        proxy_pass http://127.0.0.1:12052;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 24h;
        proxy_send_timeout 24h;
        proxy_buffering off;
    }}

    # Everything else → fake website
    location / {{
        root /var/www/fake;
        index index.html;
        try_files $uri $uri/ /index.html;
    }}
}}
"""


def build_nginx_config(node_address: str) -> str:
    """Build nginx config for a node — TLS + fake site + XHTTP reverse proxy."""
    xhttp_path = f"/{_urlquote(node_address.split('.')[0], safe='')}"
    return NGINX_TEMPLATE.format(
        domain=node_address,
        cert_fullchain=CERT_VLESS_FULLCHAIN,
        cert_key=CERT_VLESS_KEY,
        xhttp_path=xhttp_path,
    )


FAKE_SITE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NetSphere Solutions — Cloud Infrastructure</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f8fafc;color:#334155}
.hero{background:linear-gradient(135deg,#1e3a5f 0%,#2563eb 100%);color:#fff;padding:80px 20px;text-align:center}
.hero h1{font-size:2.5rem;margin-bottom:16px}
.hero p{font-size:1.2rem;opacity:.85;max-width:600px;margin:0 auto}
.features{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:24px;max-width:960px;margin:40px auto;padding:0 20px}
.card{background:#fff;border-radius:12px;padding:32px 24px;box-shadow:0 1px 3px rgba(0,0,0,.08);text-align:center}
.card h3{margin:12px 0 8px;font-size:1.1rem}
.card p{color:#64748b;font-size:.95rem;line-height:1.5}
.icon{font-size:2.5rem}
footer{text-align:center;padding:40px 20px;color:#94a3b8;font-size:.85rem}
</style>
</head>
<body>
<div class="hero">
<h1>NetSphere Solutions</h1>
<p>Enterprise-grade cloud infrastructure and managed hosting for businesses worldwide.</p>
</div>
<div class="features">
<div class="card"><div class="icon">&#9729;&#65039;</div><h3>Cloud Hosting</h3><p>Scalable virtual machines with 99.99% uptime SLA and global edge locations.</p></div>
<div class="card"><div class="icon">&#128274;</div><h3>Security</h3><p>DDoS protection, WAF, and TLS encryption included with every plan.</p></div>
<div class="card"><div class="icon">&#9889;</div><h3>Performance</h3><p>NVMe storage, dedicated CPU cores, and low-latency networking.</p></div>
</div>
<footer>&copy; 2026 NetSphere Solutions B.V. &mdash; Amsterdam, Netherlands</footer>
</body>
</html>"""


def generate_sub_links(user_uuid: str, username: str, nodes: list,
                       enabled_protocols: str = "exit,direct,dns,icmp") -> list:
    """Generate subscription links for a user across all active nodes.

    enabled_protocols: comma-separated list of protocol keys to include.
    Valid keys: exit, direct, dns, icmp
    """
    links = []
    enabled = set(p.strip().lower() for p in enabled_protocols.split(",") if p.strip())

    for node in nodes:
        if not node.get("is_active"):
            continue

        addr = node["address"]
        flag = node.get("flag", "\U0001f30d")
        short = node.get("name", "") or node.get("label", "")
        xhttp_path = f"/{_urlquote(addr.split('.')[0], safe='')}"

        if "exit" in enabled:
            links.append(
                f"vless://{user_uuid}@{addr}:443"
                f"?encryption=none&type=xhttp&security=tls"
                f"&sni={addr}&alpn=h2,http/1.1&mode=auto"
                f"&path={_urlquote(xhttp_path, safe='')}"
                f"#{flag}\U0001f504 {short} EXIT"
            )
        if "direct" in enabled:
            links.append(
                f"vless://{user_uuid}@{addr}:2052"
                f"?encryption=none&type=xhttp&security=tls"
                f"&sni={addr}&alpn=h2,http/1.1&mode=auto"
                f"&path={_urlquote(xhttp_path, safe='')}"
                f"#{flag}\u26a1\ufe0f {short} DIRECT"
            )
        if "dns" in enabled:
            links.append(
                f"hysteria2://{user_uuid}@{addr}:53"
                f"?sni={addr}&insecure=0"
                f"#{flag}\U0001f4e1 {short} DNS"
            )
        if "icmp" in enabled:
            links.append(
                f"hysteria2://{user_uuid}@{addr}:9053"
                f"?sni={addr}&insecure=0"
                f"#{flag}\U0001f6e1\ufe0f {short} ICMP"
            )

    return links
