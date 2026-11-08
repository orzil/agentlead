"""Drip Or's subcontracting emails to Israeli CV/ML consultancies (2026-11-08).

The outbound batch used to stop at "draft sent to Or on Telegram" - 43 drafts,
0 sent. Now the agent sends them itself from Or's Gmail, slowly and politely:

- one email per company, ever (kv `agency_mail_sent:<address>`)
- Sun-Thu, 09:00-16:00 Israel time, at most AGENCY_MAIL_PER_DAY a day, at least
  AGENCY_MAIL_GAP_MIN minutes apart - a person writing, not a blast
- every sent email is copied to Or on Telegram, so a reply is never a surprise
- kill switch: AGENCY_MAIL=0 in .env, or `python -X utf8 agency_mail.py --off`

The queue is `agency_outreach.jsonl` (gitignored: {name, email, subject, body}
per line), written by hand from the companies' own sites. It runs from the
home loop only (reddit_loop.pyw): the cloud has neither the queue nor SMTP.

Usage:  python -X utf8 agency_mail.py --status | --off | --on | --send-now
"""
from __future__ import annotations

import argparse
import html
import json
import smtplib
import time
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path
from zoneinfo import ZoneInfo

import config
import db
import notifier

QUEUE = Path(__file__).with_name("agency_outreach.jsonl")
IL = ZoneInfo("Asia/Jerusalem")
PER_DAY = int(config.env("AGENCY_MAIL_PER_DAY", "4"))
GAP_MIN = int(config.env("AGENCY_MAIL_GAP_MIN", "50"))
ENABLED = config.env("AGENCY_MAIL", "1") in ("1", "true", "yes")
SENDER_NAME = "Or Zilberberg"


def _queue() -> list[dict]:
    if not QUEUE.exists():
        return []
    return [json.loads(l) for l in QUEUE.read_text(encoding="utf-8").splitlines() if l.strip()]


def _pending(conn) -> list[dict]:
    return [q for q in _queue()
            if not db.kv_get(conn, f"agency_mail_sent:{q['email'].lower()}", "")]


def _in_window(now: datetime) -> bool:
    # Israeli work week: Sunday (6) through Thursday (3)
    return now.weekday() in (6, 0, 1, 2, 3) and 9 <= now.hour < 16


def _send(item: dict) -> None:
    msg = EmailMessage()
    msg["From"] = formataddr((SENDER_NAME, config.IMAP_USER))
    msg["To"] = item["email"]
    msg["Subject"] = item["subject"]
    msg["Message-ID"] = make_msgid(domain="gmail.com")
    msg.set_content(item["body"])
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
        s.login(config.IMAP_USER, config.IMAP_PASSWORD)
        s.send_message(msg)


def send_one(conn, force: bool = False) -> str | None:
    """Send the next queued email if the pacing allows. Returns the company name."""
    if not ENABLED or db.kv_get(conn, "agency_mail_off", "") == "1":
        return None
    if not (config.IMAP_USER and config.IMAP_PASSWORD):
        return None
    now = datetime.now(IL)
    if not force:
        if not _in_window(now):
            return None
        day = now.strftime("%Y-%m-%d")
        if db.kv_get(conn, "agency_mail_day", "") != day:
            db.kv_set(conn, "agency_mail_day", day)
            db.kv_set(conn, "agency_mail_count", "0")
        if int(db.kv_get(conn, "agency_mail_count", "0") or 0) >= PER_DAY:
            return None
        if time.time() - float(db.kv_get(conn, "agency_mail_last", "0") or 0) < GAP_MIN * 60:
            return None
    todo = _pending(conn)
    if not todo:
        return None
    item = todo[0]
    _send(item)
    db.kv_set(conn, f"agency_mail_sent:{item['email'].lower()}", now.isoformat())
    db.kv_set(conn, "agency_mail_last", str(time.time()))
    db.kv_set(conn, "agency_mail_count",
              str(int(db.kv_get(conn, "agency_mail_count", "0") or 0) + 1))
    left = len(todo) - 1
    notifier._send_raw(
        f"📧 Sent from your Gmail to <b>{html.escape(item['name'])}</b> "
        f"({html.escape(item['email'])}) - {left} left in the queue. Replies land "
        f"in your inbox.\n\n<i>{html.escape(item['subject'])}</i>\n"
        f"{html.escape(item['body'][:900])}")
    return item["name"]


def job(conn) -> None:
    """Scheduler entry point (loop-only job `agency_mail`)."""
    name = send_one(conn)
    if name:
        print(f"agency mail sent to {name}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--status", action="store_true")
    g.add_argument("--off", action="store_true")
    g.add_argument("--on", action="store_true")
    g.add_argument("--send-now", action="store_true", help="send one now, ignoring pacing")
    a = ap.parse_args()
    conn = db.connect()
    if a.off:
        db.kv_set(conn, "agency_mail_off", "1"); print("agency mail OFF")
    elif a.on:
        db.kv_set(conn, "agency_mail_off", "0"); print("agency mail ON")
    elif a.send_now:
        print(send_one(conn, force=True) or "nothing sent")
    q, todo = _queue(), _pending(conn)
    print(f"queue {len(q)}, sent {len(q) - len(todo)}, pending {len(todo)}, "
          f"{PER_DAY}/day, off={db.kv_get(conn, 'agency_mail_off', '0')}")
    for item in todo[:5]:
        print("  next:", item["name"], item["email"])


if __name__ == "__main__":
    main()
