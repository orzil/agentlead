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
    # Israeli funding/launch news (2026-10-20; CTech/NoCamels/Geektime EN feeds 404)
    "globes-tech": "https://www.globes.co.il/webservice/rss/rssfeeder.asmx/FeederNode?iID=594",
    "globes-en": "https://en.globes.co.il/WebService/Rss/RssFeeder.asmx/FeederNode?iID=1725",
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

# 2026-11-15: the loose regexes above sent Or a Tesla Cybertruck story ("השיקה" +
# "ייצור"), layoffs at Innoviz/eBay and Nvidia-invests-in-Meta as "prospects".
# A news item is a prospect only when a company RAISED A STATED AMOUNT, in a
# vision/OCR/robotics field, and is not a giant, a layoff or an acquisition.
ROUND_RE = re.compile(
    r"(\braise[sd]?\b|\bfunding\b|\bseed\b|series\s+[a-c]\b|גייס(ה|ו)?\b|מגייס(ת|ים)?\b|גיוס|סבב)"
    r".{0,80}?(\$\s?\d+(\.\d+)?\s?(m\b|million)|\d+(\.\d+)?\s*מיליון\s*(דולר|שקל|יורו))"
    r"|(\$\s?\d+(\.\d+)?\s?(m\b|million)|\d+(\.\d+)?\s*מיליון\s*(דולר|שקל|יורו)).{0,40}?"
    r"(\bround\b|\bfunding\b|\bseed\b|series\s+[a-c]\b|גיוס|סבב)", re.IGNORECASE | re.DOTALL)
CORE_SECTOR_RE = re.compile(
    r"(computer\s+vision|\bOCR\b|document\s+(ai|processing|intelligence)|machine\s+vision"
    r"|robot|inspection|defect|medical\s+imag|radiolog|satellite\s+imag|drone|lidar"
    r"|video\s+analytics|\bvision\b|imaging|sim-to-real"
    r"|ראייה\s+ממוחשבת|רובוט|הדמיה|עיבוד\s+תמונה|בדיקה\s+אופטית|רחפן)", re.IGNORECASE)
NOT_PROSPECT_RE = re.compile(
    r"(billion|מיליארד|layoff|lay\s+off|פיטורים|מפטר|acquir|takeover|תשתלט|רוכשת|רכישת"
    r"|\b(tesla|nvidia|meta|amazon|google|apple|microsoft|ebay|openai|anthropic)\b"
    r"|טסלה|אנבידיה|מטא\b|אמזון|גוגל|אפל|מיקרוסופט|איביי)", re.IGNORECASE)


def is_prospect(text: str) -> bool:
    title = text.split(". ", 1)[0]
    return bool(ROUND_RE.search(text) and CORE_SECTOR_RE.search(text)
                and not NOT_PROSPECT_RE.search(title))


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
        if not (title and link and is_prospect(text)):
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
