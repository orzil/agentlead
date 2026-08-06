"""Secret Tel Aviv jobs board (jobs.secrettelaviv.com, WordPress + WPJobBoard).

The board's front page server-renders every job card:
    div.wpjb-grid-row > .wpjb-col-title > a  (title + link)
                      > .wpjb-sub           (company)
For cards whose title passes a quick keyword check we also fetch the job's
detail page to give the LLM the full description.
"""
from __future__ import annotations

import logging
import re

import httpx
from bs4 import BeautifulSoup

import config
from models import Lead

log = logging.getLogger("secrettlv")
BOARD = "https://jobs.secrettelaviv.com/"
MAX_DETAIL_FETCHES = 10  # politeness cap per run


def _detail_text(client: httpx.Client, url: str) -> str:
    try:
        r = client.get(url)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        main = soup.select_one(".wpjb-job-content, .wpjb-text-box, article") or soup.body
        text = main.get_text(" ", strip=True) if main else ""
        return re.sub(r"\s{2,}", " ", text)[:4000]
    except Exception as e:
        log.warning("detail fetch failed for %s: %s", url, e)
        return ""


def fetch() -> list[Lead]:
    leads: list[Lead] = []
    headers = {"User-Agent": config.USER_AGENT}
    with httpx.Client(timeout=30, headers=headers, follow_redirects=True) as client:
        r = client.get(BOARD)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        details_fetched = 0
        for row in soup.select("div.wpjb-grid-row"):
            a = row.select_one(".wpjb-col-title a[href*='/job/']")
            if not a:
                continue
            url = a["href"]
            title = a.get_text(strip=True)
            company = row.select_one(".wpjb-col-title .wpjb-sub")
            company_txt = company.get_text(strip=True) if company else ""
            loc = row.select_one(".wpjb-col-location")
            loc_txt = loc.get_text(" ", strip=True) if loc else ""

            text = f"{title}\nCompany: {company_txt}\n{loc_txt}"
            # Full description only for cards that look relevant (saves requests)
            if (config.DOMAIN_RE.search(title) or config.ENGAGE_RE.search(text)) \
                    and details_fetched < MAX_DETAIL_FETCHES:
                detail = _detail_text(client, url)
                if detail:
                    text = f"{text}\n\n{detail}"
                    details_fetched += 1

            leads.append(Lead(source="secrettelaviv", url=url, raw_text=text))

    log.info("SecretTLV: fetched %d job cards", len(leads))
    return leads
