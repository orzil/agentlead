"""Jobicy - free public remote-jobs JSON API (no auth, no rate-limit worth
worrying about). Remote AI/ML/data roles carrying a `jobType` field
(Full-Time / Part-Time / Contract / Freelance), so the FT gate can weed out the
salaried ones and keep the freelance/contract/part-time gigs the engineer wants.

Docs: https://jobicy.com/jobs-rss-feed (JSON at /api/v2/remote-jobs).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

import config
from models import Lead

log = logging.getLogger("jobicy")

API = "https://jobicy.com/api/v2/remote-jobs"
# Jobicy industry tags most likely to carry the engineer's kind of work.
# (Jobicy uses a fixed tag vocabulary; the keyword gate narrows these broad
# buckets down to the engineer's domains, and drops full-time-only roles.)
TAGS = ["machine-learning", "data", "dev", "engineering"]
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(html: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", html or "")).strip()


def fetch() -> list[Lead]:
    import httpx

    headers = {"User-Agent": config.USER_AGENT, "Accept": "application/json"}
    seen: set = set()
    leads: list[Lead] = []
    with httpx.Client(headers=headers, timeout=25, follow_redirects=True) as client:
        for tag in TAGS:
            try:
                r = client.get(API, params={"count": 50, "tag": tag})
                r.raise_for_status()
                for j in r.json().get("jobs", []) or []:
                    jid = j.get("id") or j.get("url")
                    if not jid or jid in seen:
                        continue
                    seen.add(jid)
                    jt = j.get("jobType") or []
                    jt = ", ".join(jt) if isinstance(jt, list) else str(jt)
                    text = (f"{j.get('jobTitle','')} at {j.get('companyName','')}\n"
                            f"Type: {jt} | Location: {j.get('jobGeo','')} | "
                            f"Level: {j.get('jobLevel','')}\n\n"
                            f"{_clean(j.get('jobExcerpt',''))}")
                    pub = j.get("pubDate")
                    posted = None
                    if pub:
                        try:
                            posted = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                        except (ValueError, AttributeError):
                            pass
                    leads.append(Lead(source="jobicy", url=j.get("url", ""),
                                      raw_text=text[:4000], author=j.get("companyName"),
                                      posted_at=posted))
            except Exception as e:
                log.error("jobicy tag=%r failed: %s", tag, e)
    log.info("Jobicy: fetched %d jobs", len(leads))
    return leads
