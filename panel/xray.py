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


def _build_socks_exit_outbound() -> dict | None:
    """Build SOCKS5 outbound for Dante proxy server."""
    addr = os.environ.get("SOCKS_EXIT_ADDRESS", "")
    port = int(os.environ.get("SOCKS_EXIT_PORT", "0"))
    user = os.environ.get("SOCKS_EXIT_USER", "")
    passwd = os.environ.get("SOCKS_EXIT_PASS", "")

    if not all([addr, port]):
        return None

    settings: dict = {
        "servers": [{
            "address": addr,
            "port": port,
        }]
    }
    if user:
        settings["servers"][0]["users"] = [{
            "user": user,
            "pass": passwd
        }]

    return {
        "tag": "exit-socks",
        "protocol": "socks",
        "settings": settings,
        "streamSettings": {
            "sockopt": {"tcpFastOpen": True}
        }
    }


def _build_socks_pk_exit_outbound() -> dict | None:
    """Build chained outbound: Pakistan corp → SOCKS5.

    Traffic flows: xray → Pakistan VLESS Reality → SOCKS5 Dante server.
    Uses proxySettings to chain through exit-corp.
    """
    socks_ob = _build_socks_exit_outbound()
    corp_ob = _build_corp_exit_outbound()
    if not socks_ob or not corp_ob:
        return None

    addr = os.environ.get("SOCKS_EXIT_ADDRESS", "")
    port = int(os.environ.get("SOCKS_EXIT_PORT", "0"))
    user = os.environ.get("SOCKS_EXIT_USER", "")
    passwd = os.environ.get("SOCKS_EXIT_PASS", "")

    settings: dict = {
        "servers": [{
            "address": addr,
            "port": port,
        }]
    }
    if user:
        settings["servers"][0]["users"] = [{
            "user": user,
            "pass": passwd
        }]

    return {
        "tag": "exit-socks-pk",
        "protocol": "socks",
        "settings": settings,
        "proxySettings": {
            "tag": "exit-corp"
        },
        "streamSettings": {
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

# Feature flag — H3 inbounds require xray-hy with XHTTP H3 support (post v26.2.6)
ENABLE_XHTTP_H3 = os.environ.get("ENABLE_XHTTP_H3", "").lower() in ("1", "true", "yes")

# Stealth mode — full cookie-based XHTTP + sudoku mask (requires custom client)
ENABLE_STEALTH = os.environ.get("ENABLE_STEALTH", "").lower() in ("1", "true", "yes")
SUDOKU_PASSWORD = os.environ.get("SUDOKU_PASSWORD", "clawstealth2026")

# Scrape SOCKS proxy — exposed on each node for external scrapers
SCRAPE_SOCKS_PORT = int(os.environ.get("SCRAPE_SOCKS_PORT", "0"))
SCRAPE_SOCKS_USER = os.environ.get("SCRAPE_SOCKS_USER", "")
SCRAPE_SOCKS_PASS = os.environ.get("SCRAPE_SOCKS_PASS", "")


# ---------------------------------------------------------------------------
# Inbound builders — shared structure, no copy-paste
# ---------------------------------------------------------------------------

def _build_vless_xhttp_inbound(tag: str, port: int, clients: list,
                                xhttp_path: str = "/") -> dict:
    """Build a VLESS XHTTP inbound — behind nginx, no TLS (nginx terminates).

    nginx proxies matching path → 127.0.0.1:{port} via grpc/h2c.
    noGRPCHeader/noSSEHeader remove known proxy fingerprints from responses.
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
                "path": xhttp_path,
                "noGRPCHeader": True,
                "noSSEHeader": True
            },
            "security": "none"
        },
        "sniffing": {
            "enabled": True,
            "destOverride": ["http", "tls", "quic"]
        }
    }


def _build_vless_xhttp_stealth_inbound(tag: str, port: int, clients: list,
                                        xhttp_path: str = "/") -> dict:
    """Build a VLESS XHTTP stealth inbound — full cookie placement + sudoku mask.

    Everything goes into cookies: session ID, sequence numbers, uplink data, padding.
    This makes the HTTP traffic look like normal website requests with auth cookies.
    Sudoku mask on TCP makes the wire bytes look like printable ASCII text.

    Requires custom xray-hy client (standard V2Box/Streisand won't work).
    Listens behind nginx (no TLS, nginx terminates).
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
                "mode": "packet-up",
                "path": xhttp_path,
                # --- Full cookie placement ---
                "sessionPlacement": "cookie",
                "sessionKey": "cf_session",
                "seqPlacement": "cookie",
                "seqKey": "cf_seq",
                "uplinkDataPlacement": "cookie",
                "uplinkDataKey": "cf_data",
                # --- Anti-fingerprint ---
                "noGRPCHeader": True,
                "noSSEHeader": True,
                "xPaddingObfsMode": True,
                "xPaddingMethod": "tokenish",
                "xPaddingPlacement": "cookie",
                "xPaddingKey": "cf_token"
            },
            "security": "none"
        },
        "sniffing": {
            "enabled": True,
            "destOverride": ["http", "tls", "quic"]
        }
    }


def _build_vless_xhttp_h3_inbound(tag: str, port: int, clients: list,
                                   cert: dict, xhttp_path: str = "/") -> dict:
    """Build a VLESS XHTTP H3 inbound — direct QUIC/UDP, no nginx.

    HTTP/3 over QUIC is immune to TCP RST injection by TSPU.
    xray handles TLS+QUIC itself; listens on UDP port directly.
    """
    return {
        "tag": tag,
        "listen": "0.0.0.0",
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
                "path": xhttp_path,
                "noGRPCHeader": True,
                "noSSEHeader": True
            },
            "security": "tls",
            "tlsSettings": {
                "certificates": [cert],
                "minVersion": "1.3",
                "alpn": ["h3"]
            }
        },
        "sniffing": {
            "enabled": True,
            "destOverride": ["http", "tls", "quic"]
        }
    }


