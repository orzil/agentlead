"""WhatsApp group messages from the phone's notification shade - no screen, no taps.

`adb shell dumpsys notification --noredact` prints each live notification's
extras, and WhatsApp's group notifications are MessagingStyle: every message
carries its sender, its FULL text (never cut at 'קרא עוד') and its exact time
in epoch milliseconds. Measured on the S9 (Android 9) on 2026-10-24.

Limits, which is why this complements the screen reader and never replaces it:
  * only the last 7 messages of each group are kept in the notification;
  * muted groups post no notification, and WhatsApp mutes large groups;
  * opening WhatsApp clears every notification, so this must run BEFORE a pass
    touches the app - it then sees exactly what arrived since the last pass.

Same allowlist rail as wa_phone: only groups this phone joined (or asked to
join - a notification from one proves the admin approved it).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

import wa_phone
from models import Lead

log = logging.getLogger("wa_notify")

_RECORD_SPLIT = re.compile(r"\n\s*NotificationRecord\(")
_TITLE_RE = re.compile(r"android\.conversationTitle=String \((.*?)\)\s*$", re.MULTILINE)
_COUNT_SUFFIX_RE = re.compile(r"\s*\((\d+)\s+(?:הודעות|messages)\)$")
_BUNDLE_RE = re.compile(r"\[\d+\] Bundle\[\{")
_KEYS = r"(?:time|type|uri|sender|sender_person|extras|text)"


def _messages(record: str) -> list[dict]:
    """The MessagingStyle messages of one notification record."""
    starts = [m.start() for m in _BUNDLE_RE.finditer(record)]
    out = []
    for i, a in enumerate(starts):
        chunk = record[a:starts[i + 1] if i + 1 < len(starts) else len(record)]
        chunk = re.split(r"\n\s+android\.\w+=", chunk, maxsplit=1)[0]   # end of the list
        t = re.search(r"\btime=(\d{13})", chunk)
        txt = re.search(rf"\btext=(.*?)(?=, {_KEYS}=|\}}\]\s*$)", chunk, re.DOTALL)
        if not (t and txt):
            continue
        snd = re.search(rf"\bsender=(.*?)(?=, {_KEYS}=|\}}\]\s*$)", chunk, re.DOTALL)
        out.append({"time_ms": int(t.group(1)), "text": txt.group(1).strip(),
                    "sender": (snd.group(1).strip() if snd else "").lstrip("~ ").strip()})
    return out


def parse(dump: str) -> list[dict]:
    """[{title, count, messages}] for every WhatsApp GROUP notification."""
    groups = []
    for rec in _RECORD_SPLIT.split(dump)[1:]:
        head = rec[:400]
        if "pkg=com.whatsapp" not in head or "isGroupConversation=Boolean (true)" not in rec:
            continue
        m = _TITLE_RE.search(rec)
        if not m:
            continue
        title = wa_phone.clean(m.group(1))
        cm = _COUNT_SUFFIX_RE.search(title)
        groups.append({"title": _COUNT_SUFFIX_RE.sub("", title).strip(),
                       "count": int(cm.group(1)) if cm else None,
                       "messages": _messages(rec)})
    return groups


def harvest(conn) -> tuple[list[Lead], dict[str, int]]:
    """New messages (newer than each group's watermark) as Leads, and
    {title: n_new} for read_pass, which then opens those groups even when the
    chat-list walk would miss them. The watermark itself is NOT moved here:
    a notification holds only the last 7 messages, and moving it would hide
    the older ones from the screen reader."""
    try:
        raw = wa_phone.shell("dumpsys", "notification", "--noredact", timeout=40)
    except wa_phone.PhoneError as e:
        log.warning("wa notify: dumpsys failed: %s", e)
        return [], {}
    joined = wa_phone._joined_titles(conn)
    requested = wa_phone._requested_titles(conn)
    marks = wa_phone._watermarks(conn, joined)
    today = datetime.now(wa_phone.IL).date()
    leads: list[Lead] = []
    news: dict[str, int] = {}
    groups = parse(raw)
    for g in groups:
        title = wa_phone._match_title(g["title"], joined)
        if title is None:
            approved = wa_phone._match_title(g["title"], requested)
            if approved is None:
                continue                    # not ours: Or's own chats are never read
            wa_phone._mark_accepted(conn, requested[approved], approved)
            joined[approved] = requested[approved]
            title = approved
            marks[title] = (datetime.now(timezone.utc)
                            - timedelta(days=wa_phone.WATERMARK_SEED_DAYS))
        code = joined[title]
        since = marks.get(title)
        new = 0
        for m in g["messages"]:
            posted = datetime.fromtimestamp(m["time_ms"] / 1000, tz=timezone.utc)
            if since is not None and posted < since:
                continue
            new += 1
            msg = {"text": m["text"], "time": posted.astimezone(wa_phone.IL).strftime("%H:%M"),
                   "date": posted.astimezone(wa_phone.IL).date(), "sender": m["sender"],
                   "number": "", "posted": posted}
            lead = wa_phone._to_lead(code, title, msg, today)
            if lead:
                leads.append(lead)
        if new:
            news[title] = new
    log.info("wa notify: %d group notification(s), %d of ours with %d new message(s)",
             len(groups), len(news), sum(news.values()))
    return leads, news
