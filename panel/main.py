"""
ClawPanel — main FastAPI application.
Web UI + Agent API + Subscription API.
"""
import asyncio
import hmac
import os
import time
import secrets
import base64
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import models
from xray import build_xray_config, generate_sub_links, build_nginx_config, FAKE_SITE_HTML, generate_amnezia_config

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    await models.init_db()
    yield

app = FastAPI(title="ClawPanel", version="2.1.0", lifespan=lifespan)

BASE_DIR = Path(__file__).parent
static_dir = BASE_DIR / "static"
app.mount("/assets", StaticFiles(directory=str(static_dir / "assets")), name="assets")
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

SESSIONS: dict = {}  # token -> {admin: username, expires: timestamp}

# Cached agent secret — avoids hitting DB on every agent request
_agent_secret_cache: dict = {"value": "", "fetched_at": 0}
_CACHE_TTL = 300  # 5 min

PANEL_HOST = os.environ.get("PANEL_HOST", "")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def format_bytes(b: int) -> str:
    if b == 0:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(b) < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


def time_ago(ts: float) -> str:
    if ts == 0:
        return "never"
    diff = time.time() - ts
    if diff < 60:
        return f"{int(diff)}s ago"
    if diff < 3600:
        return f"{int(diff/60)}m ago"
    if diff < 86400:
        return f"{int(diff/3600)}h ago"
    return f"{int(diff/86400)}d ago"


def time_left(ts: float) -> str:
    if ts == 0:
        return "∞"
    diff = ts - time.time()
    if diff <= 0:
        return "expired"
    if diff < 3600:
        return f"{int(diff/60)}m"
    if diff < 86400:
        return f"{int(diff/3600)}h"
    return f"{int(diff/86400)}d"


templates.env.globals["format_bytes"] = format_bytes
templates.env.globals["time_ago"] = time_ago
templates.env.globals["time_left"] = time_left
templates.env.globals["int"] = int
templates.env.globals["time"] = time


def _cleanup_sessions():
    """Evict expired sessions (called lazily)."""
    now = time.time()
    expired = [k for k, v in SESSIONS.items() if v["expires"] < now]
    for k in expired:
        del SESSIONS[k]


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def get_current_admin(request: Request) -> str | None:
    token = request.cookies.get(models.COOKIE_NAME)
    if not token or token not in SESSIONS:
        return None
    sess = SESSIONS[token]
    if sess["expires"] < time.time():
        del SESSIONS[token]
        return None
    return sess["admin"]


def require_admin(request: Request) -> str:
    admin = get_current_admin(request)
    if not admin:
        # JSON API gets 401, HTML gets redirect
        if request.url.path.startswith("/api/"):
            raise HTTPException(status_code=401, detail="Unauthorized")
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return admin


async def _get_agent_secret() -> str:
    """Return agent secret with simple TTL cache."""
    now = time.time()
    if _agent_secret_cache["value"] and (now - _agent_secret_cache["fetched_at"]) < _CACHE_TTL:
        return _agent_secret_cache["value"]
    val = await models.get_setting(models.SETTING_AGENT_SECRET)
    _agent_secret_cache["value"] = val
    _agent_secret_cache["fetched_at"] = now
    return val


async def verify_agent_secret(request: Request):
    """Timing-safe agent secret verification."""
    secret = request.headers.get("X-Agent-Secret", "")
    expected = await _get_agent_secret()
    if not expected or not hmac.compare_digest(secret, expected):
        raise HTTPException(403, "invalid agent secret")


def _serve_spa() -> HTMLResponse | None:
    """Serve React SPA index.html if build exists."""
    index = BASE_DIR / "static" / "index.html"
    if index.exists():
        return HTMLResponse(index.read_text())
    return None


# ---------------------------------------------------------------------------
# Auth routes (SPA-aware: serve React if build exists, fallback to Jinja)
# ---------------------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    spa = _serve_spa()
    if spa:
        return spa
    return templates.TemplateResponse("login.html", {"request": request, "error": ""})