def _build_vless_xhttp_h3_stealth_inbound(tag: str, port: int, clients: list,
                                            cert: dict, xhttp_path: str = "/") -> dict:
    """Build a VLESS XHTTP H3 stealth inbound — QUIC + full cookie + sudoku.

    Combines: HTTP/3 over QUIC (immune to TCP RST) + full cookie placement.
    Direct UDP port, xray handles TLS+QUIC itself.
    """
    return {
        "tag": tag,
        "listen": "0.0.0.0",
        "port": port,
        "protocol": "vless",
        "settings": {
            "clients": clients,
            "decryption": "none"
        },
        "streamSettings": {
            "network": "xhttp",
            "xhttpSettings": {
                "mode": "packet-up",
                "path": xhttp_path,
                "sessionPlacement": "cookie",
                "sessionKey": "cf_session",
                "seqPlacement": "cookie",
                "seqKey": "cf_seq",
                "uplinkDataPlacement": "cookie",
                "uplinkDataKey": "cf_data",
                "noGRPCHeader": True,
                "noSSEHeader": True,
                "xPaddingObfsMode": True,
                "xPaddingMethod": "tokenish",
                "xPaddingPlacement": "cookie",
                "xPaddingKey": "cf_token"
            },
            "security": "tls",
            "tlsSettings": {
                "certificates": [cert],
                "minVersion": "1.3",
                "alpn": ["h3"]
            }
        },
        "sniffing": {
            "enabled": True,
            "destOverride": ["http", "tls", "quic"]
        }
    }


def _build_hy2_inbound(tag: str, port: int, clients: list, cert: dict,
                       finalmask_entry: dict, masquerade_domain: str = "",
                       inner_udp_masks: list | None = None) -> dict:
    """Build a Hysteria2 inbound (used for both XDNS and XICMP).

    masquerade_domain: domain for active probing response (should match node's own domain
    so IP↔domain consistency is maintained for TSPU checks).
    inner_udp_masks: additional finalmask UDP entries (e.g. noise) that go INSIDE
    the main mask. xdns/xicmp must be outermost (index 0, level 0), noise goes after.
    Array order: [outermost_protocol_mask, inner_masks...]
    """
    masq_url = f"https://{masquerade_domain}" if masquerade_domain else "https://www.bing.com"
    # Protocol mask (xdns/xicmp) is outermost — FIRST in the array (level 0)
    udp_masks = [finalmask_entry] + list(inner_udp_masks or [])
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
                    "url": masq_url,
                    "rewriteHost": False
                }
            },
            "finalmask": {
                "udp": udp_masks
            }
        }
    }


# ---------------------------------------------------------------------------
# Main config builder
# ---------------------------------------------------------------------------

