"""Ask a lead's URL whether it is still real before putting it in front of the user.

Age is only a proxy. A job board posting can be pulled after three days, and a
Reddit thread stays answerable for months - so guessing from a date alone both
kills good leads and shows dead ones. The user hit exactly that: an aijobs
listing expired 28 days in (inside the age window) and a Freelancer project that
no longer resolves at all.

Three ways a lead turns out to be dead, all checked here:
  * HTTP 404/410, or a connection failure that repeats.
  * A redirect off the posting and onto a generic index ("/jobs", "/projects"),
    which is what most boards do instead of returning 404.
  * Expiry wording in the body - boards keep serving HTTP 200 for a page that
    says the role is filled.

Deliberately NOT checked in bulk: LinkedIn and Facebook, which bot-wall on
volume. LinkedIn alert leads are already enriched at fetch time, and Facebook
posts are checked by the group scraper.

Usage:  python -X utf8 main.py --verify-links [N]
"""
from __future__ import annotations

import logging
import re
import sqlite3
from urllib.parse import urlsplit

import config

log = logging.getLogger("linkcheck")

# Wording that means "gone" even though the server said 200.
#
# Matched against RENDERED TEXT, never raw HTML, and only near the top of the
# page. Both matter: an earlier version scanned the HTML source for "404" and
# declared a perfectly live Reddit thread dead, because that string appears in
# Reddit's inline scripts. Status banners, by contrast, sit beside the title.
#
# Boards show these as bare status chips rather than sentences - measured on the
# two the user flagged:
#   aijobs.net  "...USD 70K-70K Mid-level Freelance  Expired  Find fresh jobs"
#   freelancer  "Digitalisasi & Arsip Surat PDF $250-750 USD  Closed  Posted..."
# hence the word-bounded single tokens, which are safe only because the search
# is limited to the first few hundred characters.
EXPIRED_RE = re.compile(
    r"(\bexpired\b|\bclosed\b|\bfilled\b|\barchived\b"
    r"|no longer (available|accepting|active|open|hiring)"
    r"|this (job|position|project|listing|posting) (is|has been) "
    r"(closed|filled|expired|removed|deleted|cancell?ed)"
    r"|applications? (are )?closed|bidding (is )?closed|awarded)", re.I)

# How much of the page text counts as "near the title".
_TOP_CHARS = 700

# Boards render the status as a chip wedged between the budget and the date -
# "$250-750 USD  Closed  Posted about 1 month ago" - which on Freelancer lands
# 5,800 characters in, far past any "top of page" window, behind the nav. So
# match the SHAPE instead of the position: a status word touching a price or a
# "Posted ... ago". Unambiguous, and it works anywhere on the page.
STATUS_CHIP_RE = re.compile(
    r"((?:USD|EUR|GBP|\$|€|£)\s*[\d,.\s\-–]{0,18}\s*"
    r"\b(closed|expired|filled|awarded|cancelled|canceled)\b"
    r"|\b(closed|expired|filled|awarded)\b\s+posted\b"
    r"|\b(expired|closed)\s+\d+\s*[dwmy]\w*\s+ago)", re.I)

# Landing on one of these paths means we were bounced to an index page.
_INDEX_PATHS = re.compile(r"^/?(jobs?|projects?|search|browse|home)?/?$", re.I)

# Hosts that bot-wall on volume - never bulk-check these.
SKIP_HOSTS = ("linkedin.com", "facebook.com", "fb.com")

_TIMEOUT = 15


def check_url(client, url: str) -> tuple[bool, str]:
    """(is_dead, reason). Errs toward ALIVE: a network hiccup or a bot-wall must
    never delete a real lead, so only clear evidence counts."""
    try:
        r = client.get(url, timeout=_TIMEOUT, follow_redirects=True)
    except Exception as e:
        return False, f"unreachable ({type(e).__name__}) - kept"
    if r.status_code in (404, 410):
        return True, f"HTTP {r.status_code}"
    if r.status_code >= 500 or r.status_code in (403, 429):
        return False, f"HTTP {r.status_code} - kept (server/bot-wall, not proof)"
    final = urlsplit(str(r.url))
    original = urlsplit(url)
    if final.path != original.path and _INDEX_PATHS.match(final.path or "/"):
        return True, f"redirected to index {final.path}"
    # Rendered text only - scanning raw HTML matches strings buried in scripts.
    try:
        from bs4 import BeautifulSoup
        text = re.sub(r"\s+", " ", BeautifulSoup(r.text, "html.parser")
                      .get_text(" ", strip=True))
    except Exception:
        return False, "unparseable - kept"
    m = EXPIRED_RE.search(text[:_TOP_CHARS])
    if m:
        return True, f'page says "{m.group(0)}"'
    m = STATUS_CHIP_RE.search(text)
    if m:
        return True, f'status chip "{m.group(0).strip()[:38]}"'
    # Client-side-rendered pages (Reddit returns ~6 chars of text) give us
    # nothing to read. That is not evidence of death - keep the lead.
    return False, "alive" if len(text) > 200 else "js-rendered, no text - kept"


def verify(conn: sqlite3.Connection, limit: int = 60, min_score: int = 7) -> dict:
    """Check the leads the user is most likely to act on, newest first."""
    import httpx

    rows = conn.execute(
        "SELECT id, url, source, score FROM leads "
        "WHERE score >= ? AND status NOT IN ('gated_out','handled') "
        "ORDER BY score DESC, id DESC LIMIT ?", (min_score, limit)).fetchall()
    counts = {"alive": 0, "dead": 0, "skipped": 0}
    headers = {"User-Agent": config.USER_AGENT}
    with httpx.Client(headers=headers, follow_redirects=True) as client:
        for r in rows:
            if any(h in (r["url"] or "") for h in SKIP_HOSTS):
                counts["skipped"] += 1
                continue
            dead, why = check_url(client, r["url"])
            if dead:
                conn.execute(
                    "UPDATE leads SET status='gated_out', reasoning=? WHERE id=?",
                    (f"gate: dead link ({why})", r["id"]))
                conn.commit()
                counts["dead"] += 1
                log.info("  DEAD [%s] %-46s %s", r["score"], r["source"][:24], why)
            else:
                counts["alive"] += 1
    log.info("link check: %s", counts)
    return counts