@app.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    if await models.verify_admin(username, password):
        _cleanup_sessions()
        token = secrets.token_urlsafe(32)
        SESSIONS[token] = {"admin": username, "expires": time.time() + 86400 * 7}
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(
            models.COOKIE_NAME, token,
            httponly=True, secure=True, samesite="lax",
            max_age=86400 * 7,
        )
        return resp
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": "Invalid credentials"
    })


@app.get("/logout")
async def logout(request: Request):
    token = request.cookies.get(models.COOKIE_NAME)
    if token and token in SESSIONS:
        del SESSIONS[token]
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(models.COOKIE_NAME)
    return resp


# ---------------------------------------------------------------------------
# Dashboard (SPA or legacy Jinja)
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    # Serve React SPA if build exists
    index = BASE_DIR / "static" / "index.html"
    if index.exists():
        return HTMLResponse(index.read_text())
    # Fallback to old Jinja template
    admin = get_current_admin(request)
    if not admin:
        return RedirectResponse("/login", status_code=303)
    users, nodes = await asyncio.gather(
        models.get_all_users(),
        models.get_all_nodes(),
    )
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "admin": admin,
        "users": users,
        "nodes": nodes,
        "now": time.time()
    })


# ---------------------------------------------------------------------------
# User CRUD
# ---------------------------------------------------------------------------

@app.get("/users", response_class=HTMLResponse)
async def users_page(request: Request):
    spa = _serve_spa()
    if spa:
        return spa
    admin = get_current_admin(request)
    if not admin:
        return RedirectResponse("/login", status_code=303)
    users, nodes = await asyncio.gather(
        models.get_all_users(),
        models.get_all_nodes(),
    )
    panel_host = PANEL_HOST or request.headers.get("host", "panel.clawvpn.lol")
    return templates.TemplateResponse("users.html", {
        "request": request,
        "admin": admin,
        "users": users,
        "nodes": nodes,
        "panel_host": panel_host
    })


@app.post("/users/create")
async def user_create(request: Request, username: str = Form(...), note: str = Form(""),
                      data_limit_gb: float = Form(0), expire_days: int = Form(0)):
    require_admin(request)
    data_limit = int(data_limit_gb * 1024**3) if data_limit_gb > 0 else 0
    expire_at = (time.time() + expire_days * 86400) if expire_days > 0 else 0
    await models.create_user(username, note=note, data_limit=data_limit, expire_at=expire_at)
    return RedirectResponse("/users", status_code=303)


@app.post("/users/{user_id}/toggle")
async def user_toggle(request: Request, user_id: str):
    require_admin(request)
    await models.toggle_user(user_id)
    return RedirectResponse("/users", status_code=303)


@app.post("/users/{user_id}/delete")
async def user_delete(request: Request, user_id: str):
    require_admin(request)
    await models.delete_user(user_id)
    return RedirectResponse("/users", status_code=303)


@app.post("/users/{user_id}/reset-traffic")
async def user_reset_traffic(request: Request, user_id: str):
    require_admin(request)
    await models.update_user(user_id, data_used=0)
    return RedirectResponse("/users", status_code=303)


@app.post("/users/{user_id}/reset-uuid")
async def user_reset_uuid(request: Request, user_id: str):
    require_admin(request)
    await models.reset_user_uuid(user_id)
    return RedirectResponse("/users", status_code=303)


@app.get("/users/{user_id}/sub-info", response_class=HTMLResponse)
async def user_sub_info(request: Request, user_id: str):
    admin = get_current_admin(request)
    if not admin:
        return RedirectResponse("/login", status_code=303)
    user, nodes = await asyncio.gather(
        models.get_user(user_id),
        models.get_active_nodes(),
    )
    if not user:
        raise HTTPException(404)
    links = generate_sub_links(user["xray_uuid"], user["username"], nodes)
    scheme = request.headers.get("x-forwarded-proto", "https")
    host = PANEL_HOST or request.headers.get("host", "panel.clawvpn.lol")
    sub_url = f"{scheme}://{host}/sub/{user['sub_token']}"
    return templates.TemplateResponse("sub_info.html", {
        "request": request,
        "admin": admin,
        "user": user,
        "links": links,
        "sub_url": sub_url
    })


# ---------------------------------------------------------------------------
# Node CRUD
# ---------------------------------------------------------------------------