def build_xray_config(clients: List[Dict], node_address: str,
                      xhttp_path: str = "") -> dict:
    """
    Build full xray config for a node.

    Args:
        clients: list of {"id": uuid, "email": username}
        node_address: hostname like "nl2.service-toolbox.ru"
        xhttp_path: custom XHTTP path (e.g. "/a8f3k2"), falls back to /{subdomain}

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

    # XHTTP path — use custom if provided, otherwise derive from subdomain
    if not xhttp_path:
        xhttp_path = f"/{_urlquote(node_address.split('.')[0], safe='')}"

    # --- Routing rules ---
    corp_exit = _build_corp_exit_outbound()
    socks_exit = _build_socks_exit_outbound()
    socks_pk_exit = _build_socks_pk_exit_outbound()
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

    if socks_exit:
        rules.append({
            "type": "field",
            "inboundTag": ["VLESS-XHTTP-SOCKS"],
            "outboundTag": "exit-socks"
        })

    if socks_pk_exit:
        rules.append({
            "type": "field",
            "inboundTag": ["VLESS-XHTTP-SOCKS-PK"],
            "outboundTag": "exit-socks-pk"
        })

    # XHTTP H3 routing — only if H3 is enabled (needs xray-hy with H3 support)
    if ENABLE_XHTTP_H3 and corp_exit:
        rules.append({
            "type": "field",
            "inboundTag": ["VLESS-XHTTP-H3-EXIT"],
            "outboundTag": "exit-corp"
        })

    # Stealth routing — cookie-based XHTTP for custom clients
    if ENABLE_STEALTH and corp_exit:
        rules.append({
            "type": "field",
            "inboundTag": ["VLESS-STEALTH-EXIT"],
            "outboundTag": "exit-corp"
        })
    if ENABLE_STEALTH and ENABLE_XHTTP_H3 and corp_exit:
        rules.append({
            "type": "field",
            "inboundTag": ["VLESS-STEALTH-H3-EXIT"],
            "outboundTag": "exit-corp"
        })

    direct_inbounds = ["VLESS-XHTTP-DIRECT", "HY2-XDNS", "HY2-XICMP"]
    if SCRAPE_SOCKS_PORT and SCRAPE_SOCKS_USER:
        direct_inbounds.append("SOCKS-SCRAPE")
    if ENABLE_XHTTP_H3:
        direct_inbounds.append("VLESS-XHTTP-H3-DIRECT")
    if ENABLE_STEALTH:
        direct_inbounds.append("VLESS-STEALTH-DIRECT")
    if ENABLE_STEALTH and ENABLE_XHTTP_H3:
        direct_inbounds.append("VLESS-STEALTH-H3-DIRECT")
    if not corp_exit:
        direct_inbounds.append("VLESS-XHTTP-EXIT")
        if ENABLE_XHTTP_H3:
            direct_inbounds.append("VLESS-XHTTP-H3-EXIT")
    if not socks_exit:
        direct_inbounds.append("VLESS-XHTTP-SOCKS")
    if not socks_pk_exit:
        direct_inbounds.append("VLESS-XHTTP-SOCKS-PK")

    rules.append({
        "type": "field",
        "inboundTag": direct_inbounds,
        "outboundTag": "DIRECT"
    })

    # --- Outbounds ---
    outbounds = []
    if corp_exit:
        outbounds.append(corp_exit)
    if socks_exit:
        outbounds.append(socks_exit)
    if socks_pk_exit:
        outbounds.append(socks_pk_exit)
    outbounds.extend([DIRECT_OUTBOUND, BLOCK_OUTBOUND])

    # HY2 masquerade uses direct (non-CDN) domain so IP matches A record
    hy_masq_domain = _hy_direct_addr(node_address)

    # Cert for H3/HY2 — xray handles TLS directly
    cert_h3 = {
        "certificateFile": CERT_HY2_FULLCHAIN,
        "keyFile": CERT_HY2_KEY
    }

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
        "inbounds": [],   # populated below
        "outbounds": outbounds
    }

    # --- Build inbounds list ---
    inbounds = [
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
        # VLESS XHTTP — SOCKS exits (ports 10444 direct, 10445 via PK)
        _build_vless_xhttp_inbound("VLESS-XHTTP-SOCKS", 10444, vless_clients, xhttp_path),
        _build_vless_xhttp_inbound("VLESS-XHTTP-SOCKS-PK", 10445, vless_clients, xhttp_path),
    ]

    # VLESS XHTTP H3 — direct QUIC/UDP, no nginx (immune to TCP RST)
    # Only enabled with ENABLE_XHTTP_H3=1 — needs xray-hy with H3 support
    if ENABLE_XHTTP_H3:
        inbounds.extend([
            _build_vless_xhttp_h3_inbound("VLESS-XHTTP-H3-EXIT", 8443, vless_clients, cert_h3, xhttp_path),
            _build_vless_xhttp_h3_inbound("VLESS-XHTTP-H3-DIRECT", 8444, vless_clients, cert_h3, xhttp_path),
        ])

    # Hysteria2 XDNS (:53) and XICMP (:9053) — direct, own TLS
    # Noise mask adds random padding packets to confuse traffic analysis
    # IMPORTANT: xdns/xicmp must be OUTERMOST mask (they handle raw protocol)
    # noise must be INNER (prepended before the protocol mask)
    hy2_noise = {
        "type": "noise",
        "settings": {
            "reset": "30-80",
            "noise": [
                {"rand": "10-40", "delay": "0-5"},
                {"rand": "20-60", "delay": "5-15"}
            ]
        }
    }
    inbounds.extend([
        _build_hy2_inbound("HY2-XDNS", 53, hy2_clients, cert_hy2, {
            "type": "xdns",
            "settings": {"domain": XDNS_DOMAIN}
        }, masquerade_domain=hy_masq_domain, inner_udp_masks=[hy2_noise]),
        _build_hy2_inbound("HY2-XICMP", 9053, hy2_clients, cert_hy2, {
            "type": "xicmp",
            "settings": {"listenIp": "0.0.0.0"}
        }, masquerade_domain=hy_masq_domain, inner_udp_masks=[hy2_noise]),
    ])

    # --- Stealth inbounds (full cookie mode, custom client only) ---
    # Uses separate internal ports: 10446 (exit), 10447 (direct)
    # Behind nginx on ports 4443 (exit), 4444 (direct)
    if ENABLE_STEALTH:
        stealth_path = xhttp_path + "s"   # e.g. /nl2s
        inbounds.extend([
            _build_vless_xhttp_stealth_inbound("VLESS-STEALTH-EXIT", 10446,
                                               vless_clients, stealth_path),
            _build_vless_xhttp_stealth_inbound("VLESS-STEALTH-DIRECT", 10447,
                                               vless_clients, stealth_path),
        ])
        # Stealth H3 (QUIC + full cookie) — ports 8445/8446
        if ENABLE_XHTTP_H3:
            inbounds.extend([
                _build_vless_xhttp_h3_stealth_inbound("VLESS-STEALTH-H3-EXIT", 8445,
                                                       vless_clients, cert_h3, stealth_path),
                _build_vless_xhttp_h3_stealth_inbound("VLESS-STEALTH-H3-DIRECT", 8446,
                                                       vless_clients, cert_h3, stealth_path),
            ])

    # --- Scrape SOCKS5 proxy — direct exit from node IP ---
    if SCRAPE_SOCKS_PORT and SCRAPE_SOCKS_USER:
        inbounds.append({
            "tag": "SOCKS-SCRAPE",
            "listen": "0.0.0.0",
            "port": SCRAPE_SOCKS_PORT,
            "protocol": "socks",
            "settings": {
                "auth": "password",
                "accounts": [
                    {"user": SCRAPE_SOCKS_USER, "pass": SCRAPE_SOCKS_PASS}
                ],
                "udp": False
            }
        })

    config["inbounds"] = inbounds

    return config


# ---------------------------------------------------------------------------
# Nginx config builder — TLS termination + fake site + XHTTP proxy
# ---------------------------------------------------------------------------

NGINX_TEMPLATE = """# Auto-generated by ClawPanel — do not edit manually
# Fake website + XHTTP reverse proxy to xray-hy
# Uses listen ... http2 syntax for nginx 1.24+ compat

