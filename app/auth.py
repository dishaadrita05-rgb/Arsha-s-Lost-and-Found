# app/auth.py
from __future__ import annotations

from typing import Optional
from passlib.context import CryptContext

"""
Password hashing:

bcrypt has a hard limit of 72 BYTES. That causes errors for long passwords and
for multi-byte characters (emoji, Bangla, etc.).

Fix:
- Use pbkdf2_sha256 as the DEFAULT scheme (supports long passwords).
- Keep bcrypt to verify existing users who registered before this change.
- On successful login, auto-upgrade old hashes to pbkdf2_sha256.
"""

pwd_context = CryptContext(
    schemes=["pbkdf2_sha256", "bcrypt"],
    deprecated="auto",
)


def normalize_phone(phone: str) -> str:
    """Keep only digits, remove spaces, +, etc."""
    return "".join(ch for ch in (phone or "") if ch.isdigit())


def normalize_nid(nid: str) -> str:
    """Keep only digits."""
    return "".join(ch for ch in (nid or "") if ch.isdigit())


def validate_nid(nid_digits: str) -> bool:
    return len(nid_digits) in (13, 18)


def hash_password(password: str) -> str:
    if password is None or not str(password).strip():
        raise ValueError("Password is required.")
    # pbkdf2_sha256 supports long passwords safely.
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        if password is None or password_hash is None:
            return False
        return pwd_context.verify(password, password_hash)
    except Exception:
        return False


def password_hash_needs_update(password_hash: str) -> bool:
    try:
        if not password_hash:
            return False
        return pwd_context.needs_update(password_hash)
    except Exception:
        return False


def session_login(request, user_id: int) -> None:
    request.session["user_id"] = int(user_id)


def session_logout(request) -> None:
    try:
        request.session.clear()
    except Exception:
        request.session.pop("user_id", None)


def session_user_id(request) -> Optional[int]:
    uid = request.session.get("user_id")
    try:
        return int(uid) if uid is not None else None
    except Exception:
        return None
