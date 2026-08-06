"""Hacker News monthly threads via the free Algolia API (no auth).

Monitors the two threads posted by the `whoishiring` bot each month:
  - "Ask HN: Who is hiring?"
  - "Ask HN: Freelancer? Seeking freelancer?"

One request fetches an entire thread with all comments nested.
"""
from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timezone

import httpx

from models import Lead

log = logging.getLogger("hn")
ALGOLIA = "https://hn.algolia.com/api/v1"

THREAD_PATTERNS = {
    "hn/whoishiring": re.compile(r"who is hiring", re.I),
    "hn/freelancer": re.compile(r"freelancer\?? seeking", re.I),
}


def _strip_html(s: str) -> str:
    s = re.sub(r"<p>", "\n", s or "")
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(s).strip()


def _current_thread_ids(client: httpx.Client) -> dict[str, int]:
    """Latest thread id per pattern.

    "Who is hiring?" comes from the whoishiring bot. The "Freelancer? Seeking
    freelancer?" thread was discontinued by the bot but is community-run again
    since ~April 2026 (currently posted by jon_north) - so we find it by TITLE
    QUERY across all stories, not by author.
    """
    found: dict[str, int] = {}
    r = client.get(
        f"{ALGOLIA}/search_by_date",
        params={"tags": "story,author_whoishiring", "hitsPerPage": 10},
    )
    r.raise_for_status()
    for hit in r.json().get("hits", []):
        if THREAD_PATTERNS["hn/whoishiring"].search(hit.get("title") or ""):
            found["hn/whoishiring"] = int(hit["objectID"])
            break
    r = client.get(
        f"{ALGOLIA}/search_by_date",
        params={"query": "Freelancer? Seeking freelancer?", "tags": "story",
                "hitsPerPage": 10},
    )
    r.raise_for_status()
    for hit in r.json().get("hits", []):
        if THREAD_PATTERNS["hn/freelancer"].search(hit.get("title") or ""):
            found["hn/freelancer"] = int(hit["objectID"])
            break
    return found


def fetch() -> list[Lead]:
    leads: list[Lead] = []
    with httpx.Client(timeout=30) as client:
        for source, story_id in _current_thread_ids(client).items():
            r = client.get(f"{ALGOLIA}/items/{story_id}")
            r.raise_for_status()
            thread = r.json()
            for c in thread.get("children", []):  # top-level comments = job posts
                text = _strip_html(c.get("text") or "")
                if not text or len(text) < 40:
                    continue
                created = c.get("created_at_i")
                leads.append(
                    Lead(
                        source=source,
                        url=f"https://news.ycombinator.com/item?id={c['id']}",
                        raw_text=text,
                        author=c.get("author"),
                        posted_at=datetime.fromtimestamp(created, tz=timezone.utc)
                        if created else None,
                    )
                )
    log.info("HN: fetched %d top-level comments", len(leads))
    return leads
