"""Database models and helpers for ClawPanel."""
import aiosqlite
import uuid
import time
import hashlib
import hmac
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "claw.db"

# --- Constants ---
SETTING_AGENT_SECRET = "agent_secret"
COOKIE_NAME = "claw_session"

_ALLOWED_USER_COLS = frozenset({
    "is_active", "data_used", "data_limit", "xray_uuid",
    "expire_at", "note", "sub_token", "username", "enabled_protocols",
})
_ALLOWED_NODE_COLS = frozenset({
    "is_active", "address", "flag", "label", "name",
    "last_heartbeat", "agent_version", "xhttp_path",
})


# --- DB connection (context manager, no leaks) ---

@asynccontextmanager
async def _db():
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()


async def init_db():
    async with _db() as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
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
                enabled_protocols TEXT DEFAULT 'exit,direct,socks,socks-pk,dns,icmp',
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
            await db.execute(
                "INSERT INTO admin (username, password_hash) VALUES (?, ?)",
                ("admin", hash_password("ClawVPN2025"))
            )

        # Default agent secret
        existing = await db.execute_fetchall(
            "SELECT value FROM settings WHERE key=?", (SETTING_AGENT_SECRET,)
        )
        if not existing:
            await db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)",
                (SETTING_AGENT_SECRET, secrets.token_urlsafe(32))
            )

        # Migration: add enabled_protocols column if missing
        cols = [r[1] for r in await db.execute_fetchall("PRAGMA table_info(users)")]
        if "enabled_protocols" not in cols:
            await db.execute(
                "ALTER TABLE users ADD COLUMN enabled_protocols TEXT DEFAULT 'exit,direct,dns,icmp'"
            )

        # Migration: add xhttp_path column to nodes if missing
        node_cols = [r[1] for r in await db.execute_fetchall("PRAGMA table_info(nodes)")]
        if "xhttp_path" not in node_cols:
            await db.execute(
                "ALTER TABLE nodes ADD COLUMN xhttp_path TEXT DEFAULT ''"
            )
            # Backfill existing nodes with random paths
            nodes = await db.execute_fetchall("SELECT id, xhttp_path FROM nodes")
            for n in nodes:
                if not n["xhttp_path"]:
                    rpath = "/" + secrets.token_urlsafe(8)
                    await db.execute("UPDATE nodes SET xhttp_path=? WHERE id=?", (rpath, n["id"]))

        # Migration: add socks,socks-pk to existing users' enabled_protocols
        all_users = await db.execute_fetchall("SELECT id, enabled_protocols FROM users")
        for u in all_users:
            protos = u["enabled_protocols"] or "exit,direct,dns,icmp"
            parts = [p.strip() for p in protos.split(",")]
            if "socks" not in parts or "socks-pk" not in parts:
                if "socks" not in parts:
                    parts.append("socks")
                if "socks-pk" not in parts:
                    parts.append("socks-pk")
                await db.execute(
                    "UPDATE users SET enabled_protocols=? WHERE id=?",
                    (",".join(parts), u["id"])
                )

        await db.commit()


# --- Password hashing (single source of truth) ---

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


# --- User helpers ---

async def create_user(username: str, note: str = "", data_limit: int = 0, expire_at: float = 0):
    async with _db() as db:
        uid = str(uuid.uuid4())[:8]
        xray_uuid = str(uuid.uuid4())
        sub_token = secrets.token_urlsafe(16)
        now = time.time()
        await db.execute(
            "INSERT INTO users (id, username, xray_uuid, sub_token, data_limit, expire_at, note) VALUES (?,?,?,?,?,?,?)",
            (uid, username, xray_uuid, sub_token, data_limit, expire_at, note)
        )
        await db.commit()
        return {
            "id": uid, "username": username, "xray_uuid": xray_uuid,
            "sub_token": sub_token, "data_limit": data_limit, "data_used": 0,
            "expire_at": expire_at, "is_active": 1, "note": note, "created_at": now,
        }


async def get_all_users():
    async with _db() as db:
        rows = await db.execute_fetchall("SELECT * FROM users ORDER BY created_at DESC")
        return [dict(r) for r in rows]


async def get_user(user_id: str):
    async with _db() as db:
        rows = await db.execute_fetchall("SELECT * FROM users WHERE id=?", (user_id,))
        return dict(rows[0]) if rows else None


async def get_user_by_sub_token(token: str):
    async with _db() as db:
        rows = await db.execute_fetchall("SELECT * FROM users WHERE sub_token=?", (token,))
        return dict(rows[0]) if rows else None


async def update_user(user_id: str, **kwargs):
    if not kwargs.keys() <= _ALLOWED_USER_COLS:
        raise ValueError(f"Invalid columns: {kwargs.keys() - _ALLOWED_USER_COLS}")
    async with _db() as db:
        sets = ", ".join(f"{k}=?" for k in kwargs)
        vals = list(kwargs.values()) + [user_id]
        await db.execute(f"UPDATE users SET {sets} WHERE id=?", vals)
        await db.commit()


async def delete_user(user_id: str):
    async with _db() as db:
        await db.execute("DELETE FROM users WHERE id=?", (user_id,))
        await db.commit()


