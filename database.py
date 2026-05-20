import sqlite3
import os

DB_PATH = os.getenv("DB_PATH", "/tmp/viralforge.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            email       TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role        TEXT DEFAULT 'user',
            active      INTEGER DEFAULT 1,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
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
    conn.commit()
    conn.close()


def get_user_by_email(email: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower(),)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_users():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, email, role, active, created_at FROM users ORDER BY created_at"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_user(email: str, password_hash: str, role: str = "user") -> bool:
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (email, password_hash, role) VALUES (?, ?, ?)",
            (email.lower(), password_hash, role),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def upsert_admin(email: str, password_hash: str):
    """Create admin if not exists, or update their password hash."""
    conn = get_db()
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
    conn.commit()
    conn.close()


def delete_user(user_id: int):
    conn = get_db()
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()


def toggle_user_active(user_id: int):
    conn = get_db()
    conn.execute(
        "UPDATE users SET active = CASE WHEN active = 1 THEN 0 ELSE 1 END WHERE id = ?",
        (user_id,),
    )
    conn.commit()
    conn.close()


def update_password(user_id: int, password_hash: str):
    conn = get_db()
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))
    conn.commit()
    conn.close()


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
    conn.commit()
    conn.close()


def delete_api_key(user_id: int, provider: str):
    conn = get_db()
    conn.execute(
        "DELETE FROM api_keys WHERE user_id = ? AND provider = ?", (user_id, provider)
    )
    conn.commit()
    conn.close()
