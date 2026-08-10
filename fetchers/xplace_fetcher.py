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
# The site moved the endpoint under /il/ (measured 2026-08-10: the bare
# /rest/... path now 302s to the homepage, which surfaced as a daily error
# alert). Both are tried, newest first, so another move degrades to a warning
# instead of breaking the job.
API_CANDIDATES = [
    "https://www.xplace.com/il/rest/public/browse/projects",
    "https://www.xplace.com/rest/public/browse/projects",
]
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
        payload = None
        for api in API_CANDIDATES:
            try:
                # follow_redirects stays OFF: a 302 to the homepage is how a
                # dead endpoint announces itself, and following it would just
                # hand us HTML to fail on later.
                r = client.get(api, params={"projectFsp_pageIndex": 0},
                               follow_redirects=False)
            except Exception as e:
                log.info("X-Place %s failed: %s", api, str(e)[:60])
                continue
            if r.status_code in (301, 302, 307, 308):
                log.info("X-Place %s redirects to %s - trying the next path",
                         api, r.headers.get("location", "?")[:40])
                continue
            if r.status_code != 200:
                log.info("X-Place %s -> HTTP %s", api, r.status_code)
                continue
            try:
                payload = r.json().get("responsePayload", {})
                break
            except ValueError:  # maintenance page etc.
                log.warning("X-Place returned non-JSON (%d bytes)", len(r.content))
                continue
        if payload is None:
            log.warning("X-Place: no endpoint responded with JSON; skipping this run")
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
