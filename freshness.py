"""How old is a lead, and how much should that cost it?

A gig is perishable. A month-old post is usually filled, answered, or forgotten,
so it cannot be a 7/10 no matter how well it matches - Or made exactly that
point after seeing 38-day-old posts sitting at the top of his table.

This is applied deterministically AFTER scoring rather than left to the LLM,
because the model almost never knows the date: a Reddit or Facebook body rarely
says "posted 5 weeks ago", so the rubric's freshness rule only fired on the rare
post that spelled it out. The fetcher already knows the date; using it is both
more accurate and free.

Age comes from, in order:
  1. posted_at set by the fetcher (the real post date, when the source gives one)
  2. a date written in the post body ("Mar 7, 2022") - Facebook supplies no date
     at all, so this is the only signal there
  3. fetched_at, as a floor: a lead cannot be fresher than when we first saw it
"""
from __future__ import annotations

from datetime import datetime, timezone

import config

# Penalty by age. Deliberately gentle in the first week and steep after a month,
# which is roughly how a freelance post's odds actually decay: still open for a
# few days, contested within two weeks, cold after a month.
PENALTY_TIERS = [
    (7, 0),      # this week - full score
    (14, 1),     # last week
    (30, 2),     # this month
    (10_000, 3),  # older; MAX_LEAD_AGE_DAYS gates most of these out entirely
]


def _parse(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _body_date(text: str) -> datetime | None:
    m = config.STALE_DATE_RE.search("\n".join((text or "").splitlines()[:6]))
    if not m:
        return None
    stamp = f"{m.group(1)} {m.group(2)} {m.group(3)}"
    for fmt in ("%b %d %Y", "%B %d %Y"):
        try:
            return datetime.strptime(stamp, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def age_days(posted_at=None, raw_text: str = "", fetched_at=None) -> int | None:
    """Best estimate of how many days old the post is, or None if unknowable."""
    now = datetime.now(timezone.utc)
    candidates = [d for d in (_parse(posted_at), _body_date(raw_text)) if d]
    if not candidates:
        # fetched_at is a floor, not the post date - a lead we saw two months ago
        # is at least two months old even if the source never dated it.
        f = _parse(fetched_at)
        if not f:
            return None
        return max(0, (now - f).days)
    # oldest credible signal wins: if the body says 2022, a posted_at of today
    # (which is really just the fetch time) must not override it
    oldest = min(candidates)
    return max(0, (now - oldest).days)


def penalty(days: int | None) -> int:
    if days is None:
        return 0
    for limit, cost in PENALTY_TIERS:
        if days <= limit:
            return cost
    return PENALTY_TIERS[-1][1]


def apply(score, posted_at=None, raw_text: str = "", fetched_at=None):
    """Lower a LeadScore for age, in place, and flag why. Returns (score, days).

    Never drops below 1, and records the original in `reasoning` so a demoted
    lead can still be understood later.
    """
    days = age_days(posted_at, raw_text, fetched_at)
    cost = penalty(days)
    if not cost or score is None:
        return score, days
    original = score.score
    score.score = max(1, original - cost)
    label = f"{days}d old"
    if label not in (score.red_flags or []):
        score.red_flags = list(score.red_flags or []) + [label]
    score.reasoning = f"[age -{cost}: was {original}/10, {label}] {score.reasoning or ''}".strip()
    return score, days
