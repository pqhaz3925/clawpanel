"""
ClawPanel — main FastAPI application.
Web UI + Agent API + Subscription API.
"""
import os
import json
import time
import hashlib
import secrets
import base64
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, Response, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

import models
from xray import build_xray_config, generate_sub_links

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    await models.init_db()
    yield

app = FastAPI(title="ClawPanel", version="2.0.0", lifespan=lifespan)

BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

SESSION_SECRET = secrets.token_hex(32)
SESSIONS: dict = {}  # token -> {admin: username, expires: timestamp}

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


# Register template globals
templates.env.globals["format_bytes"] = format_bytes
templates.env.globals["time_ago"] = time_ago
templates.env.globals["time_left"] = time_left
templates.env.globals["int"] = int
templates.env.globals["time"] = time


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------

def get_session_token(request: Request) -> Optional[str]:
    return request.cookies.get("claw_session")


def get_current_admin(request: Request) -> Optional[str]:
    token = get_session_token(request)
    if not token or token not in SESSIONS:
        return None
    sess = SESSIONS[token]
    if sess["expires"] < time.time():
        del SESSIONS[token]
        return None
    return sess["admin"]


def require_admin(request: Request):
    admin = get_current_admin(request)
    if not admin:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return admin


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": ""})


@app.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    if await models.verify_admin(username, password):
        token = secrets.token_urlsafe(32)
        SESSIONS[token] = {"admin": username, "expires": time.time() + 86400 * 7}
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie("claw_session", token, httponly=True, max_age=86400 * 7)
        return resp
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": "Invalid credentials"
    })


@app.get("/logout")
async def logout(request: Request):
    token = get_session_token(request)
    if token and token in SESSIONS:
        del SESSIONS[token]
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie("claw_session")
    return resp


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    admin = get_current_admin(request)
    if not admin:
        return RedirectResponse("/login", status_code=303)
    users = await models.get_all_users()
    nodes = await models.get_all_nodes()
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
    admin = get_current_admin(request)
    if not admin:
        return RedirectResponse("/login", status_code=303)
    users = await models.get_all_users()
    nodes = await models.get_all_nodes()
    panel_host = request.headers.get("host", "panel.clawvpn.lol:8000")
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
    user = await models.get_user(user_id)
    if user:
        await models.update_user(user_id, is_active=0 if user["is_active"] else 1)
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
    import uuid
    await models.update_user(user_id, xray_uuid=str(uuid.uuid4()))
    return RedirectResponse("/users", status_code=303)


@app.get("/users/{user_id}/sub-info", response_class=HTMLResponse)
async def user_sub_info(request: Request, user_id: str):
    admin = get_current_admin(request)
    if not admin:
        return RedirectResponse("/login", status_code=303)
    user = await models.get_user(user_id)
    if not user:
        raise HTTPException(404)
    nodes = await models.get_all_nodes()
    links = generate_sub_links(user["xray_uuid"], user["username"], nodes)
    scheme = request.headers.get("x-forwarded-proto", "https")
    host = request.headers.get("host", "panel.clawvpn.lol:8000")
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
                      flag: str = Form("🌍"), label: str = Form("")):
    require_admin(request)
    await models.create_node(name, address, flag=flag, label=label or name)
    return RedirectResponse("/nodes", status_code=303)


@app.post("/nodes/{node_id}/toggle")
async def node_toggle(request: Request, node_id: str):
    require_admin(request)
    db = await models.get_db()
    rows = await db.execute_fetchall("SELECT * FROM nodes WHERE id=?", (node_id,))
    if rows:
        node = dict(rows[0])
        await models.update_node(node_id, is_active=0 if node["is_active"] else 1)
    await db.close()
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
    admin = get_current_admin(request)
    if not admin:
        return RedirectResponse("/login", status_code=303)
    agent_secret = await models.get_setting("agent_secret")
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
    db = await models.get_db()
    pw_hash = hashlib.sha256(new_password.encode()).hexdigest()
    await db.execute("UPDATE admin SET password_hash=? WHERE username=?", (pw_hash, admin_name))
    await db.commit()
    await db.close()
    return RedirectResponse("/settings?ok=password", status_code=303)


@app.post("/settings/agent-secret")
async def change_agent_secret(request: Request, agent_secret: str = Form(...)):
    require_admin(request)
    await models.set_setting("agent_secret", agent_secret)
    return RedirectResponse("/settings?ok=secret", status_code=303)


# ---------------------------------------------------------------------------
# Agent API (called by node daemons)
# ---------------------------------------------------------------------------

async def verify_agent_secret(request: Request):
    secret = request.headers.get("X-Agent-Secret", "")
    expected = await models.get_setting("agent_secret")
    if not expected or secret != expected:
        raise HTTPException(403, "invalid agent secret")


@app.get("/agent/config/{node_name}")
async def agent_get_config(request: Request, node_name: str):
    await verify_agent_secret(request)
    node = await models.get_node_by_name(node_name)
    if not node:
        raise HTTPException(404, f"node {node_name} not found")
    clients = await models.get_active_xray_clients()
    config = build_xray_config(clients, node["address"])
    return {"xray": config}


@app.post("/agent/heartbeat")
async def agent_heartbeat(request: Request):
    await verify_agent_secret(request)
    body = await request.json()
    node_name = body.get("node", "")
    version = body.get("version", "")
    traffic = body.get("traffic", {})

    await models.node_heartbeat(node_name, version)

    # Record traffic per user
    for email, stats in traffic.items():
        up = stats.get("up", 0)
        down = stats.get("down", 0)
        if up > 0 or down > 0:
            await models.record_traffic(email, node_name, up, down)

    return {"ok": True}


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

    # Check expiry
    if user["expire_at"] > 0 and user["expire_at"] < time.time():
        raise HTTPException(403, "subscription expired")

    # Check data limit
    if user["data_limit"] > 0 and user["data_used"] >= user["data_limit"]:
        raise HTTPException(403, "data limit exceeded")

    nodes = await models.get_all_nodes()
    links = generate_sub_links(user["xray_uuid"], user["username"], nodes)

    content = "\n".join(links)
    encoded = base64.b64encode(content.encode()).decode()

    # Subscription-Userinfo header (for apps that show data usage)
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


# ---------------------------------------------------------------------------
# API — JSON endpoints for dynamic UI
# ---------------------------------------------------------------------------

@app.get("/api/stats")
async def api_stats(request: Request):
    admin = get_current_admin(request)
    if not admin:
        raise HTTPException(401)
    users = await models.get_all_users()
    nodes = await models.get_all_nodes()
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
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
