"""Gmail IMAP fetcher - the free, ban-proof channel for the hard platforms.

One inbox carries four sources:
  facebook       - per-group notification emails (notification@facebookmail.com)
                   after you enable "All posts" notifications on each group
  upwork         - saved-search job alert emails
  wellfound      - job alert emails
  linkedin/alert - saved-search job alerts (jobalerts-noreply@linkedin.com).
                   The robust half of the LinkedIn integration: LinkedIn can
                   bot-wall the guest scraper, but it cannot block its own
                   emails. See README for the 4-step alert setup.

Requires a Gmail *app password* (Google account -> Security -> 2-Step
Verification -> App passwords). Nothing here talks to the platforms
themselves, so there is zero account risk.
"""
from __future__ import annotations

import email
import email.header
import imaplib
import logging
import re
import sqlite3
from datetime import datetime, timedelta
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup

import config
import db
from fetchers import linkedin_fetcher
from models import Lead

log = logging.getLogger("email")

FB_POST_RE = re.compile(
    r"https://(?:www|m|l)\.facebook\.com/groups/[^\s\"'<>]+?(?:permalink|posts)/\d+[^\s\"'<>]*"
)
FB_BOILERPLATE = re.compile(
    r"(view or reply|this message was sent to|unsubscribe|manage your notification"
    r"|reply to this email|facebook, inc\.|meta platforms).*",
    re.I | re.S,
)


def _decode_header(value: str) -> str:
    parts = email.header.decode_header(value or "")
    out = []
    for text, enc in parts:
        if isinstance(text, bytes):
            out.append(text.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(text)
    return "".join(out)


def _get_html_and_text(msg: email.message.Message) -> tuple[str, str]:
    html_body, text_body = "", ""
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype not in ("text/html", "text/plain"):
            continue
        try:
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            decoded = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        except Exception:
            continue
        if ctype == "text/html" and not html_body:
            html_body = decoded
        elif ctype == "text/plain" and not text_body:
            text_body = decoded
    return html_body, text_body


def _clean_url(url: str) -> str:
    """Strip tracking query params; keep scheme://host/path."""
    s = urlsplit(url)
    return urlunsplit((s.scheme, s.netloc, s.path, "", ""))


def _parse_facebook(subject: str, html_body: str, text_body: str) -> list[Lead]:
    combined = html_body or text_body
    m = FB_POST_RE.search(combined)
    if not m:
        return []
    url = _clean_url(m.group(0))
    if html_body:
        text = BeautifulSoup(html_body, "html.parser").get_text("\n", strip=True)
    else:
        text = text_body
    text = FB_BOILERPLATE.sub("", text).strip()
    return [Lead(source="facebook", url=url, raw_text=f"{subject}\n\n{text[:4000]}")]


def _parse_job_alert(source: str, html_body: str, job_link_pat: re.Pattern,
                     prefix: str = "", canonicalise=None) -> list[Lead]:
    """Generic parser for Upwork/Wellfound/LinkedIn alert emails: one lead per job link.

    prefix       - prepended to every raw_text. Used for the email SUBJECT, which
                   carries the saved-search name ('"computer vision": 12 new jobs')
                   and so guarantees a domain-keyword hit for domain-gated sources
                   whose job titles alone ("Senior Data Scientist") wouldn't match.
    canonicalise - optional url -> url mapper, so alert links dedup against the
                   same job fetched by a scraper (see linkedin_fetcher).
    """
    if not html_body:
        return []
    soup = BeautifulSoup(html_body, "html.parser")
    full_text = soup.get_text("\n", strip=True)
    leads: list[Lead] = []
    seen_urls: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not job_link_pat.search(href):
            continue
        url = _clean_url(href)
        if canonicalise:
            url = canonicalise(url) or url
        if url in seen_urls:
            continue
        anchor = a.get_text(" ", strip=True)
        if not anchor or len(anchor) < 8:  # icon / "View job" buttons
            continue
        # NB: mark the URL seen only AFTER the anchor check - a job's logo link
        # often precedes its title link, and marking it here would swallow the
        # title anchor and drop the job entirely.
        seen_urls.add(url)
        # context: the text following the title inside the email body
        idx = full_text.find(anchor)
        context = full_text[idx: idx + 700] if idx >= 0 else anchor
        if prefix:
            context = f"{prefix}\n{context}"
        leads.append(Lead(source=source, url=url, raw_text=context))
    return leads


UPWORK_JOB_RE = re.compile(r"upwork\.com/(?:jobs|job|freelance-jobs/apply)/", re.I)
WELLFOUND_JOB_RE = re.compile(r"(wellfound\.com|angel\.co)/(?:jobs|l/|company/[^/]+/jobs)", re.I)
LINKEDIN_JOB_RE = re.compile(r"linkedin\.com/(?:comm/)?jobs/view/", re.I)


def _source_for(sender: str) -> str | None:
    sender = sender.lower()
    for domain, source in config.EMAIL_SOURCES.items():
        if domain in sender:
            return source
    return None


def fetch(conn: sqlite3.Connection) -> list[Lead]:
    if not (config.IMAP_USER and config.IMAP_PASSWORD):
        log.debug("IMAP not configured; skipping")
        return []

    since = (datetime.now() - timedelta(days=config.IMAP_LOOKBACK_DAYS)).strftime("%d-%b-%Y")
    leads: list[Lead] = []

    imap = imaplib.IMAP4_SSL(config.IMAP_HOST)
    try:
        imap.login(config.IMAP_USER, config.IMAP_PASSWORD)
        imap.select(config.IMAP_FOLDER, readonly=True)
        _, data = imap.search(None, f'(SINCE "{since}")')
        ids = data[0].split()
        # newest first, capped per run
        for num in reversed(ids[-300:]):
            _, hdr_data = imap.fetch(num, "(BODY.PEEK[HEADER.FIELDS (FROM MESSAGE-ID SUBJECT)])")
            if not hdr_data or not hdr_data[0]:
                continue
            hdr = email.message_from_bytes(hdr_data[0][1])
            sender = _decode_header(hdr.get("From", ""))
            source = _source_for(sender)
            if source is None:
                continue
            message_id = (hdr.get("Message-ID") or "").strip() or f"no-id-{num.decode()}"
            if db.email_seen(conn, message_id):
                continue

            _, msg_data = imap.fetch(num, "(BODY.PEEK[])")
            msg = email.message_from_bytes(msg_data[0][1])
            subject = _decode_header(msg.get("Subject", ""))
            html_body, text_body = _get_html_and_text(msg)

            try:
                if source == "facebook":
                    leads.extend(_parse_facebook(subject, html_body, text_body))
                elif source == "upwork":
                    leads.extend(_parse_job_alert("upwork", html_body, UPWORK_JOB_RE))
                elif source == "wellfound":
                    leads.extend(_parse_job_alert("wellfound", html_body, WELLFOUND_JOB_RE))
                elif source == "linkedin/alert":
                    leads.extend(_parse_job_alert(
                        "linkedin/alert", html_body, LINKEDIN_JOB_RE,
                        prefix=subject,
                        canonicalise=linkedin_fetcher.canonical_job_url))
            except Exception as e:
                log.error("parse failed for email %s (%s): %s", message_id, source, e)

            db.mark_email_seen(conn, message_id)
    finally:
        try:
            imap.logout()
        except Exception:
            pass

    log.info("Email: extracted %d leads", len(leads))
    return leads
