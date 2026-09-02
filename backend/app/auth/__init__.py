"""Auth helpers (mirrors src/lib/auth/index.ts)."""
import re
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt

from .. import config
from .. import db

SESSION_COOKIE = config.SESSION_COOKIE
SESSION_DURATION_MS = 1000 * 60 * 60 * 24 * 30  # 30 days

_SAFE = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


def _nanoid(length: int) -> str:
    return "".join(secrets.choice(_SAFE) for _ in range(length))


def sortable_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def to_public_user(user: dict | None) -> dict | None:
    if user is None:
        return None
    pub = {}
    for k, v in user.items():
        if k in ("passwordHash", "_id"):
            continue
        pub[k] = v.isoformat() if hasattr(v, "isoformat") else v
    if "id" not in pub and "_id" in user:
        pub["id"] = str(user["_id"])
    return pub


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("utf-8")


def verify_password(password: str, hash_: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hash_.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def signup(input_: dict) -> dict:
    email = (input_.get("email") or "").strip().lower()
    name = (input_.get("name") or "").strip()
    password = input_.get("password") or ""
    if not name or len(name) < 2:
        return {"ok": False, "error": "Please enter your name."}
    if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email):
        return {"ok": False, "error": "Please enter a valid email address."}
    if len(password) < 8:
        return {"ok": False, "error": "Password must be at least 8 characters."}
    if db.get_user_by_email(email):
        return {"ok": False, "error": "An account with this email already exists."}

    user = {
        "id": f"usr_{_nanoid(12)}",
        "name": name,
        "email": email,
        "passwordHash": hash_password(password),
        "createdAt": db.utcnow_iso(),
        "updatedAt": db.utcnow_iso(),
        "paymentPrefs": dict(config.DEFAULT_PAYMENT_PREFS),
    }
    db.create_user(user)
    return {"ok": True, "data": to_public_user(user)}


def login(input_: dict) -> dict:
    email = (input_.get("email") or "").strip().lower()
    password = input_.get("password") or ""
    user = db.get_user_by_email(email)
    if not user or not verify_password(password, user.get("passwordHash") or ""):
        return {"ok": False, "error": "Invalid email or password."}
    return {"ok": True, "data": user}


def create_user_session(user_id: str, remember: bool) -> dict:
    db.delete_expired_sessions()
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    duration = SESSION_DURATION_MS if remember else 1000 * 60 * 60 * 4
    session = {
        "id": f"ses_{_nanoid(20)}",
        "userId": user_id,
        "createdAt": sortable_iso(now_ms),
        "expiresAt": sortable_iso(now_ms + duration),
    }
    db.create_session(session)
    return session


def _expired(session: dict) -> bool:
    expires = session.get("expiresAt") or ""
    try:
        parsed = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= parsed
    except Exception:
        # numeric epoch-seconds fallback
        try:
            val = float(str(expires).replace("Z", "+00:00"))
            return datetime.now(timezone.utc).timestamp() >= val
        except Exception:
            return True


def get_current_user_from_cookie(cookie_value: str | None) -> dict | None:
    if not cookie_value:
        return None
    session = db.get_session(cookie_value)
    if not session:
        return None
    if _expired(session):
        db.delete_session(cookie_value)
        return None
    return db.get_user_by_id(session.get("userId") or "")


def logout_session(session_id: str | None) -> None:
    if session_id:
        db.delete_session(session_id)


def request_password_reset(email: str) -> dict:
    user = db.get_user_by_email(email.strip().lower())
    if not user:
        return {"ok": True, "data": {"token": ""}}
    token = _nanoid(40)
    db.create_reset(token, user["id"])
    return {"ok": True, "data": {"token": token}}


def is_valid_reset_token(token: str) -> bool:
    if not token:
        return False
    reset = db.get_reset(token)
    if not reset or reset.get("used"):
        return False
    return not _expired({"expiresAt": reset.get("expiresAt")})


def reset_password(token: str, new_password: str) -> dict:
    if not token or len(new_password) < 8:
        return {"ok": False, "error": "Password must be at least 8 characters."}
    reset = db.get_reset(token)
    if not reset or reset.get("used") or _expired({"expiresAt": reset.get("expiresAt")}):
        return {"ok": False, "error": "This reset link is invalid or has expired."}
    user = db.get_user_by_id(reset.get("userId") or "")
    if not user:
        return {"ok": False, "error": "Account not found."}
    db.update_user(user["id"], {"passwordHash": hash_password(new_password)})
    db.mark_reset_used(token)
    return {"ok": True, "data": None}