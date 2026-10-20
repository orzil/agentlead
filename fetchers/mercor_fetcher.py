"""Mercor - AI-training / expert-network gigs via its public explore-page JSON
(no auth). Added 2026-10-21 after the 60-day winners review: AI-training
platforms (micro1, Mindrift, Alignerr, Mercor) were the most frequent source of
>=6 leads - hourly, remote, $60-200/hr - but only ever reached us second-hand
through Reddit/Telegram reposts. This reads Mercor's own listing feed.

Each listing carries rate, hours/week and eligible countries, so the US-only
ones are dropped here and the 35+ h/wk ones are gated as full-time by
prefilter's "Hours/wk:" rule. The source is in STRONG_DOMAIN_SOURCES: the
title line must name CV/ML/OCR/... - the descriptions all say "AI".
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import config
from models import Lead

log = logging.getLogger("mercor")

API = "https://aws.api.mercor.com/work/listings-explore-page"


def _eligible(j: dict) -> bool:
    """Open to someone living in Israel: no country list, or Israel on it."""
    el = j.get("eligibleLocation") or []
    inel = j.get("ineligibleLocation") or []
    return (not el or "ISR" in el or "Israel" in el) and "ISR" not in inel and "Israel" not in inel


def _when(v: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(v).replace(tzinfo=timezone.utc) if v else None
    except ValueError:
        return None


def fetch() -> list[Lead]:
    import httpx

    headers = {"User-Agent": config.USER_AGENT, "Accept": "application/json"}
    with httpx.Client(headers=headers, timeout=40, follow_redirects=True) as client:
        r = client.get(API)
        r.raise_for_status()
        listings = r.json().get("listings", [])
    leads: list[Lead] = []
    for j in listings:
        if j.get("status") != "active" or j.get("isPrivate") or not _eligible(j):
            continue
        rate = f"{j.get('rateMin')}-{j.get('rateMax')} USD/{j.get('payRateFrequency') or 'hr'}"
        hours = j.get("hoursPerWeek")
        text = (f"{j.get('title', '')} at {j.get('companyName') or 'Mercor'}\n"
                f"Type: contract ({j.get('commitment', '')}) | Rate: {rate}"
                + (f" | Hours/wk: {hours}" if hours else "")
                + f" | Location: {j.get('location', '')}\n\n"
                f"{(j.get('description') or '')[:2500]}")
        leads.append(Lead(source="mercor",
                          url=f"https://work.mercor.com/jobs/{j['listingId']}",
                          raw_text=text,
                          posted_at=_when(j.get("postedAt") or j.get("createdAt"))))
    log.info("mercor: %d listing(s), %d open to Israel", len(listings), len(leads))
    return leads
