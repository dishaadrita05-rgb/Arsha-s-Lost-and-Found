# app/db.py
import sqlite3
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

DB_PATH = Path(__file__).resolve().parent.parent / "lostfound.sqlite3"


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _column_exists(con: sqlite3.Connection, table: str, col: str) -> bool:
    cur = con.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in cur.fetchall()]
    return col in cols


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def init_db() -> None:
    con = connect()
    cur = con.cursor()

    # --------------------
    # users table (NEW)
    # --------------------
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL CHECK(role IN ('user','office')),
            name TEXT NOT NULL,
            phone TEXT NOT NULL UNIQUE,
            nid TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        """
    )
    con.commit()

    # --------------------
    # reports table
    # --------------------
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL CHECK(kind IN ('lost','found')),
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            location_text TEXT NOT NULL,
            event_time TEXT,
            created_at TEXT NOT NULL,
            extracted_json TEXT NOT NULL,

            clarify_key TEXT,
            clarify_answer TEXT,
            duplicate_of INTEGER
        );
        """
    )
    con.commit()

    # report migrations (safe auto-migrate)
    report_migrations = [
        ("handover_location", "ALTER TABLE reports ADD COLUMN handover_location TEXT"),
        ("contact_info", "ALTER TABLE reports ADD COLUMN contact_info TEXT"),
        ("manage_token", "ALTER TABLE reports ADD COLUMN manage_token TEXT"),

        # closing workflow
        ("is_closed", "ALTER TABLE reports ADD COLUMN is_closed INTEGER DEFAULT 0"),
        ("closed_at", "ALTER TABLE reports ADD COLUMN closed_at TEXT"),
        ("closed_claim_id", "ALTER TABLE reports ADD COLUMN closed_claim_id INTEGER"),

        # NEW: ownership
        ("owner_user_id", "ALTER TABLE reports ADD COLUMN owner_user_id INTEGER"),
    ]
    for col, ddl in report_migrations:
        if not _column_exists(con, "reports", col):
            cur.execute(ddl)
    con.commit()

    # --------------------
    # claims table
    # --------------------
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lost_report_id INTEGER NOT NULL,
            found_report_id INTEGER NOT NULL,
            proof_text TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected')),
            created_at TEXT NOT NULL
        );
        """
    )
    con.commit()

    # claim migrations
    claim_migrations = [
        # office-only snapshot columns
        ("claimer_name", "ALTER TABLE claims ADD COLUMN claimer_name TEXT"),
        ("claimer_phone", "ALTER TABLE claims ADD COLUMN claimer_phone TEXT"),
        ("claimer_nid", "ALTER TABLE claims ADD COLUMN claimer_nid TEXT"),
        ("office_note", "ALTER TABLE claims ADD COLUMN office_note TEXT"),

        # settlement tracking
        ("is_settled", "ALTER TABLE claims ADD COLUMN is_settled INTEGER DEFAULT 0"),
        ("settled_at", "ALTER TABLE claims ADD COLUMN settled_at TEXT"),

        # link claim to logged-in account
        ("claimer_user_id", "ALTER TABLE claims ADD COLUMN claimer_user_id INTEGER"),
    ]
    for col, ddl in claim_migrations:
        if not _column_exists(con, "claims", col):
            cur.execute(ddl)
    con.commit()

    # --------------------
    # disputes table
    # --------------------
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS disputes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    con.commit()

    # disputes migrations
    dispute_migrations = [
        ("reporter_user_id", "ALTER TABLE disputes ADD COLUMN reporter_user_id INTEGER"),
    ]
    for col, ddl in dispute_migrations:
        if not _column_exists(con, "disputes", col):
            cur.execute(ddl)
    con.commit()

    con.close()


# ========================
# Users
# ========================

def create_user(
    name: str,
    phone: str,
    nid_digits: str,
    password_hash: str,
    role: str = "user",
) -> int:
    con = connect()
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO users(role,name,phone,nid,password_hash,is_active,created_at)
        VALUES(?,?,?,?,?,?,?)
        """,
        (role, name, phone, nid_digits, password_hash, 1, now_utc_iso()),
    )
    con.commit()
    uid = int(cur.lastrowid)
    con.close()
    return uid


