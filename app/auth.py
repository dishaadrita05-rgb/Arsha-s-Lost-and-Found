# app/auth.py
from __future__ import annotations

from typing import Optional

from passlib.context import CryptContext

# bcrypt processes only the first 72 BYTES of a password.
# Many libraries raise an error if it's longer than 72 bytes.
BCRYPT_MAX_BYTES = 72

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def normalize_phone(phone: str) -> str:
    """Keep only digits, remove spaces, +, etc."""
    return "".join(ch for ch in (phone or "") if ch.isdigit())


def normalize_nid(nid: str) -> str:
    """Keep only digits from NID input."""
    return "".join(ch for ch in (nid or "") if ch.isdigit())


def validate_nid(nid_digits: str) -> bool:
    """Bangladesh NID: 13 or 18 digits."""
    return bool(nid_digits) and (len(nid_digits) == 13 or len(nid_digits) == 18)


def _check_password_length(password: str) -> None:
    if password is None:
        raise ValueError("Password is required.")

    # IMPORTANT: count bytes, not characters (Bangla/emoji etc. can be multi-byte)
    if len(password.encode("utf-8")) > BCRYPT_MAX_BYTES:
        pw_len = len(password.encode("utf-8"))
        raise ValueError(
            f"Password is too long ({pw_len} bytes). Bcrypt only supports up to 72 bytes. "
            "Please use a shorter password. Tip: emoji/Bangla letters count as multiple bytes."
        )


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
