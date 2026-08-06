"""Three lightweight free job boards, one fetcher - all public JSON, no auth.

  - Arbeitnow      https://www.arbeitnow.com/api/job-board-api
                   Europe-centric; explicit job_types incl. Freelance/Contract.
  - Working Nomads https://www.workingnomads.com/api/exposed_jobs/
                   Curated remote dev jobs.
  - Himalayas      https://himalayas.app/jobs/api?limit=N
                   Large remote pool; employmentType + salary fields.

All three are in DOMAIN_REQUIRED_SOURCES, so only listings matching a domain
keyword (CV/ML/OCR/algorithms/...) survive the gate.

(ai-jobs.net was evaluated too but its documented feed/API endpoints 404 now.)
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import config
from models import Lead

log = logging.getLogger("jobboards")

_TAG_RE = re.compile(r"<[^>]+>")


def _clean(html: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", html or "")).strip()


def _parse_when(v):
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v, tz=timezone.utc)
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _arbeitnow(client) -> list[Lead]:
    r = client.get("https://www.arbeitnow.com/api/job-board-api")
    r.raise_for_status()
    leads = []
    for j in r.json().get("data", []):
        types = ", ".join(j.get("job_types", []) or [])
        text = (f"{j.get('title','')} at {j.get('company_name','')}\n"
                f"Types: {types} | Remote: {j.get('remote')} | Location: {j.get('location','')}\n"
                f"Tags: {', '.join(j.get('tags', []) or [])}\n\n{_clean(j.get('description',''))}")
        leads.append(Lead(source="arbeitnow", url=j.get("url", ""),
                          raw_text=text[:4000], author=j.get("company_name"),
                          posted_at=_parse_when(j.get("created_at"))))
    return leads


def _workingnomads(client) -> list[Lead]:
    r = client.get("https://www.workingnomads.com/api/exposed_jobs/")
    r.raise_for_status()
    leads = []
    for j in r.json():
        text = (f"{j.get('title','')} at {j.get('company_name','')}\n"
                f"Category: {j.get('category_name','')} | Location: {j.get('location','')}\n"
                f"Tags: {j.get('tags','')}\n\n{_clean(j.get('description',''))}")
        leads.append(Lead(source="workingnomads", url=j.get("url", ""),
                          raw_text=text[:4000], author=j.get("company_name"),
                          posted_at=_parse_when(j.get("pub_date"))))
    return leads


def _himalayas(client) -> list[Lead]:
    # their API is slow; a small page + generous timeout keeps it reliable
    r = client.get("https://himalayas.app/jobs/api", params={"limit": 20}, timeout=90)
    r.raise_for_status()
    leads = []
    for j in r.json().get("jobs", []):
        emp = ", ".join(j.get("employmentType", []) or []) \
            if isinstance(j.get("employmentType"), list) else (j.get("employmentType") or "")
        url = j.get("applicationLink") or j.get("guid") or ""
        text = (f"{j.get('title','')} at {j.get('companyName','')}\n"
                f"Employment: {emp} | Categories: {', '.join(j.get('categories', []) or [])}\n\n"
                f"{_clean(j.get('description') or j.get('excerpt') or '')}")
        leads.append(Lead(source="himalayas", url=url,
                          raw_text=text[:4000], author=j.get("companyName"),
                          posted_at=_parse_when(j.get("pubDate"))))
    return leads


def _jobspresso(client) -> list[Lead]:
    """WP Job Manager RSS with a working keyword filter."""
    from xml.etree import ElementTree as ET
    from email.utils import parsedate_to_datetime

    leads, seen = [], set()
    for kw in ("machine learning", "computer vision", "artificial intelligence"):
        r = client.get("https://jobspresso.co/",
                       params={"feed": "job_feed", "search_keywords": kw})
        r.raise_for_status()
        for item in ET.fromstring(r.content).findall(".//item"):
            link = (item.findtext("link") or "").strip()
            if not link or link in seen:
                continue
            seen.add(link)
            posted = None
            pub = item.findtext("pubDate")
            if pub:
                try:
                    posted = parsedate_to_datetime(pub)
                except (TypeError, ValueError):
                    pass
            text = (f"{(item.findtext('title') or '').strip()}\n\n"
                    f"{_clean(item.findtext('description') or '')}")
            leads.append(Lead(source="jobspresso", url=link,
                              raw_text=text[:4000], posted_at=posted))
    return leads


def fetch() -> list[Lead]:
    import httpx

    headers = {"User-Agent": config.USER_AGENT, "Accept": "application/json"}
    leads: list[Lead] = []
    with httpx.Client(headers=headers, timeout=25, follow_redirects=True) as client:
        for name, fn in (("arbeitnow", _arbeitnow),
                         ("workingnomads", _workingnomads),
                         ("himalayas", _himalayas),
                         ("jobspresso", _jobspresso)):
            try:
                got = fn(client)
                log.info("%s: fetched %d jobs", name, len(got))
                leads.extend(got)
            except Exception as e:
                log.error("%s failed: %s", name, e)
    return leads