def get_user_by_phone(phone: str) -> Optional[Dict[str, Any]]:
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE phone=?", (phone,))
    row = cur.fetchone()
    con.close()
    return dict(row) if row else None


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE id=?", (user_id,))
    row = cur.fetchone()
    con.close()
    return dict(row) if row else None


def set_user_role(user_id: int, role: str) -> None:
    con = connect()
    cur = con.cursor()
    cur.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
    con.commit()
    con.close()


def update_user_password_hash(user_id: int, new_password_hash: str) -> None:
    con = connect()
    cur = con.cursor()
    cur.execute("UPDATE users SET password_hash=? WHERE id=?", (new_password_hash, user_id))
    con.commit()
    con.close()


# ========================
# Reports
# ========================

def insert_report(
    kind: str,
    title: str,
    description: str,
    location_text: str,
    event_time: Optional[str],
    extracted_json: str,
    duplicate_of: Optional[int] = None,
    owner_user_id: Optional[int] = None,
) -> int:
    con = connect()
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO reports(kind,title,description,location_text,event_time,created_at,extracted_json,duplicate_of,owner_user_id)
        VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (kind, title, description, location_text, event_time, now_utc_iso(), extracted_json, duplicate_of, owner_user_id),
    )
    con.commit()
    report_id = int(cur.lastrowid)
    con.close()
    return report_id


def get_report(report_id: int) -> Optional[Dict[str, Any]]:
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT * FROM reports WHERE id = ?", (report_id,))
    row = cur.fetchone()
    con.close()
    return dict(row) if row else None


def list_reports(kind: Optional[str] = None, include_closed: bool = False) -> List[Dict[str, Any]]:
    """
    By default, closed reports are hidden from lists (homepage, candidates).
    """
    con = connect()
    cur = con.cursor()

    if kind:
        if include_closed:
            cur.execute("SELECT * FROM reports WHERE kind=? ORDER BY id DESC", (kind,))
        else:
            cur.execute(
                "SELECT * FROM reports WHERE kind=? AND (is_closed IS NULL OR is_closed=0) ORDER BY id DESC",
                (kind,),
            )
    else:
        if include_closed:
            cur.execute("SELECT * FROM reports ORDER BY id DESC")
        else:
            cur.execute("SELECT * FROM reports WHERE (is_closed IS NULL OR is_closed=0) ORDER BY id DESC")

    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows


def list_reports_for_user(user_id: int, kind: Optional[str] = None, include_closed: bool = True) -> List[Dict[str, Any]]:
    con = connect()
    cur = con.cursor()

    if kind:
        if include_closed:
            cur.execute(
                "SELECT * FROM reports WHERE owner_user_id=? AND kind=? ORDER BY id DESC",
                (user_id, kind),
            )
        else:
            cur.execute(
                "SELECT * FROM reports WHERE owner_user_id=? AND kind=? AND (is_closed IS NULL OR is_closed=0) ORDER BY id DESC",
                (user_id, kind),
            )
    else:
        if include_closed:
            cur.execute(
                "SELECT * FROM reports WHERE owner_user_id=? ORDER BY id DESC",
                (user_id,),
            )
        else:
            cur.execute(
                "SELECT * FROM reports WHERE owner_user_id=? AND (is_closed IS NULL OR is_closed=0) ORDER BY id DESC",
                (user_id,),
            )

    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows


def update_extracted_json(report_id: int, extracted_json: str) -> None:
    con = connect()
    cur = con.cursor()
    cur.execute("UPDATE reports SET extracted_json=? WHERE id=?", (extracted_json, report_id))
    con.commit()
    con.close()


def set_clarification(report_id: int, key: str, answer: str) -> None:
    con = connect()
    cur = con.cursor()
    cur.execute(
        "UPDATE reports SET clarify_key=?, clarify_answer=? WHERE id=?",
        (key, answer, report_id),
    )
    con.commit()
    con.close()


