"""We Work Remotely - free public RSS, no auth. Quality remote dev roles;
contract/part-time listings appear alongside full-time.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

import config
from models import Lead

log = logging.getLogger("wwr")

FEEDS = [
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
]
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(html: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", html or "")).strip()


def fetch() -> list[Lead]:
    import httpx

    headers = {"User-Agent": config.USER_AGENT}
    seen: set = set()
    leads: list[Lead] = []
    with httpx.Client(headers=headers, timeout=25, follow_redirects=True) as client:
        for feed_url in FEEDS:
            try:
                r = client.get(feed_url)
                r.raise_for_status()
                root = ET.fromstring(r.content)
                for item in root.findall(".//item"):
                    link = (item.findtext("link") or "").strip()
                    if not link or link in seen:
                        continue
                    seen.add(link)
                    title = (item.findtext("title") or "").strip()
                    desc = _clean(item.findtext("description") or "")
                    region = (item.findtext("region") or "").strip()
                    jtype = (item.findtext("type") or "").strip()
                    text = f"{title}\n{('Type: '+jtype) if jtype else ''} {('| '+region) if region else ''}\n\n{desc}"
                    pub = item.findtext("pubDate")
                    posted = None
                    if pub:
                        try:
                            posted = parsedate_to_datetime(pub)
                        except (TypeError, ValueError):
                            pass
                    leads.append(Lead(source="weworkremotely", url=link,
                                      raw_text=text[:4000], posted_at=posted))
            except Exception as e:
                log.error("wwr feed %s failed: %s", feed_url, e)
    log.info("WeWorkRemotely: fetched %d jobs", len(leads))
    return leads
