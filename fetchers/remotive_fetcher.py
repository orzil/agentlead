"""Remotive - free public JSON API, no auth. Remote dev/AI jobs with a clean
`job_type` field (freelance / contract / full_time), so we can flag freelance.

NOTE: Remotive rate-limits to ~4 requests/day and serves ~24h-delayed data, so
this fetcher is scheduled infrequently and keeps its query set small.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import config
from models import Lead

log = logging.getLogger("remotive")

API = "https://remotive.com/api/remote-jobs"
QUERIES = ["computer vision", "machine learning", "OCR", "algorithm"]
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(html: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", html or "")).strip()


def fetch() -> list[Lead]:
    import httpx

    headers = {"User-Agent": config.USER_AGENT, "Accept": "application/json"}
    seen: set = set()
    leads: list[Lead] = []
    with httpx.Client(headers=headers, timeout=25, follow_redirects=True) as client:
        for q in QUERIES:
            try:
                r = client.get(API, params={"search": q, "limit": 25})
                r.raise_for_status()
                for j in r.json().get("jobs", []) or []:
                    jid = j.get("id") or j.get("url")
                    if not jid or jid in seen:
                        continue
                    seen.add(jid)
                    jtype = j.get("job_type", "")
                    loc = j.get("candidate_required_location", "")
                    text = (f"{j.get('title','')} at {j.get('company_name','')}\n"
                            f"Type: {jtype} | Location: {loc} | Category: {j.get('category','')}\n"
                            f"Tags: {', '.join(j.get('tags', []) or [])}\n\n{_clean(j.get('description',''))}")
                    pub = j.get("publication_date")
                    posted = None
                    if pub:
                        try:
                            posted = datetime.fromisoformat(pub).replace(tzinfo=timezone.utc)
                        except ValueError:
                            pass
                    leads.append(Lead(source="remotive", url=j.get("url", ""),
                                      raw_text=text[:4000], author=j.get("company_name"),
                                      posted_at=posted))
            except Exception as e:
                log.error("remotive query=%r failed: %s", q, e)
    log.info("Remotive: fetched %d jobs", len(leads))
    return leads
