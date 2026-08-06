"""Braintrust - free public JSON API, no auth. A 100%-freelance/contract
talent marketplace: every listing has job_type=freelance, hourly USD budgets,
skills, and expected hours. One of the highest-fit sources for Or.

GET https://app.usebraintrust.com/api/jobs/?page=N  (paginated, 'next' link)
The list API has no long description; title+skills+budget are plenty for the
gate and scorer, and the URL leads to the full post.
"""
from __future__ import annotations

import logging
from datetime import datetime

import config
from models import Lead

log = logging.getLogger("braintrust")

API = "https://app.usebraintrust.com/api/jobs/"
MAX_PAGES = 4  # 20/page; 141 open jobs total right now


def _parse_when(v):
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def fetch() -> list[Lead]:
    import httpx

    headers = {"User-Agent": config.USER_AGENT, "Accept": "application/json"}
    leads: list[Lead] = []
    with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
        for page in range(1, MAX_PAGES + 1):
            try:
                r = client.get(API, params={"page": page})
                if r.status_code == 404:  # past the last page
                    break
                r.raise_for_status()
                data = r.json()
                for j in data.get("results", []):
                    jid = j.get("id")
                    if not jid:
                        continue
                    skills = ", ".join(s.get("name", "") for s in (j.get("main_skills") or []))
                    locs = ", ".join(str(x) for x in (j.get("locations") or [])) or "remote"
                    text = (f"{j.get('title','')}\n"
                            f"Type: {j.get('job_type','')} ({j.get('payment_type','')}) | "
                            f"Rate: {j.get('budget_minimum_usd')}-{j.get('budget_maximum_usd')} USD/hr | "
                            f"Hours/wk: {j.get('expected_hours_per_week')} | "
                            f"Contract: {j.get('contract_type','')}\n"
                            f"Skills: {skills}\nLocations: {locs}")
                    leads.append(Lead(
                        source="braintrust",
                        url=f"https://app.usebraintrust.com/jobs/{jid}/",
                        raw_text=text[:4000],
                        posted_at=_parse_when(j.get("created")),
                    ))
                if not data.get("next"):
                    break
            except Exception as e:
                log.error("braintrust page %d failed: %s", page, e)
                break
    log.info("Braintrust: fetched %d jobs", len(leads))
    return leads
