#!/usr/bin/env python3
"""
Promote a user to OFFICE role in the SQLite database.

Works even on Windows where the sqlite3 CLI is not installed, because it uses
Python's built-in sqlite3 module.

Usage (run from repo root):
  python scripts/make_office.py --phone 017xxxxxxxx
  python scripts/make_office.py --user-id 1
  python scripts/make_office.py --phone 017xxxxxxxx --db lostfound.sqlite3
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


def open_db_readwrite_no_create(db_path: Path) -> sqlite3.Connection:
    """
    Open SQLite DB in read-write mode without creating a new file.
    If the DB doesn't exist, raise a helpful error.
    """
    # Using URI mode prevents accidental creation of an empty DB file.
    uri = f"file:{db_path.as_posix()}?mode=rw"
    try:
        return sqlite3.connect(uri, uri=True)
    except sqlite3.OperationalError as e:
        raise SystemExit(
            f"[ERROR] Cannot open DB: {db_path}\n"
            f"Reason: {e}\n\n"
            f"Fix:\n"
            f"  - Run the app once to create the database and tables, or\n"
            f"  - Point to the correct DB with --db\n"
        )


def table_exists(con: sqlite3.Connection, table_name: str) -> bool:
    cur = con.cursor()
    cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table_name,),
    )
    return cur.fetchone() is not None


def promote_to_office(db_path: Path, phone: str | None, user_id: int | None) -> None:
    con = open_db_readwrite_no_create(db_path)

    try:
        if not table_exists(con, "users"):
            raise SystemExit(
                f"[ERROR] 'users' table not found in {db_path}.\n"
                f"Fix: start the app once so it creates/migrates tables, then rerun this script."
            )

        cur = con.cursor()

        if phone:
            cur.execute("UPDATE users SET role='office' WHERE phone=?", (phone,))
        else:
            cur.execute("UPDATE users SET role='office' WHERE id=?", (user_id,))

        con.commit()

        # Verify
        if phone:
            cur.execute("SELECT id, name, phone, role FROM users WHERE phone=?", (phone,))
        else:
            cur.execute("SELECT id, name, phone, role FROM users WHERE id=?", (user_id,))

        row = cur.fetchone()
        if not row:
            target = f"phone={phone}" if phone else f"id={user_id}"
            raise SystemExit(
                f"[ERROR] No user found for {target} in DB: {db_path}\n"
                f"Tip: run a quick check:\n"
                f"  SELECT id,name,phone,role FROM users;"
            )

        print("[OK] Updated user:", row)
        print("Now log out and log in again to see office pages (/office).")

    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Promote a user to office role.")
    parser.add_argument(
        "--db",
        default="lostfound.sqlite3",
        help="Path to SQLite DB (default: lostfound.sqlite3 in repo root)",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--phone", help="User phone number to promote (exact match).")
    group.add_argument("--user-id", type=int, help="User id to promote.")

    args = parser.parse_args()
    db_path = Path(args.db).expanduser().resolve()

    promote_to_office(db_path=db_path, phone=args.phone, user_id=args.user_id)


if __name__ == "__main__":
    main()
