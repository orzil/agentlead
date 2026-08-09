"""Facebook group posts via the SEARCH INDEX - never touching facebook.com.

Why this exists: logged-out scraping of Facebook is dead from any datacenter IP.
Measured 2026-08-09 from a GitHub runner - www, mbasic, m, touch and a mobile UA
ALL redirect to login.php, and three consecutive cloud runs produced 0 Facebook
leads, walled on the first group every time. Meta blocks the IP range on
reputation, so no amount of pacing, headers or alternate endpoints helps.

Search engines, however, already crawled those public posts. Asking the INDEX
returns post-level permalinks plus a snippet of the post text:

    facebook.com/groups/freelance.hightech/permalink/7426400877397482
    facebook.com/groups/fivemserverdevelopmenthelp2025/posts/832214689133011

We issue zero requests to Facebook, so there is nothing to rate-limit and no ban
risk of any kind. Or opens the permalink logged in, as a human, and replies
normally.

Two query families:
  * per-group  - site:facebook.com/groups/<slug>, keeping posts flowing from the
                 22 curated groups the scraper can no longer read.
  * intent     - site:facebook.com/groups "looking for a developer", which finds
                 posts in groups nobody has catalogued yet.

The snippet is only ~200 characters, so the scorer sees much less than a full
post and returns "unclear" more often. That is an accepted trade: the lead's job
is to put Or in front of a live permalink, not to reproduce the post.
"""
from __future__ import annotations

import logging
import re
import time

import config
import db
from models import Lead

log = logging.getLogger("fbsearch")

# Only individual POSTS are leads. A group root or a profile URL is not - the
# same reasoning as reddit_fetcher keeping only /comments/ permalinks.
POST_URL_RE = re.compile(
    r"https?://(?:www\.|m\.|web\.)?facebook\.com/groups/"
    r"(?P<slug>[A-Za-z0-9._-]{3,60})/(?:posts|permalink)/(?P<pid>\d{6,})",
    re.IGNORECASE)

_SLEEP = 12          # between the (few) queries a single run is allowed
_LITE = "https://lite.duckduckgo.com/lite/"


def canonical_post_url(url: str) -> str | None:
    """Any Facebook post URL -> https://www.facebook.com/groups/<slug>/posts/<id>.

    DDG hands back mobile hosts, /permalink/ and /posts/ forms and tracking
    query strings for the same post; collapsing them is what lets the existing
    url_hash dedup in db.insert_lead do its job across runs.
    """
    m = POST_URL_RE.search(url or "")
    if not m:
        return None
    return (f"https://www.facebook.com/groups/{m.group('slug')}"
            f"/posts/{m.group('pid')}")


def _results(html: str) -> list[tuple[str, str, str]]:
    """DDG /lite/ HTML -> [(post_url, title, snippet)].

    The lite layout is a flat table: a row carries the result link, a later row
    carries its snippet, so state is tracked across rows rather than nested.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    out: list[tuple[str, str, str]] = []
    pending: tuple[str, str] | None = None
    for tr in soup.select("tr"):
        a = tr.select_one("a.result-link") or tr.select_one("a[href*='facebook.com/groups']")
        if a is not None:
            url = canonical_post_url(a.get("href") or "")
            pending = (url, a.get_text(" ", strip=True)) if url else None
            continue
        sn = tr.select_one("td.result-snippet") or tr.select_one(".result-snippet")
        if sn is not None and pending:
            out.append((pending[0], pending[1], sn.get_text(" ", strip=True)))
            pending = None
    # A result whose snippet row never arrived is still a usable lead.
    if pending:
        out.append((pending[0], pending[1], ""))
    return out


def _clean_title(title: str) -> str:
    for suffix in (" | Facebook", " - Facebook", " | פייסבוק"):
        if title.endswith(suffix):
            title = title[: -len(suffix)]
    return title.strip()


def search(queries: list[str], conn=None) -> list[Lead]:
    """Run a small batch of index queries and return post leads."""
    import httpx

    headers = {"User-Agent": config.USER_AGENT, "Accept": "text/html",
               "Accept-Language": "en-US,en;q=0.9,he;q=0.8"}
    leads: list[Lead] = []
    seen: set[str] = set()
    with httpx.Client(headers=headers, timeout=20, follow_redirects=True) as client:
        for i, q in enumerate(queries):
            if i:
                time.sleep(_SLEEP)
            try:
                r = client.post(_LITE, data={"q": q})
            except Exception as e:
                log.error("query %r failed: %s", q[:50], e)
                continue
            if r.status_code != 200 or "anomaly" in r.text.lower():
                log.warning("DDG challenge (HTTP %s) after %d quer(y/ies) - stopping",
                            r.status_code, i)
                break
            found = 0
            for url, title, snippet in _results(r.text):
                if url in seen:
                    continue
                seen.add(url)
                text = f"{_clean_title(title)}\n\n{snippet}".strip()
                if len(text) < 40:      # nothing to gate or score on
                    continue
                leads.append(Lead(source="facebook/search", url=url, raw_text=text))
                found += 1
            log.info("  %-54s -> %d post(s)", q[:54], found)
    log.info("fbsearch: %d post lead(s) from %d quer(y/ies)", len(leads), len(queries))
    return leads


def fetch(conn) -> list[Lead]:
    """Scheduler entry point: take this run's slice of the query rotation."""
    queries = config.fb_post_queries()
    per_run = int(config.env("FBSEARCH_QUERIES_PER_RUN", "2"))
    cursor = int(db.kv_get(conn, "fbsearch_cursor", "0") or "0") % len(queries)
    batch = [queries[(cursor + i) % len(queries)] for i in range(min(per_run, len(queries)))]
    db.kv_set(conn, "fbsearch_cursor", str((cursor + len(batch)) % len(queries)))
    log.info("fbsearch: cursor %d/%d", cursor, len(queries))
    return search(batch, conn)
