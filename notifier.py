"""Telegram notifications (free). Falls back to console + outbox.log when unconfigured."""
from __future__ import annotations

import html
import json
import logging
import re
import sqlite3
from datetime import datetime

import httpx

import config

log = logging.getLogger("notifier")
OUTBOX = config.BASE_DIR / "outbox.log"

SOURCE_ICONS = {
    "facebook": "\U0001F4D8", "upwork": "\U0001F7E2", "wellfound": "\U0001F680",
    "xplace": "\U0001F1EE\U0001F1F1", "secrettelaviv": "\U0001F1EE\U0001F1F1",
    "hn": "\U0001F7E0", "r": "\U0001F916", "linkedin": "\U0001F537",
    "whatsapp": "\U0001F4AC",
}


def _open_line(row: sqlite3.Row) -> str:
    """The link at the bottom of a push. WhatsApp messages have no web URL (the
    synthetic whatsapp:// id is for dedup only, and Telegram rejects the scheme),
    so they get the group + time as text instead."""
    if row["url"].startswith("whatsapp://"):
        when = (row["posted_at"] or "")[:16].replace("T", " ")
        group = row["source"].split("/", 1)[-1]
        return f"\n\U0001F4AC in <b>{html.escape(group)}</b> {when} UTC"
    return f'\n<a href="{html.escape(row["url"], quote=True)}">Open post →</a>'


def _wa_contact(row: sqlite3.Row) -> str | None:
    """Sender line for a WhatsApp lead: name plus a tappable wa.me link, so Or
    can DM the poster from his main phone."""
    if not row["url"].startswith("whatsapp://"):
        return None
    m = re.search(r"https://wa\.me/\d+", row["raw_text"] or "")
    who = html.escape(row["author"] or "?")
    return f"\U0001F464 {who}" + (f" - {m.group(0)}" if m else "")


def _send_raw(text: str) -> int | None:
    """Send to Telegram. Returns the MESSAGE ID, not just success.

    The id matters: replying to that message is how Or gives one-word feedback
    ("fulltime", "old", "good"), and feedback.py needs the id to map a reply
    back to the lead it judges.
    """
    if not (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID):
        # dry-run mode: keep the message so nothing is lost
        with open(OUTBOX, "a", encoding="utf-8") as f:
            f.write(f"--- {datetime.now().isoformat()} ---\n{text}\n\n")
        log.info("Telegram not configured; message written to outbox.log")
        return None
    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": config.TELEGRAM_CHAT_ID,
                "text": text[:4000],
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        if r.status_code != 200:
            log.error("Telegram error %s: %s", r.status_code, r.text[:200])
            return None
        return r.json().get("result", {}).get("message_id")
    except Exception as e:
        log.error("Telegram send failed: %s", e)
        return None


def notify_lead(row: sqlite3.Row, pitch: str | None = None) -> int | None:
    """Instant push for a scored lead. Returns the Telegram message id so the
    caller can map Or's one-word reply back to this lead."""
    icon = SOURCE_ICONS.get(row["source"].split("/")[0], "\U0001F4CC")
    red_flags = json.loads(row["red_flags"] or "[]")
    lines = [
        f"\U0001F3AF <b>Lead {row['score']}/10</b> - {row['category']} / {row['work_type']}",
        f"{icon} {html.escape(row['source'])}",
        "",
        html.escape(row["summary"] or (row["raw_text"] or "")[:300]),
    ]
    if row["budget"]:
        lines.append(f"\U0001F4B0 {html.escape(row['budget'])}")
    # Easy Apply comes from the source label, not the post text - LinkedIn's
    # logged-out pages never expose it (see config.LINKEDIN_EASYAPPLY).
    if row["source"].endswith("/easyapply"):
        lines.append("⚡ <b>Easy Apply</b> - one tap, no cover letter")
    if red_flags:
        lines.append("⚠️ " + html.escape(", ".join(red_flags)))
    contact = _wa_contact(row)
    if contact:
        lines.append(contact)
    if pitch:
        lines.append(f"\n✍️ <b>Suggested reply</b> (copy-paste):\n"
                     f"<code>{html.escape(pitch[:1200])}</code>")
    lines.append(_open_line(row))
    return _send_raw("\n".join(lines))


def notify_question(row: sqlite3.Row) -> int | None:
    """Push for a domain QUESTION (see scorer.score_question): the question in
    full, who asked, and the angle Or could answer from. Returns the message id
    so the usual one-word replies (good/spam/less/more) work on it too."""
    icon = SOURCE_ICONS.get(row["source"].split("/")[0], "\U0001F4CC")
    lines = [
        f"❓ <b>Question {row['score']}/10</b> - answer it, win the work",
        f"{icon} {html.escape(row['source'])}",
        "",
        html.escape((row["raw_text"] or "")[:900]),
    ]
    if row["summary"]:
        lines.append(f"\n\U0001F4A1 {html.escape(row['summary'])}")
    if row["reasoning"]:
        lines.append(f"\U0001F3AF Angle: {html.escape(row['reasoning'])}")
    draft = row["reply_draft"] if "reply_draft" in row.keys() else None
    if draft:
        lines.append(f"✍️ Ready answer:\n<code>{html.escape(draft)}</code>")
    contact = _wa_contact(row)
    if contact:
        lines.append(contact)
    lines.append(_open_line(row))
    return _send_raw("\n".join(lines))


def notify_reply_pending(lead_row: sqlite3.Row, message: str, reply_id: int) -> bool:
    """Tell the user a drafted reply awaits approval."""
    return _send_raw(
        f"✍️ <b>Reply drafted</b> for lead {lead_row['id']} "
        f"({html.escape(lead_row['source'])}, score {lead_row['score']}):\n\n"
        f"<code>{html.escape(message[:1500])}</code>\n\n"
        f"Approve with:\n<code>python main.py --approve-reply {reply_id}</code>\n"
        f'<a href="{html.escape(lead_row["url"], quote=True)}">Open post →</a>')


def send_digest(rows: list[sqlite3.Row]) -> bool:
    if not rows:
        return True
    lines = [f"\U0001F4EC <b>Daily digest - {len(rows)} borderline lead(s)</b>", ""]
    for r in rows[:15]:
        lines.append(
            f"<b>{r['score']}/10</b> [{html.escape(r['source'])}] "
            f"{html.escape((r['summary'] or r['raw_text'])[:150])}\n"
            + (f'<a href="{html.escape(r["url"], quote=True)}">link</a>'
               if r["url"].startswith("http") else _open_line(r).strip())
        )
        lines.append("")
    return _send_raw("\n".join(lines))


def send_error(job: str, err: str) -> bool:
    return _send_raw(f"\U0001F6A8 <b>lead-agent error</b> in <code>{html.escape(job)}</code>:\n"
                     f"<code>{html.escape(err[:500])}</code>")


def send_test() -> bool:
    return _send_raw("✅ lead-agent: Telegram connection works.")
