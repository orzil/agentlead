"""Career pages of hand-picked AI/CV companies via their ATS platforms'
PUBLIC no-auth JSON APIs (Greenhouse / Comeet / Workable / Ashby).

Why: Israeli computer-vision companies (Trigo, Pixellot, Aidoc, Hailo, ...)
are exactly Or's domain - even their full-time posts are strong contract-pitch
targets, and the AI-data companies (Scale, Invisible, Toloka, Turing) regularly
post contractor work. All endpoints verified 2026-07-06.

Titles/locations only (no descriptions) - enough for the gate + scorer, and the
URL opens the full post. The gate requires a DOMAIN keyword, so only on-domain
roles (CV/ML/algorithms/data) survive.
"""
from __future__ import annotations

import logging
from datetime import datetime

import config
from models import Lead

log = logging.getLogger("companies")

GREENHOUSE = [  # slug -> label
    ("lightricks", "Lightricks (IL)"),
    ("cortica", "Cortica (IL)"),
    ("aidocmedical", "Aidoc (IL)"),
    ("invisibletech", "Invisible Technologies"),
    ("stabilityai", "Stability AI"),
    ("scaleai", "Scale AI"),
    ("turing", "Turing"),
    ("toloka", "Toloka"),
]
COMEET = [  # (uid, token, label) - tokens are long-lived, embedded in careers pages
    ("BA.00B", "ABB4B1D4062203155D855D8203155D815762031", "Pixellot (IL)"),
    ("D5.007", "5D71D33348F348F1D331D3311852EB85D7BAE", "Hailo (IL)"),
    ("A6.005", "6A527DED4A6A52E8321396A503528D4A", "Trigo (IL)"),
    ("43.00F", "34F108B69E34F108B13DA17299ED13DAD3C", "Nanox AI (IL)"),
]
WORKABLE = [("huggingface", "Hugging Face")]
ASHBY = [("Viz.ai", "Viz.ai")]


def _when(v):
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
        for slug, label in GREENHOUSE:
            try:
                r = client.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
                r.raise_for_status()
                jobs = r.json().get("jobs", [])
                # big boards (e.g. Scale AI ~180 roles) get capped to the most
                # recently published slice so one company can't flood the pipeline
                jobs = sorted(jobs, key=lambda x: x.get("first_published") or "", reverse=True)[:60]
                for j in jobs:
                    loc = (j.get("location") or {}).get("name", "")
                    leads.append(Lead(
                        source=f"companies/{label}",
                        url=j.get("absolute_url", ""),
                        raw_text=f"{j.get('title','')} at {label}\nLocation: {loc}",
                        author=label,
                        posted_at=_when(j.get("first_published") or j.get("updated_at")),
                    ))
            except Exception as e:
                log.error("greenhouse %s failed: %s", slug, e)

        for uid, token, label in COMEET:
            try:
                r = client.get(f"https://www.comeet.co/careers-api/2.0/company/{uid}/positions",
                               params={"token": token})
                r.raise_for_status()
                for j in r.json():
                    loc = (j.get("location") or {}).get("name", "")
                    url = (j.get("url_comeet_hosted_page")
                           or j.get("url_active_page") or "")
                    leads.append(Lead(
                        source=f"companies/{label}",
                        url=url,
                        raw_text=(f"{j.get('name','')} at {label}\n"
                                  f"Location: {loc} | Type: {j.get('employment_type','')} | "
                                  f"Level: {j.get('experience_level','')}"),
                        author=label,
                        posted_at=_when(j.get("time_updated")),
                    ))
            except Exception as e:
                log.error("comeet %s failed: %s", label, e)

        for slug, label in WORKABLE:
            try:
                r = client.get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}")
                r.raise_for_status()
                for j in r.json().get("jobs", []):
                    leads.append(Lead(
                        source=f"companies/{label}",
                        url=j.get("url") or j.get("shortlink", ""),
                        raw_text=(f"{j.get('title','')} at {label}\n"
                                  f"Type: {j.get('employment_type','')} | "
                                  f"Remote: {j.get('telecommuting')} | "
                                  f"Country: {j.get('country','')}"),
                        author=label,
                        posted_at=_when(j.get("published_on")),
                    ))
            except Exception as e:
                log.error("workable %s failed: %s", slug, e)

        for slug, label in ASHBY:
            try:
                r = client.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
                r.raise_for_status()
                for j in r.json().get("jobs", []):
                    if j.get("isListed") is False:
                        continue
                    leads.append(Lead(
                        source=f"companies/{label}",
                        url=j.get("jobUrl") or f"https://jobs.ashbyhq.com/{slug}/{j.get('id','')}",
                        raw_text=(f"{j.get('title','')} at {label}\n"
                                  f"Type: {j.get('employmentType','')} | "
                                  f"Location: {j.get('location','')} | Remote: {j.get('isRemote')}"),
                        author=label,
                        posted_at=_when(j.get("publishedAt")),
                    ))
            except Exception as e:
                log.error("ashby %s failed: %s", slug, e)

    log.info("companies: fetched %d roles from %d boards",
             len(leads), len(GREENHOUSE) + len(COMEET) + len(WORKABLE) + len(ASHBY))
    return leads
