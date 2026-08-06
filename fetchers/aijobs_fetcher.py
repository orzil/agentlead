"""aijobs.net - the only dedicated AI/ML job board with free access.

Their old RSS/JSON endpoints are dead (404 since the ai-jobs.net -> aijobs.net
rebrand) and CSV/JSON export is PRO-only, but the site is fully server-rendered
Django+HTMX and robots.txt allows scraping.

We pull three views (verified 2026-07-06):
  1. GET  /                       -> 50 newest jobs across the board
  2. POST / {skills=853}          -> Computer Vision jobs (853 = CV skill pk,
                                     from the free /ac/skill/?q= autocomplete)
  3. POST / {regions=4}           -> Middle East jobs (incl. Tel Aviv)
POSTs need the Django CSRF cookie+token from step 1 and HX-Request headers.
Each <li> in #job_list carries title, salary, skill tags, seniority, employment
type (incl. Contract) and location - enough for the gate + scorer.
"""
from __future__ import annotations

import logging
import re

import config
from models import Lead

log = logging.getLogger("aijobs")

BASE = "https://aijobs.net/"
FILTERS = [
    ("cv", {"skills": "853"}),      # Computer Vision
    ("mideast", {"regions": "4"}),  # Middle East (incl. Israel)
]


def _parse_list(html: str, leads: list[Lead], seen: set) -> int:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    n = 0
    for li in soup.select("#job_list li"):
        a = li.select_one('a[href^="/job/"]')
        if not a:
            continue
        url = "https://aijobs.net" + a["href"]
        if url in seen:
            continue
        seen.add(url)
        text = re.sub(r"\s+", " ", li.get_text(" ", strip=True))
        text = re.sub(r"^Featured Feat\.\s*", "", text)
        if len(text) < 30:
            continue
        leads.append(Lead(source="aijobs", url=url, raw_text=text[:4000]))
        n += 1
    return n


def fetch() -> list[Lead]:
    import httpx

    headers = {"User-Agent": config.USER_AGENT}
    leads: list[Lead] = []
    seen: set = set()
    try:
        with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
            r = client.get(BASE)
            r.raise_for_status()
            n = _parse_list(r.text, leads, seen)
            log.info("aijobs: newest -> %d jobs", n)

            m = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', r.text)
            if m:
                post_headers = {"Referer": BASE, "HX-Request": "true"}
                for name, fields in FILTERS:
                    try:
                        r2 = client.post(BASE, headers=post_headers,
                                         data={"csrfmiddlewaretoken": m.group(1), **fields})
                        r2.raise_for_status()
                        n = _parse_list(r2.text, leads, seen)
                        log.info("aijobs: filter %s -> %d new jobs", name, n)
                    except Exception as e:
                        log.warning("aijobs filter %s failed: %s", name, e)
    except Exception as e:
        log.error("aijobs fetch failed: %s", e)
    log.info("aijobs.net: fetched %d jobs total", len(leads))
    return leads