@app.get("/nodes", response_class=HTMLResponse)
async def nodes_page(request: Request):
    spa = _serve_spa()
    if spa:
        return spa
    admin = get_current_admin(request)
    if not admin:
        return RedirectResponse("/login", status_code=303)
    nodes = await models.get_all_nodes()
    return templates.TemplateResponse("nodes.html", {
        "request": request,
        "admin": admin,
        "nodes": nodes,
        "now": time.time()
    })


@app.post("/nodes/create")
async def node_create(request: Request, name: str = Form(...), address: str = Form(...),
                      flag: str = Form("\U0001f30d"), label: str = Form("")):
    require_admin(request)
    await models.create_node(name, address, flag=flag, label=label or name)
    return RedirectResponse("/nodes", status_code=303)


@app.post("/nodes/{node_id}/toggle")
async def node_toggle(request: Request, node_id: str):
    require_admin(request)
    await models.toggle_node(node_id)
    return RedirectResponse("/nodes", status_code=303)


@app.post("/nodes/{node_id}/delete")
async def node_delete(request: Request, node_id: str):
    require_admin(request)
    await models.delete_node(node_id)
    return RedirectResponse("/nodes", status_code=303)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    spa = _serve_spa()
    if spa:
        return spa
    admin = get_current_admin(request)
    if not admin:
        return RedirectResponse("/login", status_code=303)
    agent_secret = await models.get_setting(models.SETTING_AGENT_SECRET)
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "admin": admin,
        "agent_secret": agent_secret
    })


@app.post("/settings/password")
async def change_password(request: Request, old_password: str = Form(...),
                          new_password: str = Form(...)):
    admin_name = require_admin(request)
    if not await models.verify_admin(admin_name, old_password):
        return RedirectResponse("/settings?error=wrong_password", status_code=303)
    await models.update_admin_password(admin_name, new_password)
    return RedirectResponse("/settings?ok=password", status_code=303)


@app.post("/settings/agent-secret")
async def change_agent_secret(request: Request, agent_secret: str = Form(...)):
    require_admin(request)
    await models.set_setting(models.SETTING_AGENT_SECRET, agent_secret)
    # Invalidate cache
    _agent_secret_cache["value"] = ""
    _agent_secret_cache["fetched_at"] = 0
    return RedirectResponse("/settings?ok=secret", status_code=303)


# ---------------------------------------------------------------------------
# Agent API (called by node daemons)
# ---------------------------------------------------------------------------

@app.get("/agent/config/{node_name}")
async def agent_get_config(request: Request, node_name: str):
    await verify_agent_secret(request)
    node = await models.get_node_by_name(node_name)
    if not node:
        raise HTTPException(404, f"node {node_name} not found")
    clients = await models.get_active_xray_clients()
    config = build_xray_config(clients, node["address"],
                               xhttp_path=node.get("xhttp_path", ""))
    return {"xray": config}


@app.get("/agent/nginx/{node_name}")
async def agent_get_nginx(request: Request, node_name: str):
    """Return nginx config for a node — TLS + fake site + XHTTP proxy."""
    await verify_agent_secret(request)
    node = await models.get_node_by_name(node_name)
    if not node:
        raise HTTPException(404, f"node {node_name} not found")
    nginx_conf = build_nginx_config(node["address"],
                                    xhttp_path=node.get("xhttp_path", ""))
    return {"nginx": nginx_conf, "fake_html": FAKE_SITE_HTML}


@app.post("/agent/heartbeat")
async def agent_heartbeat(request: Request):
    await verify_agent_secret(request)
    body = await request.json()
    node_name = body.get("node", "")
    version = body.get("version", "")
    traffic = body.get("traffic", {})

    # Parallel: heartbeat + traffic recording
    await asyncio.gather(
        models.node_heartbeat(node_name, version),
        models.record_traffic_batch(node_name, traffic),
    )

    return {"ok": True}


@app.get("/agent/binary")
async def agent_get_binary(request: Request):
    """Serve the latest xray-hy binary for agents to self-update."""
    await verify_agent_secret(request)
    binary_path = Path("/opt/xray/xray-hy")
    if not binary_path.exists():
        raise HTTPException(404, "binary not found")
    return FileResponse(binary_path, filename="xray-hy",
                        media_type="application/octet-stream")


