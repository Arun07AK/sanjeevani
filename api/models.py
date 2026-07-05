"""SQLite data layer for the Sanjeevani prototype. stdlib sqlite3 only, no ORM."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB = "data/sanjeevani.db"

ACCOUNT_COLUMNS = (
    "id", "name", "state", "language", "phone_type", "whatsapp_registered",
    "months_since_txn", "months_since_open", "never_transacted", "kyc_age_months",
    "balance_inr", "dbt_linked", "dbt_interrupted", "duplicate_suspect",
    "opted_out", "status", "risk_score", "blocker",
)


def _db_path() -> Path:
    raw = os.environ.get("SANJEEVANI_DB", _DEFAULT_DB)
    p = Path(raw)
    return p if p.is_absolute() else _REPO_ROOT / p


def get_conn() -> sqlite3.Connection:
    """Return a new connection with Row factory and WAL enabled."""
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    name TEXT,
    state TEXT,
    language TEXT,
    phone_type TEXT,
    whatsapp_registered INTEGER,
    months_since_txn INTEGER,
    months_since_open INTEGER,
    never_transacted INTEGER,
    kyc_age_months INTEGER,
    balance_inr REAL,
    dbt_linked INTEGER,
    dbt_interrupted INTEGER,
    duplicate_suspect INTEGER,
    opted_out INTEGER DEFAULT 0,
    status TEXT,
    risk_score INTEGER,
    blocker TEXT
);

CREATE TABLE IF NOT EXISTS journey_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT,
    ts TEXT,
    attempt INTEGER,
    step TEXT,
    detail TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT,
    ts TEXT,
    channel TEXT,
    lang TEXT,
    body TEXT,
    audio_path TEXT,
    ai_disclosure INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS consent_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT,
    ts TEXT,
    action TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def init_db() -> None:
    """Create all tables if they do not exist."""
    conn = get_conn()
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def reset_db() -> None:
    """Drop and recreate all tables."""
    conn = get_conn()
    try:
        for table in ("journey_events", "messages", "consent_events", "settings", "accounts"):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_accounts(status: str | None = None, limit: int | None = None) -> list[dict]:
    """Return accounts, optionally filtered by status and capped by limit."""
    sql = "SELECT * FROM accounts"
    params: list = []
    if status is not None:
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY id"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    conn = get_conn()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_account(account_id: str) -> dict | None:
    """Return a single account by id, or None."""
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def insert_account(account: dict) -> None:
    """Insert an account from a dict keyed by column name."""
    cols = [c for c in ACCOUNT_COLUMNS if c in account]
    placeholders = ", ".join("?" for _ in cols)
    sql = f"INSERT INTO accounts ({', '.join(cols)}) VALUES ({placeholders})"
    conn = get_conn()
    try:
        conn.execute(sql, [account[c] for c in cols])
        conn.commit()
    finally:
        conn.close()


def update_account(account_id: str, **fields) -> None:
    """Update whitelisted columns on an account."""
    updates = {k: v for k, v in fields.items() if k in ACCOUNT_COLUMNS and k != "id"}
    if not updates:
        return
    assignments = ", ".join(f"{k} = ?" for k in updates)
    sql = f"UPDATE accounts SET {assignments} WHERE id = ?"
    conn = get_conn()
    try:
        conn.execute(sql, [*updates.values(), account_id])
        conn.commit()
    finally:
        conn.close()


def insert_event(account_id: str, step: str, detail: dict, attempt: int = 1) -> int:
    """Record a journey event; returns the new event id."""
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO journey_events (account_id, ts, attempt, step, detail) VALUES (?, ?, ?, ?, ?)",
            (account_id, _now(), attempt, step, json.dumps(detail)),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def list_events(account_id: str) -> list[dict]:
    """Return journey events for an account with detail JSON-decoded."""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM journey_events WHERE account_id = ? ORDER BY id",
            (account_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["detail"] = json.loads(d["detail"]) if d["detail"] else None
            out.append(d)
        return out
    finally:
        conn.close()


def insert_message(
    account_id: str, channel: str, lang: str, body: str, audio_path: str | None = None
) -> int:
    """Record an outbound/inbound message; returns the new message id."""
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO messages (account_id, ts, channel, lang, body, audio_path) VALUES (?, ?, ?, ?, ?, ?)",
            (account_id, _now(), channel, lang, body, audio_path),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def list_messages(account_id: str) -> list[dict]:
    """Return messages for an account in id order."""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM messages WHERE account_id = ? ORDER BY id",
            (account_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def insert_consent(account_id: str, action: str) -> int:
    """Record a consent event ('grant' | 'opt_out'); returns the new id."""
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO consent_events (account_id, ts, action) VALUES (?, ?, ?)",
            (account_id, _now(), action),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def get_setting(key: str, default: str | None = None) -> str | None:
    """Return a settings value by key, or default if absent."""
    conn = get_conn()
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default
    finally:
        conn.close()


def set_setting(key: str, value: str) -> None:
    """Upsert a settings key/value pair."""
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()
    finally:
        conn.close()
