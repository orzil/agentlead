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

# Score adjustment by age: POSITIVE is a bonus, negative a penalty. Roughly how
# a freelance post's odds actually decay - barely touched in the first 48 hours,
# contested within two weeks, cold after a month.
#
# The +1 for a two-day-old post is not just symmetry with the penalty: being
# early is most of the advantage on a direct channel. Few replies so far, the
# poster is still reading the thread, and nobody has been chosen yet.
ADJUST_TIERS = [
    (2, +1),      # posted in the last 48h - get in before the crowd
    (7, 0),       # this week - full score, no adjustment
    (14, -1),     # last week
    (30, -2),     # this month
    (10_000, -3),  # older; MAX_LEAD_AGE_DAYS gates most of these out entirely
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


def adjustment(days: int | None) -> int:
    """Score delta for this age. Positive = bonus, negative = penalty."""
    if days is None:
        return 0
    for limit, delta in ADJUST_TIERS:
        if days <= limit:
            return delta
    return ADJUST_TIERS[-1][1]


# kept for callers/tests that think in penalties
def penalty(days: int | None) -> int:
    return -min(0, adjustment(days))


def apply(score, posted_at=None, raw_text: str = "", fetched_at=None):
    """Adjust a LeadScore for age, in place, and flag why. Returns (score, days).

    Stays within 1-10, and records the original in `reasoning` so an adjusted
    lead can still be understood later.
    """
    days = age_days(posted_at, raw_text, fetched_at)
    delta = adjustment(days)
    if not delta or score is None:
        return score, days
    original = score.score
    score.score = max(1, min(10, original + delta))
    if score.score == original:      # already at the ceiling/floor
        return score, days
    label = f"{days}d old" if delta < 0 else f"fresh ({days}d)"
    if label not in (score.red_flags or []):
        score.red_flags = list(score.red_flags or []) + [label]
    score.reasoning = (f"[age {delta:+d}: was {original}/10, {label}] "
                       f"{score.reasoning or ''}").strip()
    return score, days
