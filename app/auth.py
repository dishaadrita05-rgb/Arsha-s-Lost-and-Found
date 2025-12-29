# app/auth.py
from __future__ import annotations

from typing import Optional
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# bcrypt has a hard limit: it only uses the first 72 BYTES.
# Some backends throw ValueError if longer, so we enforce it safely.
BCRYPT_MAX_BYTES = 72


def normalize_phone(phone: str) -> str:
    """
    Keep only digits, remove spaces, +, etc.
    """
    return "".join(ch for ch in (phone or "") if ch.isdigit())


def normalize_nid(nid: str) -> str:
    """
    Keep only digits.
    """
    return "".join(ch for ch in (nid or "") if ch.isdigit())


def validate_nid(nid_digits: str) -> bool:
    return len(nid_digits) in (13, 18)


def _check_password_length(password: str) -> None:
    if password is None:
        raise ValueError("Password is required.")

    # IMPORTANT: count bytes, not characters (Bangla/emoji etc. can be multi-byte)
    if len(password.encode("utf-8")) > BCRYPT_MAX_BYTES:
        raise ValueError("Password too long. Use a shorter password (max 72 bytes).")


def hash_password(password: str) -> str:
    _check_password_length(password)
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        # If password is too long, immediately fail (and avoid backend errors)
        if password is None:
            return False
        if len(password.encode("utf-8")) > BCRYPT_MAX_BYTES:
            return False
        return pwd_context.verify(password, password_hash)
    except Exception:
        return False


def session_login(request, user_id: int) -> None:
    request.session["user_id"] = int(user_id)


def session_logout(request) -> None:
    try:
        request.session.clear()
    except Exception:
        # not fatal
        request.session.pop("user_id", None)


def session_user_id(request) -> Optional[int]:
    uid = request.session.get("user_id")
    try:
        return int(uid) if uid is not None else None
    except Exception:
        return None
