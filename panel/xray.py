"""
Xray config generator for ClawPanel.

Builds full xray-core/xray-hy (finalmask) configs for nodes.
Supports: VLESS XHTTP, Hysteria2 XDNS, Hysteria2 XICMP.
"""
import os
from typing import List, Dict


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

CERT_VLESS_FULLCHAIN = os.environ.get("CERT_VLESS_FULLCHAIN", "/etc/ssl/xray/fullchain.pem")
CERT_VLESS_KEY = os.environ.get("CERT_VLESS_KEY", "/etc/ssl/xray/privkey.pem")
CERT_HY2_FULLCHAIN = os.environ.get("CERT_HY2_FULLCHAIN", "/etc/ssl/xray/fullchain.pem")
CERT_HY2_KEY = os.environ.get("CERT_HY2_KEY", "/etc/ssl/xray/privkey.pem")

XDNS_DOMAIN = os.environ.get("XDNS_DOMAIN", "t.example.com")


# ---------------------------------------------------------------------------
# Inbound builders — shared structure, no copy-paste
# ---------------------------------------------------------------------------

def _build_vless_xhttp_inbound(tag: str, port: int, clients: list, cert: dict) -> dict:
    """Build a VLESS XHTTP inbound (used for both EXIT and DIRECT)."""
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
            "xhttpSettings": {"mode": "auto"},
            "security": "tls",
            "tlsSettings": {
                "certificates": [cert],
                "minVersion": "1.2",
                "alpn": ["h2", "http/1.1"]
            }
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

    cert_vless = {
        "certificateFile": CERT_VLESS_FULLCHAIN,
        "keyFile": CERT_VLESS_KEY
    }
    cert_hy2 = {
        "certificateFile": CERT_HY2_FULLCHAIN,
        "keyFile": CERT_HY2_KEY
    }

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
            # VLESS XHTTP EXIT (:443) and DIRECT (:2052)
            _build_vless_xhttp_inbound("VLESS-XHTTP-EXIT", 443, vless_clients, cert_vless),
            _build_vless_xhttp_inbound("VLESS-XHTTP-DIRECT", 2052, vless_clients, cert_vless),
            # Hysteria2 XDNS (:53) and XICMP (:9053)
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


def generate_sub_links(user_uuid: str, username: str, nodes: list) -> list:
    """Generate subscription links for a user across all active nodes."""
    links = []

    for node in nodes:
        if not node.get("is_active"):
            continue

        addr = node["address"]
        flag = node.get("flag", "\U0001f30d")
        short = node.get("name", "") or node.get("label", "")

        links.append(
            f"vless://{user_uuid}@{addr}:443"
            f"?encryption=none&type=xhttp&security=tls"
            f"&sni={addr}&alpn=h2,http/1.1&mode=auto"
            f"#{flag}\U0001f504 {short} EXIT"
        )
        links.append(
            f"vless://{user_uuid}@{addr}:2052"
            f"?encryption=none&type=xhttp&security=tls"
            f"&sni={addr}&alpn=h2,http/1.1&mode=auto"
            f"#{flag}\u26a1\ufe0f {short} DIRECT"
        )
        links.append(
            f"hysteria2://{user_uuid}@{addr}:53"
            f"?sni={addr}&insecure=0"
            f"#{flag}\U0001f4e1 {short} DNS"
        )
        links.append(
            f"hysteria2://{user_uuid}@{addr}:9053"
            f"?sni={addr}&insecure=0"
            f"#{flag}\U0001f6e1\ufe0f {short} ICMP"
        )

    return links