@app.get("/agent/self-update")
async def agent_get_self(request: Request):
    """Serve the latest agent.py for self-update."""
    await verify_agent_secret(request)
    agent_path = Path(__file__).parent / "agent.py"
    if not agent_path.exists():
        raise HTTPException(404, "agent.py not found")
    return PlainTextResponse(agent_path.read_text())


# ---------------------------------------------------------------------------
# Subscription API (called by v2box/streisand clients)
# ---------------------------------------------------------------------------

@app.get("/sub/{token}")
async def subscription(request: Request, token: str):
    user = await models.get_user_by_sub_token(token)
    if not user:
        raise HTTPException(404, "subscription not found")

    if not user["is_active"]:
        raise HTTPException(403, "subscription disabled")

    if user["expire_at"] > 0 and user["expire_at"] < time.time():
        raise HTTPException(403, "subscription expired")

    if user["data_limit"] > 0 and user["data_used"] >= user["data_limit"]:
        raise HTTPException(403, "data limit exceeded")

    nodes = await models.get_active_nodes()
    links = generate_sub_links(
        user["xray_uuid"], user["username"], nodes,
        enabled_protocols=user.get("enabled_protocols", "exit,direct,socks,socks-pk,dns,icmp")
    )

    content = "\n".join(links)
    encoded = base64.b64encode(content.encode()).decode()

    upload = 0
    download = user["data_used"]
    total = user["data_limit"] if user["data_limit"] > 0 else 0
    expire = int(user["expire_at"]) if user["expire_at"] > 0 else 0

    headers = {
        "Content-Disposition": f'attachment; filename="{user["username"]}.txt"',
        "Profile-Title": f"ClawVPN - {user['username']}",
        "Profile-Update-Interval": "12",
        "Support-URL": "https://t.me/clawvpn",
    }

    userinfo_parts = [f"upload={upload}", f"download={download}"]
    if total > 0:
        userinfo_parts.append(f"total={total}")
    if expire > 0:
        userinfo_parts.append(f"expire={expire}")
    headers["Subscription-Userinfo"] = "; ".join(userinfo_parts)

    return PlainTextResponse(encoded, headers=headers)


@app.get("/sub/{token}/amnezia")
async def subscription_amnezia(request: Request, token: str):
    """Serve full xray-hy JSON config for AmneziaVPN client.

    Includes XHTTP + HY2 XDNS/XICMP with finalmask — all transports
    with observatory auto-fallback.
    """
    user = await models.get_user_by_sub_token(token)
    if not user:
        raise HTTPException(404, "subscription not found")
    if not user["is_active"]:
        raise HTTPException(403, "subscription disabled")
    if user["expire_at"] > 0 and user["expire_at"] < time.time():
        raise HTTPException(403, "subscription expired")
    if user["data_limit"] > 0 and user["data_used"] >= user["data_limit"]:
        raise HTTPException(403, "data limit exceeded")

    nodes = await models.get_active_nodes()
    config = generate_amnezia_config(
        user["xray_uuid"], user["username"], nodes,
        enabled_protocols=user.get("enabled_protocols", "exit,direct,socks,socks-pk,dns,icmp")
    )

    from fastapi.responses import JSONResponse
    return JSONResponse(
        config,
        headers={
            "Content-Disposition": f'attachment; filename="clawvpn-{user["username"]}.json"',
            "Profile-Title": f"ClawVPN - {user['username']} (Amnezia)",
        }
    )


