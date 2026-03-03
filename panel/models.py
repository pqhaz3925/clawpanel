"""Database models and helpers for ClawPanel."""
import aiosqlite
import uuid
import time
import json
import hashlib
import secrets
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "claw.db"


async def get_db():
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db():
    db = await get_db()
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS nodes (
            id TEXT PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            address TEXT NOT NULL,
            flag TEXT DEFAULT '🌍',
            label TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            last_heartbeat REAL DEFAULT 0,
            agent_version TEXT DEFAULT '',
            created_at REAL DEFAULT (unixepoch())
        );

        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            xray_uuid TEXT UNIQUE NOT NULL,
            sub_token TEXT UNIQUE NOT NULL,
            data_limit INTEGER DEFAULT 0,
            data_used INTEGER DEFAULT 0,
            expire_at REAL DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            note TEXT DEFAULT '',
            created_at REAL DEFAULT (unixepoch())
        );

        CREATE TABLE IF NOT EXISTS traffic_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            upload INTEGER DEFAULT 0,
            download INTEGER DEFAULT 0,
            recorded_at REAL DEFAULT (unixepoch()),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (node_id) REFERENCES nodes(id)
        );

        CREATE TABLE IF NOT EXISTS admin (
            id INTEGER PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        );
    """)

    # Default admin
    existing = await db.execute_fetchall("SELECT id FROM admin")
    if not existing:
        pw_hash = hashlib.sha256("ClawVPN2025".encode()).hexdigest()
        await db.execute(
            "INSERT INTO admin (username, password_hash) VALUES (?, ?)",
            ("admin", pw_hash)
        )

    # Default agent secret
    existing = await db.execute_fetchall("SELECT value FROM settings WHERE key='agent_secret'")
    if not existing:
        secret = secrets.token_urlsafe(32)
        await db.execute(
            "INSERT INTO settings (key, value) VALUES ('agent_secret', ?)",
            (secret,)
        )

    await db.commit()
    await db.close()


# --- User helpers ---

async def create_user(username: str, note: str = "", data_limit: int = 0, expire_at: float = 0):
    db = await get_db()
    uid = str(uuid.uuid4())[:8]
    xray_uuid = str(uuid.uuid4())
    sub_token = secrets.token_urlsafe(16)
    await db.execute(
        "INSERT INTO users (id, username, xray_uuid, sub_token, data_limit, expire_at, note) VALUES (?,?,?,?,?,?,?)",
        (uid, username, xray_uuid, sub_token, data_limit, expire_at, note)
    )
    await db.commit()
    user = await db.execute_fetchall("SELECT * FROM users WHERE id=?", (uid,))
    await db.close()
    return dict(user[0]) if user else None


async def get_all_users():
    db = await get_db()
    rows = await db.execute_fetchall("SELECT * FROM users ORDER BY created_at DESC")
    await db.close()
    return [dict(r) for r in rows]


async def get_user(user_id: str):
    db = await get_db()
    rows = await db.execute_fetchall("SELECT * FROM users WHERE id=?", (user_id,))
    await db.close()
    return dict(rows[0]) if rows else None


async def get_user_by_sub_token(token: str):
    db = await get_db()
    rows = await db.execute_fetchall("SELECT * FROM users WHERE sub_token=?", (token,))
    await db.close()
    return dict(rows[0]) if rows else None


async def update_user(user_id: str, **kwargs):
    db = await get_db()
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [user_id]
    await db.execute(f"UPDATE users SET {sets} WHERE id=?", vals)
    await db.commit()
    await db.close()


async def delete_user(user_id: str):
    db = await get_db()
    await db.execute("DELETE FROM users WHERE id=?", (user_id,))
    await db.commit()
    await db.close()


async def get_active_xray_clients():
    """Return list of {id, email} for active users."""
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT xray_uuid, username FROM users WHERE is_active=1"
    )
    await db.close()
    return [{"id": r["xray_uuid"], "email": r["username"]} for r in rows]


# --- Node helpers ---

async def create_node(name: str, address: str, flag: str = "🌍", label: str = ""):
    db = await get_db()
    nid = str(uuid.uuid4())[:8]
    await db.execute(
        "INSERT INTO nodes (id, name, address, flag, label) VALUES (?,?,?,?,?)",
        (nid, name, address, flag, label)
    )
    await db.commit()
    node = await db.execute_fetchall("SELECT * FROM nodes WHERE id=?", (nid,))
    await db.close()
    return dict(node[0]) if node else None


async def get_all_nodes():
    db = await get_db()
    rows = await db.execute_fetchall("SELECT * FROM nodes ORDER BY created_at")
    await db.close()
    return [dict(r) for r in rows]


async def get_node_by_name(name: str):
    db = await get_db()
    rows = await db.execute_fetchall("SELECT * FROM nodes WHERE name=?", (name,))
    await db.close()
    return dict(rows[0]) if rows else None


async def update_node(node_id: str, **kwargs):
    db = await get_db()
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [node_id]
    await db.execute(f"UPDATE nodes SET {sets} WHERE id=?", vals)
    await db.commit()
    await db.close()


async def delete_node(node_id: str):
    db = await get_db()
    await db.execute("DELETE FROM nodes WHERE id=?", (node_id,))
    await db.commit()
    await db.close()


async def node_heartbeat(name: str, version: str = ""):
    db = await get_db()
    await db.execute(
        "UPDATE nodes SET last_heartbeat=?, agent_version=? WHERE name=?",
        (time.time(), version, name)
    )
    await db.commit()
    await db.close()


# --- Settings ---

async def get_setting(key: str, default: str = ""):
    db = await get_db()
    rows = await db.execute_fetchall("SELECT value FROM settings WHERE key=?", (key,))
    await db.close()
    return rows[0]["value"] if rows else default


async def set_setting(key: str, value: str):
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, value)
    )
    await db.commit()
    await db.close()


# --- Admin ---

async def verify_admin(username: str, password: str):
    db = await get_db()
    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    rows = await db.execute_fetchall(
        "SELECT * FROM admin WHERE username=? AND password_hash=?",
        (username, pw_hash)
    )
    await db.close()
    return bool(rows)


# --- Traffic ---

async def record_traffic(user_email: str, node_name: str, upload: int, download: int):
    db = await get_db()
    # Find user by email (username)
    user_rows = await db.execute_fetchall("SELECT id FROM users WHERE username=?", (user_email,))
    node_rows = await db.execute_fetchall("SELECT id FROM nodes WHERE name=?", (node_name,))
    if user_rows and node_rows:
        uid = user_rows[0]["id"]
        nid = node_rows[0]["id"]
        await db.execute(
            "INSERT INTO traffic_log (user_id, node_id, upload, download) VALUES (?,?,?,?)",
            (uid, nid, upload, download)
        )
        await db.execute(
            "UPDATE users SET data_used = data_used + ? WHERE id=?",
            (upload + download, uid)
        )
    await db.commit()
    await db.close()
