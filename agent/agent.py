#!/usr/bin/env python3
"""
ClawAgent v2.2.0 - Node daemon for ClawPanel.

Every SYNC_INTERVAL seconds:
  1. Fetches merged xray config from panel  (key: "xray")
  2. Fetches nginx config from panel        (key: "nginx" + "fake_html")
  3. Writes /etc/claw-xray-hy/config.json if changed, restarts claw-xray-hy
  4. Writes /etc/nginx/sites-enabled/claw.conf + /var/www/fake/index.html if changed
  5. Sends heartbeat with traffic stats

Architecture:
  nginx (443/2052 TLS, fake site) → xray (10443/12052 internal, XHTTP)
  xray (53/9053 HY2 UDP, direct TLS — no nginx)

Env vars:
  PANEL_URL       https://panel.clawvpn.lol
  AGENT_SECRET    shared secret (REQUIRED)
  NODE_NAME       e.g. "NL1" (REQUIRED)
  XRAY_HY_BIN     /usr/local/bin/xray-hy
  XRAY_HY_CFG     /etc/claw-xray-hy/config.json
  XRAY_HY_SERVICE claw-xray-hy
  XRAY_API_PORT   10085
  SYNC_INTERVAL   60
"""

import os, sys, json, hashlib, time, subprocess, logging, tempfile
from pathlib import Path
import urllib.request, urllib.error, ssl

PANEL_URL       = os.environ.get("PANEL_URL",        "")
AGENT_SECRET    = os.environ.get("AGENT_SECRET",     "")
NODE_NAME       = os.environ.get("NODE_NAME",        "")
XRAY_HY_BIN     = os.environ.get("XRAY_HY_BIN",     "/usr/local/bin/xray-hy")
XRAY_HY_CFG     = os.environ.get("XRAY_HY_CFG",     "/etc/claw-xray-hy/config.json")
XRAY_HY_SERVICE = os.environ.get("XRAY_HY_SERVICE", "claw-xray-hy")
XRAY_API_PORT   = int(os.environ.get("XRAY_API_PORT",  "10085"))
SYNC_INTERVAL   = int(os.environ.get("SYNC_INTERVAL",  "60"))
AGENT_VERSION   = "2.2.0"

NGINX_CONF_PATH = "/etc/nginx/sites-enabled/claw.conf"
FAKE_HTML_PATH  = "/var/www/fake/index.html"

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


def write_if_changed(path, content, mode=0o644):
    """Atomic write: write to temp file, then rename (no partial configs)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    new_hash = hashlib.md5(content.encode()).hexdigest()
    try:
        old_hash = hashlib.md5(target.read_bytes()).hexdigest()
    except FileNotFoundError:
        old_hash = ""
    if new_hash == old_hash:
        return False
    # Write to temp in same directory, then atomic rename
    fd, tmp_path = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        os.write(fd, content.encode())
        os.fchmod(fd, mode)
        os.close(fd)
        os.replace(tmp_path, str(target))
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return True


def service_restart(service):
    unit = service if service.endswith(".service") else f"{service}.service"
    r = subprocess.run(["systemctl", "restart", unit], capture_output=True, timeout=15)
    if r.returncode != 0:
        log.warning(f"restart {unit}: {r.stderr.decode().strip()}")
    return r.returncode == 0


def service_reload(service):
    unit = service if service.endswith(".service") else f"{service}.service"
    r = subprocess.run(["systemctl", "reload", unit], capture_output=True, timeout=15)
    if r.returncode != 0:
        log.warning(f"reload {unit}: {r.stderr.decode().strip()}")
        # fallback to restart
        return service_restart(service)
    return True


def ensure_nginx():
    """Make sure nginx is installed and running."""
    r = subprocess.run(["which", "nginx"], capture_output=True)
    if r.returncode != 0:
        log.info("nginx not found, installing...")
        # Remove problematic repos that might block apt
        for f in Path("/etc/apt/sources.list.d/").glob("*"):
            if "ookla" in f.name.lower() or "speedtest" in f.name.lower():
                f.unlink()
                log.info(f"removed problematic repo: {f.name}")
        subprocess.run(["apt-get", "update", "-qq"], capture_output=True, timeout=120)
        r = subprocess.run(["apt-get", "install", "-y", "-qq", "nginx"],
                          capture_output=True, timeout=120)
        if r.returncode != 0:
            log.error(f"failed to install nginx: {r.stderr.decode()[:200]}")
            return False
        log.info("nginx installed successfully")

    # Remove default site if exists
    default_site = Path("/etc/nginx/sites-enabled/default")
    if default_site.exists():
        default_site.unlink()
        log.info("removed default nginx site")

    # Make sure sites-enabled dir exists
    Path("/etc/nginx/sites-enabled").mkdir(parents=True, exist_ok=True)
    Path("/var/www/fake").mkdir(parents=True, exist_ok=True)

    # Enable and start nginx
    subprocess.run(["systemctl", "enable", "nginx"], capture_output=True, timeout=15)
    subprocess.run(["systemctl", "start", "nginx"], capture_output=True, timeout=15)
    return True


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
            email = parts[1]
            val = int(item.get("value", 0))
            stats.setdefault(email, {"up": 0, "down": 0})
            if parts[3] == "uplink":
                stats[email]["up"] += val
            elif parts[3] == "downlink":
                stats[email]["down"] += val
        return stats
    except Exception as e:
        log.debug(f"traffic read failed: {e}")
        return {}


def sync():
    # 1. Fetch xray config
    try:
        data = json.loads(http_get(f"{PANEL_URL}/agent/config/{NODE_NAME}"))
    except Exception as e:
        log.warning(f"fetch config failed: {e}")
        return

    cfg = json.dumps(data.get("xray", {}), indent=2)

    # 2. Write xray config and reload if changed
    if write_if_changed(XRAY_HY_CFG, cfg):
        log.info("xray config changed, restarting claw-xray-hy...")
        service_restart(XRAY_HY_SERVICE)

    # 3. Fetch nginx config
    try:
        nginx_data = json.loads(http_get(f"{PANEL_URL}/agent/nginx/{NODE_NAME}"))
        nginx_conf = nginx_data.get("nginx", "")
        fake_html = nginx_data.get("fake_html", "")

        if nginx_conf:
            # Ensure nginx is installed
            if ensure_nginx():
                nginx_changed = write_if_changed(NGINX_CONF_PATH, nginx_conf)
                html_changed = write_if_changed(FAKE_HTML_PATH, fake_html) if fake_html else False

                if nginx_changed or html_changed:
                    # Test config before reload
                    test = subprocess.run(["nginx", "-t"], capture_output=True, timeout=10)
                    if test.returncode == 0:
                        log.info("nginx config changed, reloading nginx...")
                        service_reload("nginx")
                    else:
                        log.error(f"nginx config test failed: {test.stderr.decode()[:200]}")
    except Exception as e:
        log.warning(f"fetch nginx config failed: {e}")

    # 4. Heartbeat
    try:
        http_post(f"{PANEL_URL}/agent/heartbeat", {
            "node":    NODE_NAME,
            "version": AGENT_VERSION,
            "traffic": read_traffic()
        })
    except Exception as e:
        log.warning(f"heartbeat failed: {e}")


def main():
    errors = []
    if not NODE_NAME:
        errors.append("NODE_NAME is required")
    if not AGENT_SECRET:
        errors.append("AGENT_SECRET is required")
    if not PANEL_URL:
        errors.append("PANEL_URL is required")
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
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
