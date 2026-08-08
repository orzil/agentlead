"""Find what a post pays, in USD, and decide whether it clears the floor.

Why this is fiddly enough to deserve its own module:
  * The same number means opposite things. "$50/hour" is a decent rate; "$50"
    for a whole project is an insult. So hourly and fixed amounts are tracked
    separately and compared against different floors.
  * Gig boards quote in local currency and the numbers look big. "INR 5000" is
    $60; "₹500/hr" is six dollars an hour. Converting first is the whole point.
  * Posts are full of numbers that are NOT the budget - "raised $2M", "10K
    users", "GPT-4", "24/7". Anything absurdly large is treated as noise rather
    than as a budget, and bare numbers with no currency are ignored entirely.
  * Ranges ("$100-$150/hr") take the TOP of the range, because the gate should
    kill only what is unambiguously too cheap.

Returns None when no budget is stated - which is common and must never be
treated as "pays nothing". Plenty of good direct-approach posts name no figure.
"""
from __future__ import annotations

import re

import config

# 1,200.50 / 1.200,50 / 15k / 2M
_NUM = r"\d[\d,.\s]{0,12}\d|\d"
_AMOUNT_RE = re.compile(rf"({_NUM})\s*([kKmM])?\b")

# An amount over this is almost never the pay for one freelance job - it is
# funding, revenue, user counts or a phone number.
_ABSURD_USD = 500_000


def _to_float(raw: str, suffix: str | None) -> float | None:
    s = raw.replace(" ", "")
    # 1.200,50 (EU style) -> 1200.50 ; 1,200.50 (US style) -> 1200.50
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rindex(",") > s.rindex(".") \
            else s.replace(",", "")
    elif "," in s:
        # comma as thousands separator when it groups 3 digits, else decimal
        s = s.replace(",", "") if re.search(r",\d{3}\b", s) else s.replace(",", ".")
    try:
        val = float(s)
    except ValueError:
        return None
    if suffix in ("k", "K"):
        val *= 1_000
    elif suffix in ("m", "M"):
        val *= 1_000_000
    return val


def _currency_at(text: str, start: int, end: int) -> str | None:
    """Currency token immediately before or after an amount."""
    before = text[max(0, start - 12):start]
    after = text[end:end + 12]
    for pattern, code in config.CURRENCY_TOKENS:
        if re.search(pattern + r"\s*$", before, re.IGNORECASE):
            return code
        if re.search(r"^\s*" + pattern, after, re.IGNORECASE):
            return code
    return None


def extract(text: str) -> dict | None:
    """Best-effort budget -> {'usd': float, 'hourly': bool, 'raw': str}.

    Picks the LARGEST credible figure, so a range or a "from X to Y" phrasing is
    judged on its upper bound and the gate only kills the unambiguously cheap.
    """
    if not text:
        return None
    best: dict | None = None
    for m in _AMOUNT_RE.finditer(text):
        code = _currency_at(text, m.start(), m.end())
        if not code:
            continue                      # bare number - not a budget
        val = _to_float(m.group(1), m.group(2))
        if val is None or val <= 0:
            continue
        usd = val * config.FX_TO_USD.get(code, 1.0)
        if usd > _ABSURD_USD:
            continue                      # funding round, user count, etc.
        # hourly if "per hour" appears close after the amount (or just before,
        # for "hourly rate: $90" phrasings)
        window = text[m.start(): m.end() + 22] + " " + text[max(0, m.start() - 28): m.start()]
        hourly = bool(config.HOURLY_RE.search(window))
        cand = {"usd": usd, "hourly": hourly,
                "raw": text[max(0, m.start() - 6): m.end() + 8].strip()}
        # An hourly figure beats a bigger fixed one: "$120/hr" tells us far more
        # about the pay than a "$5,000 total" mentioned elsewhere in the post.
        if best is None or (cand["hourly"], cand["usd"]) > (best["hourly"], best["usd"]):
            best = cand
    return best


def too_low(text: str) -> tuple[bool, str]:
    """(should_gate, why). Only gates when a budget was found AND it is clearly
    under the floor - silence about money is never treated as a low budget."""
    b = extract(text)
    if b is None:
        return False, ""
    if b["hourly"]:
        if b["usd"] < config.MIN_HOURLY_USD:
            return True, f"${b['usd']:.0f}/hr < ${config.MIN_HOURLY_USD:.0f}/hr floor"
        return False, ""
    if b["usd"] <= config.MIN_BUDGET_USD:
        return True, f"${b['usd']:.0f} total <= ${config.MIN_BUDGET_USD:.0f} floor"
    return False, ""
