import os
import sqlite3
import httpx

TURSO_URL   = os.getenv("TURSO_URL", "")
TURSO_TOKEN = os.getenv("TURSO_TOKEN", "")
DB_PATH     = os.getenv("DB_PATH", "/tmp/viralforge.db")


# ── Turso HTTP adapter ────────────────────────────────────────────────────────

class _Rows:
    """Wraps Turso API results to behave like sqlite3 cursor."""
    def __init__(self, cols, raw_rows):
        self._rows = []
        for raw in raw_rows:
            row = {}
            for i, col in enumerate(cols):
                cell = raw[i]
                row[col] = None if cell["type"] == "null" else cell["value"]
            self._rows.append(row)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class TursoConn:
    """Drop-in sqlite3 replacement using Turso HTTP API."""
    def __init__(self, url, token):
        self._url = url.replace("libsql://", "https://") + "/v2/pipeline"
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _encode(self, v):
        if v is None:
            return {"type": "null", "value": None}
        if isinstance(v, int):
            return {"type": "integer", "value": str(v)}
        if isinstance(v, float):
            return {"type": "float", "value": v}
        return {"type": "text", "value": str(v)}

    def execute(self, sql, params=()):
        payload = {
            "requests": [
                {
                    "type": "execute",
                    "stmt": {
                        "sql": sql,
                        "args": [self._encode(p) for p in params],
                    },
                },
                {"type": "close"},
            ]
        }
        resp = httpx.post(self._url, json=payload, headers=self._headers, timeout=30.0)
        resp.raise_for_status()
        item = resp.json()["results"][0]
        if item["type"] == "error":
            msg = item.get("error", {}).get("message", "DB error")
            if "UNIQUE" in msg or "SQLITE_CONSTRAINT" in msg:
                raise sqlite3.IntegrityError(msg)
            raise Exception(msg)
        result = item["response"]["result"]
        cols   = [c["name"] for c in result["cols"]]
        return _Rows(cols, result["rows"])

    def commit(self): pass   # Turso auto-commits each statement
    def close(self):  pass


# ── Connection factory ────────────────────────────────────────────────────────

def get_db():
    if TURSO_URL and TURSO_TOKEN:
        return TursoConn(TURSO_URL, TURSO_TOKEN)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _commit(conn):
    conn.commit()   # no-op for TursoConn, real commit for sqlite3


# ── Schema ────────────────────────────────────────────────────────────────────

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            email            TEXT UNIQUE NOT NULL,
            password_hash    TEXT NOT NULL,
            role             TEXT DEFAULT 'user',
            active           INTEGER DEFAULT 1,
            trial_expires_at TIMESTAMP DEFAULT NULL,
            created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    try:
        conn.execute("ALTER TABLE users ADD COLUMN trial_expires_at TIMESTAMP DEFAULT NULL")
        _commit(conn)
    except Exception:
        pass
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            provider   TEXT NOT NULL,
            api_key    TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, provider)
        )
    """)
    _commit(conn)
    conn.close()


# ── Users ─────────────────────────────────────────────────────────────────────

def get_user_by_email(email: str):
    conn = get_db()
    row  = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower(),)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_users():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, email, role, active, trial_expires_at, created_at FROM users ORDER BY created_at"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_user(email: str, password_hash: str, role: str = "user", trial_expires_at=None) -> bool:
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (email, password_hash, role, trial_expires_at) VALUES (?, ?, ?, ?)",
            (email.lower(), password_hash, role, trial_expires_at),
        )
        _commit(conn)
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def upsert_admin(email: str, password_hash: str):
    conn     = get_db()
    existing = conn.execute("SELECT id FROM users WHERE email = ?", (email.lower(),)).fetchone()
    if existing:
        conn.execute(
            "UPDATE users SET password_hash = ?, role = 'admin', active = 1 WHERE email = ?",
            (password_hash, email.lower()),
        )
    else:
        conn.execute(
            "INSERT INTO users (email, password_hash, role, active) VALUES (?, ?, 'admin', 1)",
            (email.lower(), password_hash),
        )
    _commit(conn)
    conn.close()


def delete_user(user_id: int):
    conn = get_db()
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    _commit(conn)
    conn.close()


def toggle_user_active(user_id: int):
    conn = get_db()
    conn.execute(
        "UPDATE users SET active = CASE WHEN active = 1 THEN 0 ELSE 1 END WHERE id = ?",
        (user_id,),
    )
    _commit(conn)
    conn.close()


def update_password(user_id: int, password_hash: str):
    conn = get_db()
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))
    _commit(conn)
    conn.close()


# ── API keys ──────────────────────────────────────────────────────────────────

def get_user_api_keys(user_id: int) -> dict:
    conn = get_db()
    rows = conn.execute(
        "SELECT provider, api_key FROM api_keys WHERE user_id = ?", (user_id,)
    ).fetchall()
    conn.close()
    return {row["provider"]: row["api_key"] for row in rows}


def save_api_key(user_id: int, provider: str, api_key: str):
    conn = get_db()
    conn.execute(
        "INSERT INTO api_keys (user_id, provider, api_key) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id, provider) DO UPDATE SET api_key = excluded.api_key, "
        "updated_at = CURRENT_TIMESTAMP",
        (user_id, provider, api_key),
    )
    _commit(conn)
    conn.close()


def delete_api_key(user_id: int, provider: str):
    conn = get_db()
    conn.execute(
        "DELETE FROM api_keys WHERE user_id = ? AND provider = ?", (user_id, provider)
    )
    _commit(conn)
    conn.close()