@app.get("/sub/{token}/stealth")
async def subscription_stealth(request: Request, token: str):
    """Serve stealth subscription.

    Default (no ?format): base64 sub — standard EXIT+DIRECT ports (443/2053).
      Standard clients get server-side anti-fingerprint automatically.
    ?format=json: full xray JSON config with cookie-based stealth for custom clients.
    """
    user = await models.get_user_by_sub_token(token)
    if not user:
        raise HTTPException(404, "subscription not found")
    if not user["is_active"]:
        raise HTTPException(403, "subscription disabled")
    if user["expire_at"] > 0 and user["expire_at"] < time.time():
        raise HTTPException(403, "subscription expired")
    if user["data_limit"] > 0 and user["data_used"] >= user["data_limit"]:
        raise HTTPException(403, "data limit exceeded")

    nodes = await models.get_active_nodes()
    fmt = request.query_params.get("format", "sub")

    if fmt == "json":
        from xray import generate_stealth_config
        config = generate_stealth_config(user["xray_uuid"], user["username"], nodes)
        from fastapi.responses import JSONResponse
        return JSONResponse(
            config,
            headers={
                "Content-Disposition": f'attachment; filename="clawvpn-stealth-{user["username"]}.json"',
                "Profile-Title": f"ClawVPN - {user['username']} (Stealth)",
            }
        )

    # Base64 sub: standard ports with anti-fingerprint (works with ANY client)
    links = generate_sub_links(
        user["xray_uuid"], user["username"], nodes,
        enabled_protocols="exit,direct"
    )

    content = "\n".join(links)
    encoded = base64.b64encode(content.encode()).decode()

    upload = 0
    download = user["data_used"]
    total = user["data_limit"] if user["data_limit"] > 0 else 0
    expire = int(user["expire_at"]) if user["expire_at"] > 0 else 0

    headers = {
        "Content-Disposition": f'attachment; filename="{user["username"]}-stealth.txt"',
        "Profile-Title": f"ClawVPN - {user['username']} (Stealth)",
        "Profile-Update-Interval": "12",
        "Support-URL": "https://t.me/clawvpn",
    }

    userinfo_parts = [f"upload={upload}", f"download={download}"]
    if total > 0:
        userinfo_parts.append(f"total={total}")
    if expire > 0:
        userinfo_parts.append(f"expire={expire}")
    headers["Subscription-Userinfo"] = "; ".join(userinfo_parts)

    return PlainTextResponse(encoded, headers=headers)


@app.get("/api/stats")
async def api_stats(request: Request):
    admin = get_current_admin(request)
    if not admin:
        raise HTTPException(401)
    users, nodes = await asyncio.gather(
        models.get_all_users(),
        models.get_all_nodes(),
    )
    total_traffic = sum(u["data_used"] for u in users)
    active_users = sum(1 for u in users if u["is_active"])
    online_nodes = sum(1 for n in nodes if n["is_active"] and (time.time() - n["last_heartbeat"]) < 120)
    return {
        "total_users": len(users),
        "active_users": active_users,
        "total_nodes": len(nodes),
        "online_nodes": online_nodes,
        "total_traffic": format_bytes(total_traffic)
    }


# ---------------------------------------------------------------------------
# Scrape proxy API — static bearer, returns SOCKS5 proxies per live node
# ---------------------------------------------------------------------------

SCRAPE_API_TOKEN = os.environ.get("SCRAPE_API_TOKEN", "")
SCRAPE_SOCKS_PORT = int(os.environ.get("SCRAPE_SOCKS_PORT", "0"))
SCRAPE_SOCKS_USER = os.environ.get("SCRAPE_SOCKS_USER", "")
SCRAPE_SOCKS_PASS = os.environ.get("SCRAPE_SOCKS_PASS", "")


@app.get("/api/proxies")
async def api_proxies(request: Request):
    """Return SOCKS5 proxy list for all online nodes.

    Auth: Authorization: Bearer <SCRAPE_API_TOKEN>

    Response:
      { "proxies": [
          { "name": "NL2", "host": "212.46.33.55", "port": 11080,
            "user": "clawscrape", "pass": "...",
            "url": "socks5://user:pass@ip:port" },
          ...
      ]}
    """
    if not SCRAPE_API_TOKEN:
        raise HTTPException(503, "proxy API not configured")

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or not hmac.compare_digest(auth[7:], SCRAPE_API_TOKEN):
        raise HTTPException(401, "invalid token")

    nodes = await models.get_all_nodes()
    proxies = []
    for node in nodes:
        if not node["is_active"]:
            continue
        # Only include nodes with recent heartbeat (< 120s)
        if time.time() - node.get("last_heartbeat", 0) > 120:
            continue

        # Resolve node IP from address
        import socket
        try:
            ip = socket.gethostbyname(node["address"])
        except socket.gaierror:
            ip = node["address"]

        url = f"socks5://{SCRAPE_SOCKS_USER}:{SCRAPE_SOCKS_PASS}@{ip}:{SCRAPE_SOCKS_PORT}"
        proxies.append({
            "name": node["name"],
            "host": ip,
            "port": SCRAPE_SOCKS_PORT,
            "user": SCRAPE_SOCKS_USER,
            "pass": SCRAPE_SOCKS_PASS,
            "url": url,
        })

    return {"proxies": proxies, "count": len(proxies)}


