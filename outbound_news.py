"""Funding / launch news -> outbound prospects.

A startup that just raised money for a computer-vision, OCR, document-AI, robotics
or automation product has fresh budget and a roadmap, and usually no spare
engineers yet. These stories never reach the lead gate (they are news, not job
posts), so they are stored as leads under source `news/<site>` and captured
straight into `prospects` for the daily outbound batch.

Free RSS only. Drafts only - Or contacts the company by hand.
"""
from __future__ import annotations

import html
import logging
import re
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

import config
import db
import outbound
from models import Lead

log = logging.getLogger("outbound_news")

FEEDS = {
    "techcrunch-ai": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "geektime-il": "https://www.geektime.co.il/feed/",
}

FUNDING_RE = re.compile(
    r"(\braises?\b|\braised\b|\bfunding\b|\bseed\b|series\s+[a-c]\b|\bpre-?seed\b"
    r"|\bbacked\b|\bsecures?\b|\blaunch(es|ed)?\b"
    r"|גיוס|גייסה|גייסו|מגייס|סבב|השקיעה|השקעה|משיקה|השיקה)", re.IGNORECASE)

# Fields where a small team buys outside engineering. Wider than the lead gate on
# purpose (robotics / medtech / agritech are the products, not the skill words).
SECTOR_RE = re.compile(
    r"(computer\s+vision|\bOCR\b|document\s+(ai|processing|intelligence)|machine\s+vision"
    r"|robot|inspection|defect|medical\s+imag|radiolog|satellite|drone|lidar|autonomous"
    r"|video\s+analytics|\bvision\b|agritech|document|invoice|automation"
    r"|ראייה\s+ממוחשבת|רובוט|אוטומציה|בינה\s+מלאכותית|סוכני|הדמיה|ייצור)", re.IGNORECASE)

MAX_AGE_DAYS = 10


def _parse(xml_bytes: bytes, site: str) -> list[Lead]:
    out: list[Lead] = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        log.warning("%s: feed did not parse: %s", site, e)
        return out
    now = datetime.now(timezone.utc)
    for item in root.iter("item"):
        title = html.unescape((item.findtext("title") or "").strip())
        link = (item.findtext("link") or "").strip()
        desc = re.sub(r"<[^>]+>", " ", html.unescape(item.findtext("description") or ""))
        desc = re.sub(r"\s+", " ", desc).strip()
        text = f"{title}. {desc}"[:1500]
        if not (title and link and FUNDING_RE.search(text) and SECTOR_RE.search(text)):
            continue
        posted = None
        try:
            posted = parsedate_to_datetime(item.findtext("pubDate") or "")
            if posted.tzinfo is None:
                posted = posted.replace(tzinfo=timezone.utc)
            if (now - posted).days > MAX_AGE_DAYS:
                continue
        except (TypeError, ValueError):
            pass
        out.append(Lead(source=f"news/{site}", url=link, raw_text=text, posted_at=posted))
    return out


def fetch() -> list[Lead]:
    leads: list[Lead] = []
    headers = {"User-Agent": config.USER_AGENT}
    with httpx.Client(headers=headers, timeout=25, follow_redirects=True) as client:
        for site, url in FEEDS.items():
            try:
                r = client.get(url)
                r.raise_for_status()
                leads.extend(_parse(r.content, site))
            except Exception as e:
                log.warning("%s fetch failed: %s", site, str(e)[:80])
    return leads


def run(conn: sqlite3.Connection) -> int:
    """Fetch, store and capture as prospects. Returns how many were new."""
    new = 0
    for lead in fetch():
        lead_id = db.insert_lead(conn, lead)       # None = already stored (dedup)
        if lead_id is None:
            continue
        conn.execute("UPDATE leads SET status='gated_out', reasoning='news: prospect source' "
                     "WHERE id=?", (lead_id,))
        if outbound.capture(conn, lead_id, lead.raw_text, require_domain=False):
            new += 1
    conn.commit()
    log.info("outbound_news: %d new prospect(s)", new)
    return new
