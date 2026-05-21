# Akshay-core
__author__ = "Akshay-core"

# FILE: users/auth.py
import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta
from app.database.sqlite_db import get_conn, init_db
from app.config import SESSION_TTL_HOURS
from app.utils.logger import get_logger

logger = get_logger("auth")


def _hash_password(password: str) -> str:
    salt = "brain_local_salt_v1"
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest()


def create_user(username: str, password: str) -> dict:
    init_db()
    if len(username) < 3:
        return {"success": False, "error": "Username too short"}
    if len(password) < 6:
        return {"success": False, "error": "Password too short (min 6 chars)"}
    hashed = _hash_password(password)
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username.strip().lower(), hashed)
            )
        logger.info(f"User created: {username}")
        return {"success": True}
    except sqlite3.IntegrityError:
        return {"success": False, "error": "Username already exists"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def login(username: str, password: str) -> dict:
    init_db()
    hashed = _hash_password(password)
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT id, username FROM users WHERE username = ? AND password_hash = ?",
                (username.strip().lower(), hashed)
            ).fetchone()
            if not row:
                return {"success": False, "error": "Invalid credentials"}

            user_id = row["id"]
            token = secrets.token_hex(32)
            expires = datetime.now() + timedelta(hours=SESSION_TTL_HOURS)
            conn.execute(
                "INSERT INTO sessions (id, user_id, expires_at) VALUES (?, ?, ?)",
                (token, user_id, expires.isoformat())
            )
            conn.execute(
                "UPDATE users SET last_login = ? WHERE id = ?",
                (datetime.now().isoformat(), user_id)
            )
            return {
                "success": True,
                "token": token,
                "user_id": str(user_id),
                "username": row["username"]
            }
    except Exception as e:
        logger.error(f"Login error: {e}")
        return {"success": False, "error": str(e)}


def validate_session(token: str) -> dict:
    try:
        with get_conn() as conn:
            row = conn.execute(
                """SELECT s.user_id, u.username, s.expires_at
                   FROM sessions s JOIN users u ON s.user_id = u.id
                   WHERE s.id = ?""",
                (token,)
            ).fetchone()
            if not row:
                return {"valid": False}
            if datetime.now() > datetime.fromisoformat(row["expires_at"]):
                return {"valid": False, "reason": "expired"}
            return {
                "valid": True,
                "user_id": str(row["user_id"]),
                "username": row["username"]
            }
    except Exception:
        return {"valid": False}


def logout(token: str):
    try:
        with get_conn() as conn:
            conn.execute("DELETE FROM sessions WHERE id = ?", (token,))
    except Exception:
        pass
