#!/usr/bin/env python3
"""
Make an existing user an office user (role='office').

Why this exists:
- Many Windows machines don't have the sqlite3 CLI installed.
- But Python can still edit the SQLite DB using the built-in sqlite3 module.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def normalize_phone(phone: str) -> str:
    # Simple normalization: keep digits, keep leading 0 if present
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    # If someone types 88017..., reduce to last 11 digits if it looks like BD phone
    if len(digits) > 11 and digits.endswith(digits[-11:]):
        digits = digits[-11:]
    return digits


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    default_db = root / "lostfound.sqlite3"

    p = argparse.ArgumentParser()
    p.add_argument("--phone", required=True, help="User phone (example: 017xxxxxxxx)")
    p.add_argument("--db", default=str(default_db), help="Path to DB (default: ./lostfound.sqlite3)")
    args = p.parse_args()

    phone = normalize_phone(args.phone)
    db_path = Path(args.db).resolve()

    if not db_path.exists():
        print(f"[ERROR] DB not found: {db_path}")
        print("Run the app once to auto-create the DB, then try again.")
        return 2

    con = sqlite3.connect(str(db_path))
    cur = con.cursor()

    # Make sure users table exists
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    if not cur.fetchone():
        print("[ERROR] 'users' table not found. Your DB doesn't look initialized.")
        print("Run the app once (it runs init_db on startup), then try again.")
        con.close()
        return 3

    cur.execute("SELECT id, name, phone, role FROM users WHERE phone=?", (phone,))
    row = cur.fetchone()
    if not row:
        print(f"[ERROR] No user found with phone={phone}")
        print("Register that phone in the app first, then re-run this script.")
        con.close()
        return 4

    user_id, name, phone_db, role = row
    if role == "office":
        print(f"[OK] Already office: id={user_id}, name={name}, phone={phone_db}")
        con.close()
        return 0

    cur.execute("UPDATE users SET role='office' WHERE id=?", (user_id,))
    con.commit()
    con.close()

    print(f"[OK] Updated to office: id={user_id}, name={name}, phone={phone_db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