def update_found_handover(found_id: int, handover_location: str, contact_info: str, manage_token: str) -> None:
    con = connect()
    cur = con.cursor()
    cur.execute(
        "UPDATE reports SET handover_location=?, contact_info=?, manage_token=? WHERE id=?",
        (handover_location, contact_info, manage_token, found_id),
    )
    con.commit()
    con.close()


def close_report(report_id: int, closed_claim_id: Optional[int] = None) -> None:
    con = connect()
    cur = con.cursor()
    cur.execute(
        "UPDATE reports SET is_closed=1, closed_at=?, closed_claim_id=? WHERE id=?",
        (now_utc_iso(), closed_claim_id, report_id),
    )
    con.commit()
    con.close()


# ========================
# Claims
# ========================

def create_claim(
    lost_id: int,
    found_id: int,
    proof_text: str,
    claimer_user_id: Optional[int] = None,
    claimer_name: str = "",
    claimer_phone: str = "",
    claimer_nid: str = "",
) -> int:
    """
    We store BOTH:
      - claimer_user_id (link to account)
      - snapshot fields (name/phone/nid) for office audit later
    """
    con = connect()
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO claims(
            lost_report_id,found_report_id,proof_text,status,created_at,
            claimer_user_id,claimer_name,claimer_phone,claimer_nid,
            is_settled,settled_at
        )
        VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            lost_id,
            found_id,
            proof_text,
            "pending",
            now_utc_iso(),
            claimer_user_id,
            claimer_name,
            claimer_phone,
            claimer_nid,
            0,
            None,
        ),
    )
    con.commit()
    cid = int(cur.lastrowid)
    con.close()
    return cid


def list_claims_for_found(found_id: int) -> List[Dict[str, Any]]:
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT * FROM claims WHERE found_report_id=? ORDER BY id DESC", (found_id,))
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows


def list_claims_for_user(user_id: int) -> List[Dict[str, Any]]:
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT * FROM claims WHERE claimer_user_id=? ORDER BY id DESC", (user_id,))
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows


def get_claim(claim_id: int) -> Optional[Dict[str, Any]]:
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT * FROM claims WHERE id=?", (claim_id,))
    row = cur.fetchone()
    con.close()
    return dict(row) if row else None


def set_claim_status(claim_id: int, status: str) -> None:
    con = connect()
    cur = con.cursor()
    cur.execute("UPDATE claims SET status=? WHERE id=?", (status, claim_id))
    con.commit()
    con.close()


def settle_claim(claim_id: int) -> None:
    con = connect()
    cur = con.cursor()
    cur.execute(
        "UPDATE claims SET is_settled=1, settled_at=? WHERE id=?",
        (now_utc_iso(), claim_id),
    )
    con.commit()
    con.close()


def get_approved_claim(lost_id: int, found_id: int) -> Optional[Dict[str, Any]]:
    con = connect()
    cur = con.cursor()
    cur.execute(
        """
        SELECT * FROM claims
        WHERE lost_report_id=? AND found_report_id=? AND status='approved'
        ORDER BY id DESC LIMIT 1
        """,
        (lost_id, found_id),
    )
    row = cur.fetchone()
    con.close()
    return dict(row) if row else None


def has_settled_claim_for_found(found_id: int) -> bool:
    con = connect()
    cur = con.cursor()
    cur.execute(
        "SELECT 1 FROM claims WHERE found_report_id=? AND is_settled=1 LIMIT 1",
        (found_id,),
    )
    row = cur.fetchone()
    con.close()
    return bool(row)


# ========================
# Disputes
# ========================

def create_dispute(claim_id: int, reason: str, reporter_user_id: Optional[int] = None) -> int:
    con = connect()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO disputes(claim_id,reason,created_at,reporter_user_id) VALUES(?,?,?,?)",
        (claim_id, reason, now_utc_iso(), reporter_user_id),
    )
    con.commit()
    did = int(cur.lastrowid)
    con.close()
    return did


def list_disputes_for_claim(claim_id: int) -> List[Dict[str, Any]]:
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT * FROM disputes WHERE claim_id=? ORDER BY id DESC", (claim_id,))
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows
