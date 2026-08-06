"""Keyword pre-gate: cheap regex classifier so obvious noise never reaches the
LLM (or the user's tables while no LLM is configured).

classify() returns a reason string:
  pass             -> becomes a candidate (scored when an LLM is configured)
  partnership      -> equity/co-founder ask: kept in a low-priority bucket
  gate_seeker      -> a job-SEEKER post (someone offering themselves)
  gate_community   -> unpaid volunteer / data-collection / survey ask
  gate_noise       -> admin/welcome post, course/workshop/event ad
  gate_full_time   -> full-time-only role, no freelance/contract signal
  gate_location    -> locked to another country/region (US-only, etc.); the
                      engineer is in Israel (remote or IL only)
  gate_spam        -> design/typing/marketing gig with no strong domain term
  gate_offtopic    -> fails the domain/intent keyword requirements

Order matters: identity of the POSTER (seeker) and the ASK (community/noise)
trump everything; then engagement model (FT/partnership); then topic.
"""
from __future__ import annotations

import re

import config
from models import Lead


def classify(lead: Lead) -> str:
    src_root = lead.source.split("/")[0]
    if src_root in config.GATE_BYPASS_SOURCES:
        return "pass"
    text = lead.raw_text
    if not text or len(text) < 25:
        return "gate_offtopic"

    if config.SEEKER_RE.search(text):
        return "gate_seeker"
    if config.COMMUNITY_RE.search(text):
        return "gate_community"
    if config.NOISE_RE.search(text):
        return "gate_noise"

    # Locked to another country/region with no Israel/worldwide/remote-anywhere
    # option -> the engineer (Israel-based) can't take it.
    if config.LOCATION_BLOCK_RE.search(text) and not config.LOCATION_OK_RE.search(text):
        return "gate_location"

    # user rule: 35-40+ hrs/wk is full-time in practice, whatever the label says
    # (Braintrust-style listings carry "Hours/wk: 40" on 'freelance' contracts)
    m = re.search(r"Hours/wk:\s*(\d+)", text)
    if m and int(m.group(1)) >= 35:
        return "gate_full_time"

    has_flex = bool(config.FLEX_RE.search(text))
    if not has_flex:
        # explicit FT marker, or a career-board source that is FT by default
        if config.FT_RE.search(text) or src_root in config.FT_DEFAULT_SOURCES:
            return "gate_full_time"

    if config.PARTNER_RE.search(text) and not config.BUDGET_SIGNAL_RE.search(text):
        return "partnership"

    # Spam kill: pure design/typing/marketing gigs that only matched via a weak
    # "AI ..." tag. A STRONG domain term (CV/OCR/ML/algorithm/...) rescues them.
    if config.SPAM_RE.search(text) and not config.STRONG_DOMAIN_RE.search(text):
        return "gate_spam"

    # On broad job boards every listing is an "engagement" match by definition,
    # so require actual domain relevance - same for HN threads.
    if lead.source.startswith("hn/") or src_root in config.DOMAIN_REQUIRED_SOURCES:
        return "pass" if config.DOMAIN_RE.search(text) else "gate_offtopic"
    # Discussion-heavy communities: every post matches DOMAIN, so require
    # hiring intent (ENGAGE) as well.
    if lead.source in config.INTENT_REQUIRED_SOURCES:
        ok = config.DOMAIN_RE.search(text) and config.ENGAGE_RE.search(text)
        return "pass" if ok else "gate_offtopic"
    ok = config.DOMAIN_RE.search(text) or config.ENGAGE_RE.search(text)
    return "pass" if ok else "gate_offtopic"


def passes_gate(lead: Lead) -> bool:
    """Back-compat boolean wrapper (partnerships count as not-passing)."""
    return classify(lead) == "pass"
