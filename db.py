"""SQLite storage: leads, dedup, processed-email tracking, key/value cursors."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import config
from models import Lead, LeadScore

try:
    from rapidfuzz import fuzz

    def _similarity(a: str, b: str) -> float:
        return fuzz.token_set_ratio(a, b)
except ImportError:  # graceful fallback, no hard dependency
    from difflib import SequenceMatcher

    def _similarity(a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio() * 100


SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY,
    url_hash TEXT UNIQUE NOT NULL,
    url TEXT NOT NULL,
    source TEXT NOT NULL,
    author TEXT,
    lang TEXT,
    posted_at TEXT,
    fetched_at TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',  -- new|duplicate|gated_out|scored|notified|digest_pending|digested|error
    score INTEGER,
    category TEXT,
    work_type TEXT,
    summary TEXT,
    budget TEXT,
    red_flags TEXT,
    reasoning TEXT,
    extra_urls TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_leads_fetched ON leads(fetched_at);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);

CREATE TABLE IF NOT EXISTS seen_emails (
    message_id TEXT PRIMARY KEY,
    seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS replies (
    id INTEGER PRIMARY KEY,
    lead_id INTEGER UNIQUE NOT NULL REFERENCES leads(id),
    channel TEXT NOT NULL,            -- reddit | freelancer
    message TEXT NOT NULL,
    meta TEXT DEFAULT '{}',           -- channel-specific: bid amount/period, dm/comment...
    status TEXT NOT NULL DEFAULT 'pending',  -- pending|approved|sent|failed|skipped
    error TEXT,
    created_at TEXT NOT NULL,
    sent_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_replies_status ON replies(status);

-- WhatsApp groups are NOT leads: this is a discovery list of invite links for
-- the user to join BY HAND (the account is never automated). Populated by
-- discover_whatsapp_groups.py from stored post text + public search.
CREATE TABLE IF NOT EXISTS whatsapp_groups (
    code TEXT PRIMARY KEY,            -- invite code from chat.whatsapp.com/<code>
    url TEXT NOT NULL,
    name TEXT,                        -- og:title when the invite is live
    status TEXT NOT NULL DEFAULT 'pending',  -- pending|live|revoked|unknown
    relevance INTEGER DEFAULT 0,      -- keyword hits in the group name
    region TEXT,                      -- IL (Hebrew name) | GLOBAL
    found_via TEXT,                   -- leads_db | reddit_search | ddg
    first_seen TEXT NOT NULL,
    last_checked TEXT,
    joined INTEGER DEFAULT 0,
    notified INTEGER DEFAULT 0        -- per-row, NOT a global cursor: a group can be
                                      -- found today and validated days later once it
                                      -- clears the per-run validation cap
);
CREATE INDEX IF NOT EXISTS idx_wa_status ON whatsapp_groups(status);

-- Facebook groups DISCOVERED by discover_fb_groups.py (distinct from the curated
-- config.FACEBOOK_GROUPS list the scraper reads). Public ones graduate into that
-- config; private ones become a join list for the user - the agent never sends a
-- join request, because automating the user's FB account risks a ban.
CREATE TABLE IF NOT EXISTS facebook_groups (
    slug TEXT PRIMARY KEY,            -- facebook.com/groups/<slug>
    url TEXT NOT NULL,
    name TEXT,                        -- og:title / page title once probed
    status TEXT NOT NULL DEFAULT 'pending',  -- pending|public|private|gone|unknown
    relevance INTEGER DEFAULT 0,      -- keyword hits in the group name
    region TEXT,                      -- IL (Hebrew name) | GLOBAL
    found_via TEXT,                   -- leads_db | ddg | gmail | config
    first_seen TEXT NOT NULL,
    last_checked TEXT,
    in_config INTEGER DEFAULT 0,      -- already in config.FACEBOOK_GROUPS
    joined INTEGER DEFAULT 0,         -- user joined it (private ones)
    notified INTEGER DEFAULT 0        -- per-row, same reasoning as whatsapp_groups
);
CREATE INDEX IF NOT EXISTS idx_fb_status ON facebook_groups(status);
"""

# Columns added after a table first shipped. ALTER TABLE ADD COLUMN is cheap and
# idempotent here (sqlite has no ADD COLUMN IF NOT EXISTS), so just try each one.
_MIGRATIONS = [
    ("whatsapp_groups", "notified", "INTEGER DEFAULT 0"),
]