# ---------------------------------------------------------------------------
# JSON API — Auth
# ---------------------------------------------------------------------------

@app.post("/api/auth/login")
async def api_login(request: Request):
    body = await request.json()
    username = body.get("username", "")
    password = body.get("password", "")
    if await models.verify_admin(username, password):
        _cleanup_sessions()
        token = secrets.token_urlsafe(32)
        SESSIONS[token] = {"admin": username, "expires": time.time() + 86400 * 7}
        from fastapi.responses import JSONResponse
        resp = JSONResponse({"ok": True, "admin": username})
        resp.set_cookie(
            models.COOKIE_NAME, token,
            httponly=True, secure=True, samesite="lax",
            max_age=86400 * 7,
        )
        return resp
    raise HTTPException(401, "Invalid credentials")


@app.post("/api/auth/logout")
async def api_logout(request: Request):
    token = request.cookies.get(models.COOKIE_NAME)
    if token and token in SESSIONS:
        del SESSIONS[token]
    from fastapi.responses import JSONResponse
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(models.COOKIE_NAME)
    return resp


@app.get("/api/auth/me")
async def api_me(request: Request):
    admin = get_current_admin(request)
    if not admin:
        raise HTTPException(401)
    return {"admin": admin}


# ---------------------------------------------------------------------------
# JSON API — Users
# ---------------------------------------------------------------------------

@app.get("/api/users")
async def api_get_users(request: Request):
    require_admin(request)
    users = await models.get_all_users()
    return {"users": users}


@app.post("/api/users")
async def api_create_user(request: Request):
    require_admin(request)
    body = await request.json()
    username = body.get("username", "").strip()
    if not username:
        raise HTTPException(400, "username required")
    note = body.get("note", "")
    data_limit_gb = float(body.get("data_limit_gb", 0))
    expire_days = int(body.get("expire_days", 0))
    data_limit = int(data_limit_gb * 1024**3) if data_limit_gb > 0 else 0
    expire_at = (time.time() + expire_days * 86400) if expire_days > 0 else 0
    user = await models.create_user(username, note=note, data_limit=data_limit, expire_at=expire_at)
    return {"ok": True, "user": user}


@app.patch("/api/users/{user_id}")
async def api_update_user(request: Request, user_id: str):
    require_admin(request)
    body = await request.json()
    await models.update_user(user_id, **{k: v for k, v in body.items() if k in models._ALLOWED_USER_COLS})
    return {"ok": True}


@app.delete("/api/users/{user_id}")
async def api_delete_user(request: Request, user_id: str):
    require_admin(request)
    await models.delete_user(user_id)
    return {"ok": True}


@app.post("/api/users/{user_id}/toggle")
async def api_toggle_user(request: Request, user_id: str):
    require_admin(request)
    await models.toggle_user(user_id)
    return {"ok": True}


@app.post("/api/users/{user_id}/reset-traffic")
async def api_reset_traffic(request: Request, user_id: str):
    require_admin(request)
    await models.update_user(user_id, data_used=0)
    return {"ok": True}


@app.post("/api/users/{user_id}/reset-uuid")
async def api_reset_uuid(request: Request, user_id: str):
    require_admin(request)
    await models.reset_user_uuid(user_id)
    return {"ok": True}


