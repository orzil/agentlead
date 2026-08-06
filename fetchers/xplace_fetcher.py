"""X-Place (xplace.com) - Israel's main freelance board.

Uses the site's own public JSON endpoint (discovered from its Angular app):
    GET https://www.xplace.com/rest/public/browse/projects?projectFsp_pageIndex=N
Returns 25 projects per page: title, description, budget range, flags.
No login, no scraping fragility.
"""
from __future__ import annotations

import logging

import httpx

import config
from models import Lead

log = logging.getLogger("xplace")
API = "https://www.xplace.com/rest/public/browse/projects"
# Note: the endpoint ignores its page parameter and always returns the 25
# newest projects - which is exactly what we want at a 2-hour poll cadence.


def fetch() -> list[Lead]:
    leads: list[Lead] = []
    headers = {
        "User-Agent": config.USER_AGENT,
        "Accept": "application/json",
        "Referer": "https://www.xplace.com/il/jobs",
    }
    with httpx.Client(timeout=30, headers=headers) as client:
        r = client.get(API, params={"projectFsp_pageIndex": 0})
        r.raise_for_status()
        try:
            payload = r.json().get("responsePayload", {})
        except ValueError:  # transient non-JSON response (maintenance page etc.)
            log.warning("X-Place returned non-JSON (%d bytes); skipping this run",
                        len(r.content))
            return []
        for p in payload.get("browseSearchFoundProjects", []):
            if p.get("foundProjectIsActive") is False:
                continue
            title = p.get("foundProjectTitle") or ""
            desc = p.get("foundProjectDescription") or ""
            budget = p.get("foundProjectBudgetRange") or ""
            fulltime = "FULL-TIME POSITION" if p.get("foundProjectIsFulltime") else ""
            cats = ", ".join(
                c.get("browseEntryCategoryName", "")
                for c in (p.get("foundProjectAllCategories") or [])[:4]
            )
            leads.append(
                Lead(
                    source="xplace",
                    url=f"https://www.xplace.com/il/job/{p['foundProjectId']}",
                    raw_text=(
                        f"{title}\n\n{desc}\n\nCategories: {cats}\n"
                        f"Budget range: {budget} {fulltime}"
                    ).strip(),
                )
            )
    log.info("X-Place: fetched %d projects", len(leads))
    return leads