def _migrate(conn: sqlite3.Connection) -> None:
    for table, column, decl in _MIGRATIONS:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        except sqlite3.OperationalError:
            pass  # already there
    conn.commit()


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def insert_lead(conn: sqlite3.Connection, lead: Lead) -> int | None:
    """Insert a lead. Returns row id, or None if duplicate (by URL or fuzzy text)."""
    h = url_hash(lead.url)
    exists = conn.execute("SELECT id FROM leads WHERE url_hash=?", (h,)).fetchone()
    if exists:
        return None

    # Fuzzy dedup against the last 7 days (cross-posted FB group posts etc.)
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    recent = conn.execute(
        "SELECT id, raw_text FROM leads WHERE fetched_at > ? ORDER BY id DESC LIMIT 400",
        (week_ago,),
    ).fetchall()
    text = lead.raw_text[:1500]
    if len(text) > 60:  # too-short texts fuzz-match everything
        for row in recent:
            if _similarity(text, row["raw_text"][:1500]) >= config.DEDUP_SIMILARITY:
                conn.execute(
                    "UPDATE leads SET extra_urls = extra_urls || ' ' || ? WHERE id=?",
                    (lead.url, row["id"]),
                )
                conn.commit()
                return None

    cur = conn.execute(
        """INSERT INTO leads (url_hash, url, source, author, lang, posted_at, fetched_at, raw_text)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            h, lead.url, lead.source, lead.author, lead.lang,
            lead.posted_at.isoformat() if lead.posted_at else None,
            datetime.now(timezone.utc).isoformat(),
            lead.raw_text,
        ),
    )
    conn.commit()
    return cur.lastrowid


def set_status(conn: sqlite3.Connection, lead_id: int, status: str) -> None:
    conn.execute("UPDATE leads SET status=? WHERE id=?", (status, lead_id))
    conn.commit()


def save_score(conn: sqlite3.Connection, lead_id: int, s: LeadScore, status: str) -> None:
    conn.execute(
        """UPDATE leads SET score=?, category=?, work_type=?, summary=?, budget=?,
           red_flags=?, reasoning=?, status=? WHERE id=?""",
        (
            s.score, s.category, s.work_type, s.summary, s.budget_mentioned,
            json.dumps(s.red_flags, ensure_ascii=False), s.reasoning, status, lead_id,
        ),
    )
    conn.commit()


def digest_pending(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM leads WHERE status='digest_pending' ORDER BY score DESC"
    ).fetchall()


def email_seen(conn: sqlite3.Connection, message_id: str) -> bool:
    return bool(
        conn.execute("SELECT 1 FROM seen_emails WHERE message_id=?", (message_id,)).fetchone()
    )


def mark_email_seen(conn: sqlite3.Connection, message_id: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO seen_emails (message_id, seen_at) VALUES (?,?)",
        (message_id, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def queue_reply(conn: sqlite3.Connection, lead_id: int, channel: str,
                message: str, meta: dict) -> int | None:
    """Queue a reply draft. Returns row id, or None if this lead already has one."""
    try:
        cur = conn.execute(
            "INSERT INTO replies (lead_id, channel, message, meta, created_at) "
            "VALUES (?,?,?,?,?)",
            (lead_id, channel, message, json.dumps(meta, ensure_ascii=False),
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:  # one reply per lead, ever
        return None


def replies_by_status(conn: sqlite3.Connection, status: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT r.*, l.source, l.url, l.score, l.summary FROM replies r "
        "JOIN leads l ON l.id = r.lead_id WHERE r.status=? ORDER BY r.id",
        (status,),
    ).fetchall()


def set_reply_status(conn: sqlite3.Connection, reply_id: int, status: str,
                     error: str | None = None) -> None:
    conn.execute(
        "UPDATE replies SET status=?, error=?, "
        "sent_at=CASE WHEN ?='sent' THEN ? ELSE sent_at END WHERE id=?",
        (status, error, status, datetime.now(timezone.utc).isoformat(), reply_id),
    )
    conn.commit()


def replies_sent_today(conn: sqlite3.Connection) -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT COUNT(*) c FROM replies WHERE status='sent' AND sent_at >= ?",
        (today,),
    ).fetchone()
    return row["c"]


def kv_get(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def kv_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO kv (key, value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()