@app.post("/api/users/{user_id}/protocols")
async def api_update_protocols(request: Request, user_id: str):
    require_admin(request)
    body = await request.json()
    protocols = body.get("enabled_protocols", "")
    # Validate: only allow known protocol keys
    valid = {"exit", "direct", "socks", "socks-pk", "dns", "icmp"}
    parts = [p.strip().lower() for p in protocols.split(",") if p.strip()]
    cleaned = ",".join(p for p in parts if p in valid)
    if not cleaned:
        raise HTTPException(400, "at least one protocol required")
    await models.update_user(user_id, enabled_protocols=cleaned)
    return {"ok": True, "enabled_protocols": cleaned}


@app.get("/api/users/{user_id}/sub-info")
async def api_user_sub_info(request: Request, user_id: str):
    require_admin(request)
    user, nodes = await asyncio.gather(
        models.get_user(user_id),
        models.get_active_nodes(),
    )
    if not user:
        raise HTTPException(404)
    links = generate_sub_links(
        user["xray_uuid"], user["username"], nodes,
        enabled_protocols=user.get("enabled_protocols", "exit,direct,socks,socks-pk,dns,icmp")
    )
    scheme = request.headers.get("x-forwarded-proto", "https")
    host = PANEL_HOST or request.headers.get("host", "panel.clawvpn.lol")
    sub_url = f"{scheme}://{host}/sub/{user['sub_token']}"
    return {"sub_url": sub_url, "links": links, "user": user}


# ---------------------------------------------------------------------------
# JSON API — Nodes
# ---------------------------------------------------------------------------

@app.get("/api/nodes")
async def api_get_nodes(request: Request):
    require_admin(request)
    nodes = await models.get_all_nodes()
    return {"nodes": nodes}


@app.post("/api/nodes")
async def api_create_node(request: Request):
    require_admin(request)
    body = await request.json()
    name = body.get("name", "").strip()
    address = body.get("address", "").strip()
    if not name or not address:
        raise HTTPException(400, "name and address required")
    flag = body.get("flag", "\U0001f30d")
    label = body.get("label", "") or name
    node = await models.create_node(name, address, flag=flag, label=label)
    return {"ok": True, "node": node}


@app.delete("/api/nodes/{node_id}")
async def api_delete_node(request: Request, node_id: str):
    require_admin(request)
    await models.delete_node(node_id)
    return {"ok": True}


@app.post("/api/nodes/{node_id}/toggle")
async def api_toggle_node(request: Request, node_id: str):
    require_admin(request)
    await models.toggle_node(node_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# JSON API — Settings
# ---------------------------------------------------------------------------

@app.get("/api/settings")
async def api_get_settings(request: Request):
    require_admin(request)
    agent_secret = await models.get_setting(models.SETTING_AGENT_SECRET)
    return {"agent_secret": agent_secret}


@app.post("/api/settings/password")
async def api_change_password(request: Request):
    admin_name = require_admin(request)
    body = await request.json()
    if not await models.verify_admin(admin_name, body.get("old_password", "")):
        raise HTTPException(400, "Wrong current password")
    await models.update_admin_password(admin_name, body.get("new_password", ""))
    return {"ok": True}


@app.post("/api/settings/agent-secret")
async def api_change_agent_secret(request: Request):
    require_admin(request)
    body = await request.json()
    secret = body.get("agent_secret", "").strip()
    if not secret:
        raise HTTPException(400, "secret required")
    await models.set_setting(models.SETTING_AGENT_SECRET, secret)
    _agent_secret_cache["value"] = ""
    _agent_secret_cache["fetched_at"] = 0
    return {"ok": True}


# ---------------------------------------------------------------------------
# SPA fallback — serve React build
# ---------------------------------------------------------------------------

@app.get("/{path:path}")
async def spa_fallback(request: Request, path: str):
    # Don't intercept API, agent, or sub routes
    if path.startswith(("api/", "agent/", "sub/")):
        raise HTTPException(404)
    # Serve index.html for SPA routing
    index = BASE_DIR / "static" / "index.html"
    if index.exists():
        return HTMLResponse(index.read_text())
    # Fallback to old template if React build not present
    admin = get_current_admin(request)
    if not admin:
        return RedirectResponse("/login", status_code=303)
    return RedirectResponse("/", status_code=303)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