async def toggle_user(user_id: str):
    """Atomically toggle is_active (no SELECT needed)."""
    async with _db() as db:
        await db.execute("UPDATE users SET is_active = 1 - is_active WHERE id=?", (user_id,))
        await db.commit()


async def reset_user_uuid(user_id: str):
    """Generate a new xray UUID for the user."""
    await update_user(user_id, xray_uuid=str(uuid.uuid4()))


async def get_active_xray_clients():
    async with _db() as db:
        rows = await db.execute_fetchall(
            "SELECT xray_uuid, username FROM users WHERE is_active=1"
        )
        return [{"id": r["xray_uuid"], "email": r["username"]} for r in rows]


# --- Node helpers ---

async def create_node(name: str, address: str, flag: str = "🌍", label: str = ""):
    async with _db() as db:
        nid = str(uuid.uuid4())[:8]
        now = time.time()
        xhttp_path = "/" + secrets.token_urlsafe(8)
        await db.execute(
            "INSERT INTO nodes (id, name, address, flag, label, xhttp_path) VALUES (?,?,?,?,?,?)",
            (nid, name, address, flag, label or name, xhttp_path)
        )
        await db.commit()
        return {
            "id": nid, "name": name, "address": address, "flag": flag,
            "label": label or name, "is_active": 1, "last_heartbeat": 0,
            "agent_version": "", "created_at": now, "xhttp_path": xhttp_path,
        }


async def get_all_nodes():
    async with _db() as db:
        rows = await db.execute_fetchall("SELECT * FROM nodes ORDER BY created_at")
        return [dict(r) for r in rows]


async def get_active_nodes():
    async with _db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM nodes WHERE is_active=1 ORDER BY created_at"
        )
        return [dict(r) for r in rows]


async def get_node(node_id: str):
    async with _db() as db:
        rows = await db.execute_fetchall("SELECT * FROM nodes WHERE id=?", (node_id,))
        return dict(rows[0]) if rows else None


async def get_node_by_name(name: str):
    async with _db() as db:
        rows = await db.execute_fetchall("SELECT * FROM nodes WHERE name=?", (name,))
        return dict(rows[0]) if rows else None


async def update_node(node_id: str, **kwargs):
    if not kwargs.keys() <= _ALLOWED_NODE_COLS:
        raise ValueError(f"Invalid columns: {kwargs.keys() - _ALLOWED_NODE_COLS}")
    async with _db() as db:
        sets = ", ".join(f"{k}=?" for k in kwargs)
        vals = list(kwargs.values()) + [node_id]
        await db.execute(f"UPDATE nodes SET {sets} WHERE id=?", vals)
        await db.commit()


async def delete_node(node_id: str):
    async with _db() as db:
        await db.execute("DELETE FROM nodes WHERE id=?", (node_id,))
        await db.commit()


async def toggle_node(node_id: str):
    """Atomically toggle is_active."""
    async with _db() as db:
        await db.execute("UPDATE nodes SET is_active = 1 - is_active WHERE id=?", (node_id,))
        await db.commit()


async def node_heartbeat(name: str, version: str = ""):
    async with _db() as db:
        await db.execute(
            "UPDATE nodes SET last_heartbeat=?, agent_version=? WHERE name=?",
            (time.time(), version, name)
        )
        await db.commit()


# --- Settings ---

async def get_setting(key: str, default: str = ""):
    async with _db() as db:
        rows = await db.execute_fetchall("SELECT value FROM settings WHERE key=?", (key,))
        return rows[0]["value"] if rows else default


async def set_setting(key: str, value: str):
    async with _db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value)
        )
        await db.commit()


# --- Admin ---

async def verify_admin(username: str, password: str):
    async with _db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM admin WHERE username=? AND password_hash=?",
            (username, hash_password(password))
        )
        return bool(rows)


async def update_admin_password(username: str, new_password: str):
    async with _db() as db:
        await db.execute(
            "UPDATE admin SET password_hash=? WHERE username=?",
            (hash_password(new_password), username)
        )
        await db.commit()


# --- Traffic ---

async def record_traffic_batch(node_name: str, traffic: dict):
    """
    Record traffic for multiple users in a single DB connection.
    traffic: {email: {up: int, down: int}, ...}
    """
    if not traffic:
        return
    async with _db() as db:
        # Resolve node once
        node_rows = await db.execute_fetchall(
            "SELECT id FROM nodes WHERE name=?", (node_name,)
        )
        if not node_rows:
            return
        nid = node_rows[0]["id"]

        for email, stats in traffic.items():
            up = max(0, int(stats.get("up", 0)))
            down = max(0, int(stats.get("down", 0)))
            if up == 0 and down == 0:
                continue
            user_rows = await db.execute_fetchall(
                "SELECT id FROM users WHERE username=?", (email,)
            )
            if not user_rows:
                continue
            uid = user_rows[0]["id"]
            await db.execute(
                "INSERT INTO traffic_log (user_id, node_id, upload, download) VALUES (?,?,?,?)",
                (uid, nid, up, down)
            )
            await db.execute(
                "UPDATE users SET data_used = data_used + ? WHERE id=?",
                (up + down, uid)
            )

        await db.commit()