server {{
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name {server_names};

    ssl_certificate     {cert_fullchain};
    ssl_certificate_key {cert_key};
    ssl_protocols       TLSv1.3;
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
    listen 2053 ssl http2;
    listen [::]:2053 ssl http2;
    server_name {server_names};

    ssl_certificate     {cert_fullchain};
    ssl_certificate_key {cert_key};
    ssl_protocols       TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    ssl_session_cache   shared:SSL2:10m;
    ssl_session_timeout 1d;

    # XHTTP proxy — direct (port 2053 → internal 12052)
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

server {{
    listen 2054 ssl http2;
    listen [::]:2054 ssl http2;
    server_name {server_names};

    ssl_certificate     {cert_fullchain};
    ssl_certificate_key {cert_key};
    ssl_protocols       TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    ssl_session_cache   shared:SSL3:10m;
    ssl_session_timeout 1d;

    # XHTTP proxy — SOCKS exit (port 2054 → internal 10444)
    location {xhttp_path} {{
        proxy_pass http://127.0.0.1:10444;
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
    listen 2055 ssl http2;
    listen [::]:2055 ssl http2;
    server_name {server_names};

    ssl_certificate     {cert_fullchain};
    ssl_certificate_key {cert_key};
    ssl_protocols       TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    ssl_session_cache   shared:SSL4:10m;
    ssl_session_timeout 1d;

    # XHTTP proxy — SOCKS via Pakistan (port 2055 → internal 10445)
    location {xhttp_path} {{
        proxy_pass http://127.0.0.1:10445;
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

NGINX_STEALTH_TEMPLATE = """
# --- ClawStealth: full cookie-mode XHTTP (custom client only) ---

server {{
    listen 4443 ssl http2;
    listen [::]:4443 ssl http2;
    server_name {server_names};

    ssl_certificate     {cert_fullchain};
    ssl_certificate_key {cert_key};
    ssl_protocols       TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    ssl_session_cache   shared:SSL_S1:10m;
    ssl_session_timeout 1d;

    # Stealth XHTTP EXIT (port 4443 → internal 10446)
    location {stealth_path} {{
        proxy_pass http://127.0.0.1:10446;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Cookie $http_cookie;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 24h;
        proxy_send_timeout 24h;
        proxy_buffering off;
    }}

    location / {{
        root /var/www/fake;
        index index.html;
        try_files $uri $uri/ /index.html;
    }}
}}

server {{
    listen 4444 ssl http2;
    listen [::]:4444 ssl http2;
    server_name {server_names};

    ssl_certificate     {cert_fullchain};
    ssl_certificate_key {cert_key};
    ssl_protocols       TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    ssl_session_cache   shared:SSL_S2:10m;
    ssl_session_timeout 1d;

    # Stealth XHTTP DIRECT (port 4444 → internal 10447)
    location {stealth_path} {{
        proxy_pass http://127.0.0.1:10447;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Cookie $http_cookie;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 24h;
        proxy_send_timeout 24h;
        proxy_buffering off;
    }}

    location / {{
        root /var/www/fake;
        index index.html;
        try_files $uri $uri/ /index.html;
    }}
}}
"""


def build_nginx_config(node_address: str, xhttp_path: str = "") -> str:
    """Build nginx config for a node — TLS + fake site + XHTTP reverse proxy.

    node_address: primary domain (e.g. nl2.service-toolbox.ru)
    xhttp_path: custom path, falls back to /{subdomain}
    """
    if not xhttp_path:
        xhttp_path = f"/{_urlquote(node_address.split('.')[0], safe='')}"

    # Accept both .service-toolbox.ru and .clawvpn.lol for backward compat
    subdomain = node_address.split('.')[0]
    server_names = f"{subdomain}.service-toolbox.ru {subdomain}.clawvpn.lol"

    result = NGINX_TEMPLATE.format(
        server_names=server_names,
        cert_fullchain=CERT_VLESS_FULLCHAIN,
        cert_key=CERT_VLESS_KEY,
        xhttp_path=xhttp_path,
    )

    # Append stealth server blocks if enabled
    if ENABLE_STEALTH:
        stealth_path = xhttp_path + "s"   # e.g. /nl2s
        result += NGINX_STEALTH_TEMPLATE.format(
            server_names=server_names,
            cert_fullchain=CERT_VLESS_FULLCHAIN,
            cert_key=CERT_VLESS_KEY,
            stealth_path=stealth_path,
        )

    return result


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


def _hy_direct_addr(addr: str) -> str:
    """Derive direct (non-CDN) hostname for HY2 from node address.

    nl2.service-toolbox.ru → hy-nl2.service-toolbox.ru
    HY2 uses QUIC/UDP which can't go through Cloudflare CDN,
    so it needs a separate DNS record pointing directly to the node IP.
    """
    parts = addr.split(".", 1)
    if len(parts) == 2:
        return f"hy-{parts[0]}.{parts[1]}"
    return addr


def _client_xhttp_stream(addr: str, xhttp_path: str,
                          alpn: list | None = None) -> dict:
    """Build client-side XHTTP streamSettings with anti-fingerprint.

    Includes:
    - packet-up mode (explicit, best for nginx proxy)
    - tokenish padding in cookies (looks like auth tokens, not XXXX)
    - xmux tuned for mobile (fast dead-conn detection, short reuse)
    - TLS ClientHello fragmentation (defeats SNI-based DPI)
    """
    if alpn is None:
        alpn = ["h2", "http/1.1"]
    return {
        "network": "xhttp",
        "xhttpSettings": {
            "mode": "packet-up",
            "path": xhttp_path,
            "xPaddingObfsMode": True,
            "xPaddingMethod": "tokenish",
            "xPaddingPlacement": "cookie",
            "xPaddingKey": "x_pad",
            "noGRPCHeader": True,
            "noSSEHeader": True,
            "xmux": {
                "maxConcurrency": {"from": 1, "to": 1},
                "hMaxRequestTimes": {"from": 100, "to": 200},
                "hMaxReusableSecs": {"from": 60, "to": 180},
                "hKeepAlivePeriod": 15
            }
        },
        "security": "tls",
        "tlsSettings": {
            "serverName": addr,
            "fingerprint": "chrome",
            "alpn": alpn
        },
        "finalmask": {
            "tcp": [{
                "type": "fragment",
                "length": {"from": 1, "to": 1},
                "interval": {"from": 10, "to": 20}
            }]
        }
    }


def _client_xhttp_stealth_stream(addr: str, xhttp_path: str,
                                   alpn: list | None = None,
                                   use_sudoku: bool = False) -> dict:
    """Build stealth client-side XHTTP streamSettings — maximum obfuscation.

    Requires custom xray-hy client (Hiddify/Streisand custom build).
    Standard V2Box/Streisand from App Store won't support this.

    Adds on top of standard stream:
    - sessionPlacement: cookie — session UUID hidden in cookie
    - seqPlacement: cookie — packet sequence hidden in cookie
    - uplinkDataPlacement: cookie — actual VPN data hidden in cookies
    - Fragment — TLS ClientHello fragmentation
    - Cookie names mimic Cloudflare (cf_session, cf_data, cf_token)
    - Sudoku TCP mask (ONLY for H3/direct connections, NOT behind nginx!)

    For TSPU/DPI this looks like normal HTTPS browsing with auth cookies.

    Args:
        use_sudoku: Enable sudoku mask. Only for H3 (xray handles TLS).
                    NEVER for nginx-proxied (sudoku mangles TLS, nginx can't parse).
    """
    if alpn is None:
        alpn = ["h2", "http/1.1"]

    tcp_masks = [
        {
            "type": "fragment",
            "length": {"from": 1, "to": 1},
            "interval": {"from": 10, "to": 20}
        }
    ]
    if use_sudoku:
        # Sudoku goes BEFORE fragment in the chain (innermost mask)
        tcp_masks.insert(0, {
            "type": "sudoku",
            "settings": {
                "password": SUDOKU_PASSWORD,
                "ascii": "prefer_ascii"
            }
        })

    return {
        "network": "xhttp",
        "xhttpSettings": {
            "mode": "packet-up",
            "path": xhttp_path,
            # --- Full cookie placement (matches server inbound) ---
            "sessionPlacement": "cookie",
            "sessionKey": "cf_session",
            "seqPlacement": "cookie",
            "seqKey": "cf_seq",
            "uplinkDataPlacement": "cookie",
            "uplinkDataKey": "cf_data",
            # --- Anti-fingerprint ---
            "xPaddingObfsMode": True,
            "xPaddingMethod": "tokenish",
            "xPaddingPlacement": "cookie",
            "xPaddingKey": "cf_token",
            "noGRPCHeader": True,
            "noSSEHeader": True,
            # --- xmux for mobile stability ---
            "xmux": {
                "maxConcurrency": {"from": 1, "to": 1},
                "hMaxRequestTimes": {"from": 100, "to": 200},
                "hMaxReusableSecs": {"from": 60, "to": 180},
                "hKeepAlivePeriod": 15
            }
        },
        "security": "tls",
        "tlsSettings": {
            "serverName": addr,
            "fingerprint": "chrome",
            "alpn": alpn
        },
        "finalmask": {
            "tcp": tcp_masks
        }
    }


def generate_amnezia_config(user_uuid: str, username: str, nodes: list,
                            enabled_protocols: str = "exit,direct,dns,icmp") -> dict:
    """Generate full xray-hy client JSON config for AmneziaVPN.

    Includes all outbounds with observatory + routing fallback:
      XHTTP EXIT/DIRECT (standard VLESS links) — with anti-fingerprint
      XHTTP H3 EXIT/DIRECT (QUIC, immune to TCP RST) — optional
      HY2 XDNS (finalmask DNS tunnel) — needs AmneziaVPN or xray-hy client
      HY2 XICMP (finalmask ICMP tunnel) — needs AmneziaVPN or xray-hy client

    Returns a complete xray JSON config dict ready for import into AmneziaVPN.
    """
    enabled = set(p.strip().lower() for p in enabled_protocols.split(",") if p.strip())
    outbounds = []

    for node in nodes:
        if not node.get("is_active"):
            continue

        addr = node["address"]
        hy_addr = _hy_direct_addr(addr)
        short = node.get("name", "") or node.get("label", "")
        xhttp_path = node.get("xhttp_path", "") or f"/{_urlquote(addr.split('.')[0], safe='')}"

        # VLESS XHTTP EXIT (nginx TLS, H2)
        if "exit" in enabled:
            outbounds.append({
                "tag": f"{short}-EXIT",
                "protocol": "vless",
                "settings": {
                    "vnext": [{
                        "address": addr,
                        "port": 443,
                        "users": [{"id": user_uuid, "encryption": "none"}]
                    }]
                },
                "streamSettings": _client_xhttp_stream(addr, xhttp_path)
            })

        # VLESS XHTTP DIRECT (nginx TLS, H2)
        if "direct" in enabled:
            outbounds.append({
                "tag": f"{short}-DIRECT",
                "protocol": "vless",
                "settings": {
                    "vnext": [{
                        "address": addr,
                        "port": 2053,
                        "users": [{"id": user_uuid, "encryption": "none"}]
                    }]
                },
                "streamSettings": _client_xhttp_stream(addr, xhttp_path)
            })

        # VLESS XHTTP SOCKS (nginx TLS, H2)
        if "socks" in enabled:
            outbounds.append({
                "tag": f"{short}-SOCKS",
                "protocol": "vless",
                "settings": {
                    "vnext": [{
                        "address": addr,
                        "port": 2054,
                        "users": [{"id": user_uuid, "encryption": "none"}]
                    }]
                },
                "streamSettings": _client_xhttp_stream(addr, xhttp_path)
            })

        # VLESS XHTTP SOCKS-PK (nginx TLS, H2)
        if "socks-pk" in enabled:
            outbounds.append({
                "tag": f"{short}-SOCKS-PK",
                "protocol": "vless",
                "settings": {
                    "vnext": [{
                        "address": addr,
                        "port": 2055,
                        "users": [{"id": user_uuid, "encryption": "none"}]
                    }]
                },
                "streamSettings": _client_xhttp_stream(addr, xhttp_path)
            })

        # VLESS XHTTP H3 EXIT (QUIC/UDP, no nginx — immune to TCP RST)
        if "h3-exit" in enabled:
            outbounds.append({
                "tag": f"{short}-H3-EXIT",
                "protocol": "vless",
                "settings": {
                    "vnext": [{
                        "address": addr,
                        "port": 8443,
                        "users": [{"id": user_uuid, "encryption": "none"}]
                    }]
                },
                "streamSettings": _client_xhttp_stream(addr, xhttp_path, alpn=["h3"])
            })

        # VLESS XHTTP H3 DIRECT (QUIC/UDP, no nginx)
        if "h3-direct" in enabled:
            outbounds.append({
                "tag": f"{short}-H3-DIRECT",
                "protocol": "vless",
                "settings": {
                    "vnext": [{
                        "address": addr,
                        "port": 8444,
                        "users": [{"id": user_uuid, "encryption": "none"}]
                    }]
                },
                "streamSettings": _client_xhttp_stream(addr, xhttp_path, alpn=["h3"])
            })

        # --- ClawStealth: full cookie mode (custom client only) ---
        stealth_path = xhttp_path + "s"   # e.g. /nl2s

        # Stealth EXIT (nginx TLS, cookie-based XHTTP)
        if "stealth-exit" in enabled:
            outbounds.append({
                "tag": f"{short}-S-EXIT",
                "protocol": "vless",
                "settings": {
                    "vnext": [{
                        "address": addr,
                        "port": 4443,
                        "users": [{"id": user_uuid, "encryption": "none"}]
                    }]
                },
                "streamSettings": _client_xhttp_stealth_stream(
                    addr, stealth_path, use_sudoku=False)
            })

        # Stealth DIRECT (nginx TLS, cookie-based XHTTP)
        if "stealth-direct" in enabled:
            outbounds.append({
                "tag": f"{short}-S-DIRECT",
                "protocol": "vless",
                "settings": {
                    "vnext": [{
                        "address": addr,
                        "port": 4444,
                        "users": [{"id": user_uuid, "encryption": "none"}]
                    }]
                },
                "streamSettings": _client_xhttp_stealth_stream(
                    addr, stealth_path, use_sudoku=False)
            })

        # Stealth H3 EXIT (QUIC + cookie, immune to TCP RST)
        if "stealth-h3-exit" in enabled:
            outbounds.append({
                "tag": f"{short}-SH3-EXIT",
                "protocol": "vless",
                "settings": {
                    "vnext": [{
                        "address": addr,
                        "port": 8445,
                        "users": [{"id": user_uuid, "encryption": "none"}]
                    }]
                },
                "streamSettings": _client_xhttp_stealth_stream(
                    addr, stealth_path, alpn=["h3"], use_sudoku=False)
            })

        # Stealth H3 DIRECT (QUIC + cookie)
        if "stealth-h3-direct" in enabled:
            outbounds.append({
                "tag": f"{short}-SH3-DIRECT",
                "protocol": "vless",
                "settings": {
                    "vnext": [{
                        "address": addr,
                        "port": 8446,
                        "users": [{"id": user_uuid, "encryption": "none"}]
                    }]
                },
                "streamSettings": _client_xhttp_stealth_stream(
                    addr, stealth_path, alpn=["h3"], use_sudoku=False)
            })

        # HY2 XDNS (finalmask DNS tunnel)
        if "dns" in enabled:
            outbounds.append({
                "tag": f"{short}-DNS",
                "protocol": "hysteria",
                "settings": {
                    "version": 2,
                    "address": hy_addr,
                    "port": 53
                },
                "streamSettings": {
                    "network": "hysteria",
                    "security": "tls",
                    "tlsSettings": {
                        "serverName": hy_addr,
                        "fingerprint": "chrome",
                        "alpn": ["h3"]
                    },
                    "hysteriaSettings": {
                        "version": 2,
                        "auth": user_uuid,
                        "up": "100 mbps",
                        "down": "100 mbps"
                    },
                    "finalmask": {
                        "udp": [
                            {
                                "type": "xdns",
                                "settings": {"domain": XDNS_DOMAIN}
                            },
                            {
                                "type": "noise",
                                "settings": {
                                    "reset": "30-80",
                                    "noise": [
                                        {"rand": "10-40", "delay": "0-5"},
                                        {"rand": "20-60", "delay": "5-15"}
                                    ]
                                }
                            }
                        ]
                    }
                }
            })

        # HY2 XICMP (finalmask ICMP tunnel)
        if "icmp" in enabled:
            outbounds.append({
                "tag": f"{short}-ICMP",
                "protocol": "hysteria",
                "settings": {
                    "version": 2,
                    "address": hy_addr,
                    "port": 9053
                },
                "streamSettings": {
                    "network": "hysteria",
                    "security": "tls",
                    "tlsSettings": {
                        "serverName": hy_addr,
                        "fingerprint": "chrome",
                        "alpn": ["h3"]
                    },
                    "hysteriaSettings": {
                        "version": 2,
                        "auth": user_uuid,
                        "up": "100 mbps",
                        "down": "100 mbps"
                    },
                    "finalmask": {
                        "udp": [
                            {
                                "type": "xicmp",
                                "settings": {}
                            },
                            {
                                "type": "noise",
                                "settings": {
                                    "reset": "30-80",
                                    "noise": [
                                        {"rand": "10-40", "delay": "0-5"},
                                        {"rand": "20-60", "delay": "5-15"}
                                    ]
                                }
                            }
                        ]
                    }
                }
            })

    # Add direct + block outbounds
    outbounds.extend([
        {"tag": "direct", "protocol": "freedom"},
        {"tag": "block", "protocol": "blackhole"}
    ])

    # Collect all proxy tags for observatory
    proxy_tags = [o["tag"] for o in outbounds if o["tag"] not in ("direct", "block")]

    config = {
        "log": {"loglevel": "warning"},
        "dns": {
            "servers": [
                {"address": "https://1.1.1.1/dns-query", "domains": ["geosite:geolocation-!cn"]},
                {"address": "localhost", "domains": ["geosite:cn"]}
            ]
        },
        "observatory": {
            "subjectSelector": proxy_tags,
            "probeURL": "https://www.google.com/generate_204",
            "probeInterval": "30s",
            "enableConcurrency": True
        },
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "balancers": [{
                "tag": "auto",
                "selector": proxy_tags,
                "strategy": {"type": "leastping"},
                "fallbackTag": proxy_tags[0] if proxy_tags else "direct"
            }],
            "rules": [
                {"type": "field", "domain": ["geosite:category-ads-all"], "outboundTag": "block"},
                {"type": "field", "domain": ["geosite:cn"], "outboundTag": "direct"},
                {"type": "field", "ip": ["geoip:cn", "geoip:private"], "outboundTag": "direct"},
                {"type": "field", "network": "tcp,udp", "balancerTag": "auto"}
            ]
        },
        "inbounds": [{
            "tag": "socks",
            "listen": "127.0.0.1",
            "port": 10808,
            "protocol": "socks",
            "settings": {"udp": True}
        }, {
            "tag": "http",
            "listen": "127.0.0.1",
            "port": 10809,
            "protocol": "http"
        }],
        "outbounds": outbounds
    }

    return config


def generate_sub_links(user_uuid: str, username: str, nodes: list,
                       enabled_protocols: str = "exit,direct,dns,icmp") -> list:
    """Generate subscription links for a user across all active nodes.

    enabled_protocols: comma-separated list of protocol keys to include.
    Valid keys: exit, direct, dns, icmp, h3-exit, h3-direct, socks, socks-pk

    XHTTP uses packet-up mode for better mobile stability.
    H3 links use QUIC/UDP (immune to TCP RST injection).
    """
    links = []
    enabled = set(p.strip().lower() for p in enabled_protocols.split(",") if p.strip())

    for node in nodes:
        if not node.get("is_active"):
            continue

        addr = node["address"]                # e.g. nl2.service-toolbox.ru
        hy_addr = _hy_direct_addr(addr)       # e.g. hy-nl2.service-toolbox.ru
        flag = node.get("flag", "\U0001f30d")
        short = node.get("name", "") or node.get("label", "")
        # Use custom xhttp_path from DB, fall back to /{subdomain}
        xhttp_path = node.get("xhttp_path", "") or f"/{_urlquote(addr.split('.')[0], safe='')}"

        if "exit" in enabled:
            links.append(
                f"vless://{user_uuid}@{addr}:443"
                f"?encryption=none&type=xhttp&security=tls"
                f"&sni={addr}&alpn=h2,http/1.1&fp=chrome&mode=packet-up"
                f"&path={_urlquote(xhttp_path, safe='')}"
                f"#{flag}\U0001f504 {short} EXIT"
            )
        if "direct" in enabled:
            links.append(
                f"vless://{user_uuid}@{addr}:2053"
                f"?encryption=none&type=xhttp&security=tls"
                f"&sni={addr}&alpn=h2,http/1.1&fp=chrome&mode=packet-up"
                f"&path={_urlquote(xhttp_path, safe='')}"
                f"#{flag}\u26a1\ufe0f {short} DIRECT"
            )
        if "socks" in enabled:
            links.append(
                f"vless://{user_uuid}@{addr}:2054"
                f"?encryption=none&type=xhttp&security=tls"
                f"&sni={addr}&alpn=h2,http/1.1&fp=chrome&mode=packet-up"
                f"&path={_urlquote(xhttp_path, safe='')}"
                f"#{flag}\U0001f9e6 {short} SOCKS"
            )
        if "socks-pk" in enabled:
            links.append(
                f"vless://{user_uuid}@{addr}:2055"
                f"?encryption=none&type=xhttp&security=tls"
                f"&sni={addr}&alpn=h2,http/1.1&fp=chrome&mode=packet-up"
                f"&path={_urlquote(xhttp_path, safe='')}"
                f"#{flag}\U0001f30f {short} SOCKS-PK"
            )
        # XHTTP H3 (QUIC) — optional, immune to TCP RST
        if "h3-exit" in enabled:
            links.append(
                f"vless://{user_uuid}@{addr}:8443"
                f"?encryption=none&type=xhttp&security=tls"
                f"&sni={addr}&alpn=h3&fp=chrome&mode=packet-up"
                f"&path={_urlquote(xhttp_path, safe='')}"
                f"#{flag}\U0001f680 {short} H3-EXIT"
            )
        if "h3-direct" in enabled:
            links.append(
                f"vless://{user_uuid}@{addr}:8444"
                f"?encryption=none&type=xhttp&security=tls"
                f"&sni={addr}&alpn=h3&fp=chrome&mode=packet-up"
                f"&path={_urlquote(xhttp_path, safe='')}"
                f"#{flag}\U0001f680 {short} H3-DIRECT"
            )
        if "dns" in enabled:
            links.append(
                f"hysteria2://{user_uuid}@{hy_addr}:53"
                f"?sni={hy_addr}&insecure=0"
                f"#{flag}\U0001f4e1 {short} DNS"
            )
        if "icmp" in enabled:
            links.append(
                f"hysteria2://{user_uuid}@{hy_addr}:9053"
                f"?sni={hy_addr}&insecure=0"
                f"#{flag}\U0001f6e1\ufe0f {short} ICMP"
            )

        # --- ClawStealth sub links ---
        # Cookie placement params included — standard xray-core clients (v24.12+)
        # should parse these from URI. If not, use /sub/stealth/{token}?format=json
        stealth_path = xhttp_path + "s"
        _cookie_params = (
            "&sessionPlacement=cookie&sessionKey=cf_session"
            "&seqPlacement=cookie&seqKey=cf_seq"
            "&uplinkDataPlacement=cookie&uplinkDataKey=cf_data"
        )
        if "stealth-exit" in enabled:
            links.append(
                f"vless://{user_uuid}@{addr}:4443"
                f"?encryption=none&type=xhttp&security=tls"
                f"&sni={addr}&alpn=h2,http/1.1&fp=chrome&mode=packet-up"
                f"&path={_urlquote(stealth_path, safe='')}"
                f"{_cookie_params}"
                f"#{flag}\U0001f6e1\ufe0f {short} S-EXIT"
            )
        if "stealth-direct" in enabled:
            links.append(
                f"vless://{user_uuid}@{addr}:4444"
                f"?encryption=none&type=xhttp&security=tls"
                f"&sni={addr}&alpn=h2,http/1.1&fp=chrome&mode=packet-up"
                f"&path={_urlquote(stealth_path, safe='')}"
                f"{_cookie_params}"
                f"#{flag}\U0001f6e1\ufe0f {short} S-DIRECT"
            )
        if "stealth-h3-exit" in enabled:
            links.append(
                f"vless://{user_uuid}@{addr}:8445"
                f"?encryption=none&type=xhttp&security=tls"
                f"&sni={addr}&alpn=h3&fp=chrome&mode=packet-up"
                f"&path={_urlquote(stealth_path, safe='')}"
                f"{_cookie_params}"
                f"#{flag}\U0001f680 {short} SH3-EXIT"
            )
        if "stealth-h3-direct" in enabled:
            links.append(
                f"vless://{user_uuid}@{addr}:8446"
                f"?encryption=none&type=xhttp&security=tls"
                f"&sni={addr}&alpn=h3&fp=chrome&mode=packet-up"
                f"&path={_urlquote(stealth_path, safe='')}"
                f"{_cookie_params}"
                f"#{flag}\U0001f680 {short} SH3-DIRECT"
            )

    return links


def generate_stealth_config(user_uuid: str, username: str, nodes: list) -> dict:
    """Generate a lightweight xray JSON client config for stealth mode only.

    This uses ONLY standard xray-core features (no finalmask):
    - Cookie-based XHTTP placement (session, seq, uplink data in cookies)
    - Tokenish padding in cookies
    - xmux for mobile stability
    - noGRPCHeader, noSSEHeader

    Works with: v2rayNG, Streisand, V2Box, FoXray, NekoBox — anything with
    xray-core v24.12+ that supports XHTTP cookie placement.

    Returns a complete xray JSON config dict ready for import.
    """
    outbounds = []

    for node in nodes:
        if not node.get("is_active"):
            continue

        addr = node["address"]
        short = node.get("name", "") or node.get("label", "")
        xhttp_path = node.get("xhttp_path", "") or f"/{_urlquote(addr.split('.')[0], safe='')}"
        stealth_path = xhttp_path + "s"

        # Cookie-based XHTTP stream settings (standard xray-core, no finalmask)
        def _stealth_stream(alpn=None):
            if alpn is None:
                alpn = ["h2", "http/1.1"]
            return {
                "network": "xhttp",
                "xhttpSettings": {
                    "mode": "packet-up",
                    "path": stealth_path,
                    "sessionPlacement": "cookie",
                    "sessionKey": "cf_session",
                    "seqPlacement": "cookie",
                    "seqKey": "cf_seq",
                    "uplinkDataPlacement": "cookie",
                    "uplinkDataKey": "cf_data",
                    "xPaddingObfsMode": True,
                    "xPaddingMethod": "tokenish",
                    "xPaddingPlacement": "cookie",
                    "xPaddingKey": "cf_token",
                    "noGRPCHeader": True,
                    "noSSEHeader": True,
                    "xmux": {
                        "maxConcurrency": {"from": 1, "to": 1},
                        "hMaxRequestTimes": {"from": 100, "to": 200},
                        "hMaxReusableSecs": {"from": 60, "to": 180},
                        "hKeepAlivePeriod": 15
                    }
                },
                "security": "tls",
                "tlsSettings": {
                    "serverName": addr,
                    "fingerprint": "chrome",
                    "alpn": alpn
                }
            }

        outbounds.append({
            "tag": f"{short}-S-EXIT",
            "protocol": "vless",
            "settings": {
                "vnext": [{
                    "address": addr,
                    "port": 4443,
                    "users": [{"id": user_uuid, "encryption": "none"}]
                }]
            },
            "streamSettings": _stealth_stream()
        })

        outbounds.append({
            "tag": f"{short}-S-DIRECT",
            "protocol": "vless",
            "settings": {
                "vnext": [{
                    "address": addr,
                    "port": 4444,
                    "users": [{"id": user_uuid, "encryption": "none"}]
                }]
            },
            "streamSettings": _stealth_stream()
        })

        # H3 stealth (QUIC, immune to TCP RST)
        outbounds.append({
            "tag": f"{short}-SH3-EXIT",
            "protocol": "vless",
            "settings": {
                "vnext": [{
                    "address": addr,
                    "port": 8445,
                    "users": [{"id": user_uuid, "encryption": "none"}]
                }]
            },
            "streamSettings": _stealth_stream(alpn=["h3"])
        })

        outbounds.append({
            "tag": f"{short}-SH3-DIRECT",
            "protocol": "vless",
            "settings": {
                "vnext": [{
                    "address": addr,
                    "port": 8446,
                    "users": [{"id": user_uuid, "encryption": "none"}]
                }]
            },
            "streamSettings": _stealth_stream(alpn=["h3"])
        })

    outbounds.extend([
        {"tag": "direct", "protocol": "freedom"},
        {"tag": "block", "protocol": "blackhole"}
    ])

    proxy_tags = [o["tag"] for o in outbounds if o["tag"] not in ("direct", "block")]

    return {
        "log": {"loglevel": "warning"},
        "dns": {
            "servers": [
                {"address": "https://1.1.1.1/dns-query", "domains": ["geosite:geolocation-!cn"]},
                {"address": "localhost"}
            ]
        },
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "balancers": [{
                "tag": "auto",
                "selector": proxy_tags,
                "strategy": {"type": "leastping"},
                "fallbackTag": proxy_tags[0] if proxy_tags else "direct"
            }],
            "rules": [
                {"type": "field", "domain": ["geosite:category-ads-all"], "outboundTag": "block"},
                {"type": "field", "ip": ["geoip:private"], "outboundTag": "direct"},
                {"type": "field", "network": "tcp,udp", "balancerTag": "auto"}
            ]
        },
        "observatory": {
            "subjectSelector": proxy_tags,
            "probeURL": "https://www.google.com/generate_204",
            "probeInterval": "30s",
            "enableConcurrency": True
        },
        "inbounds": [{
            "tag": "socks",
            "listen": "127.0.0.1",
            "port": 10808,
            "protocol": "socks",
            "settings": {"udp": True}
        }, {
            "tag": "http",
            "listen": "127.0.0.1",
            "port": 10809,
            "protocol": "http"
        }],
        "outbounds": outbounds
    }
