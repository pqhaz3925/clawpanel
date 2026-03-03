#!/usr/bin/env python3
"""
ClawAgent - Node daemon for ClawPanel.

Every SYNC_INTERVAL seconds:
  1. Fetches merged xray config from panel  (key: "xray")
  2. Writes /etc/claw-xray-hy/config.json if changed, restarts claw-xray-hy
  3. Sends heartbeat with traffic stats

One binary (xray-hy / finalmask) handles everything:
  VLESS XHTTP :443 :2052  +  HY2 XDNS :53  +  HY2 XICMP :9053

Env vars:
  PANEL_URL       https://panel.clawvpn.lol:8000
  AGENT_SECRET    shared secret
  NODE_NAME       e.g. "DE-Play2Go"
  XRAY_HY_BIN     /usr/local/bin/xray-hy
  XRAY_HY_CFG     /etc/claw-xray-hy/config.json
  XRAY_HY_SERVICE claw-xray-hy
  XRAY_API_PORT   10085
  SYNC_INTERVAL   60
"""

import os, sys, json, hashlib, time, subprocess, logging
from pathlib import Path
import urllib.request, urllib.error, ssl

PANEL_URL       = os.environ.get("PANEL_URL",        "https://panel.clawvpn.lol:8000")
AGENT_SECRET    = os.environ.get("AGENT_SECRET",     "clawagent-secret-changeme-2025!!")
NODE_NAME       = os.environ.get("NODE_NAME",        "")
XRAY_HY_BIN     = os.environ.get("XRAY_HY_BIN",     "/usr/local/bin/xray-hy")
XRAY_HY_CFG     = os.environ.get("XRAY_HY_CFG",     "/etc/claw-xray-hy/config.json")
XRAY_HY_SERVICE = os.environ.get("XRAY_HY_SERVICE", "claw-xray-hy")
XRAY_API_PORT   = int(os.environ.get("XRAY_API_PORT",  "10085"))
SYNC_INTERVAL   = int(os.environ.get("SYNC_INTERVAL",  "60"))
AGENT_VERSION   = "2.0.0"

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("claw-agent")
ssl_ctx = ssl.create_default_context()


def http_get(url):
    req = urllib.request.Request(url, headers={"X-Agent-Secret": AGENT_SECRET})
    with urllib.request.urlopen(req, context=ssl_ctx, timeout=15) as r:
        return r.read()


def http_post(url, data):
    body = json.dumps(data).encode()
    req  = urllib.request.Request(
        url, data=body,
        headers={"X-Agent-Secret": AGENT_SECRET, "Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, context=ssl_ctx, timeout=15) as r:
        return r.read()


def write_if_changed(path, content):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    new_hash = hashlib.md5(content.encode()).hexdigest()
    try:
        old_hash = hashlib.md5(Path(path).read_bytes()).hexdigest()
    except FileNotFoundError:
        old_hash = ""
    if new_hash == old_hash:
        return False
    Path(path).write_text(content)
    return True


def service_restart(service):
    unit = service if service.endswith(".service") else f"{service}.service"
    r = subprocess.run(["systemctl", "restart", unit], capture_output=True, timeout=15)
    if r.returncode != 0:
        log.warning(f"restart {unit}: {r.stderr.decode().strip()}")
    return r.returncode == 0


def read_traffic():
    try:
        r = subprocess.run(
            [XRAY_HY_BIN, "api", "statsquery",
             f"--server=127.0.0.1:{XRAY_API_PORT}", "--pattern=user", "--reset"],
            capture_output=True, timeout=10
        )
        if r.returncode != 0:
            return {}
        stats = {}
        for item in json.loads(r.stdout).get("stat", []):
            parts = item.get("name", "").split(">>>")
            if len(parts) < 4:
                continue
            uid = parts[1].split("@")[0]
            val = int(item.get("value", 0))
            stats.setdefault(uid, {"up": 0, "down": 0})
            if parts[3] == "uplink":
                stats[uid]["up"] += val
            elif parts[3] == "downlink":
                stats[uid]["down"] += val
        return stats
    except Exception as e:
        log.debug(f"traffic read failed: {e}")
        return {}


def sync():
    # 1. Fetch config
    try:
        data = json.loads(http_get(f"{PANEL_URL}/agent/config/{NODE_NAME}"))
    except Exception as e:
        log.warning(f"fetch config failed: {e}")
        return

    cfg = json.dumps(data.get("xray", {}), indent=2)

    # 2. Write and reload if changed
    if write_if_changed(XRAY_HY_CFG, cfg):
        log.info("config changed, restarting claw-xray-hy...")
        service_restart(XRAY_HY_SERVICE)

    # 3. Heartbeat
    try:
        http_post(f"{PANEL_URL}/agent/heartbeat", {
            "node":    NODE_NAME,
            "version": AGENT_VERSION,
            "traffic": read_traffic()
        })
    except Exception as e:
        log.warning(f"heartbeat failed: {e}")


def main():
    if not NODE_NAME:
        print("ERROR: NODE_NAME is required", file=sys.stderr)
        sys.exit(1)
    log.info(f"ClawAgent v{AGENT_VERSION} | node={NODE_NAME} | interval={SYNC_INTERVAL}s")
    sync()
    while True:
        time.sleep(SYNC_INTERVAL)
        try:
            sync()
        except Exception as e:
            log.error(f"sync error: {e}")


if __name__ == "__main__":
    main()
