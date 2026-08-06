"""Reddit fetcher.

Two modes, both free:
  1. If REDDIT_CLIENT_ID/SECRET are set -> official API via PRAW (higher limits).
  2. Otherwise -> Reddit's PUBLIC RSS feeds (no login, no keys). Reddit now
     403-blocks the unauthenticated /new.json endpoint from many IPs, but still
     serves /r/<sub>/new/.rss to a client sending a unique, descriptive
     User-Agent (a browser UA gets rate-limited; the lead-agent UA works).

So Reddit works out of the box; add credentials later only if you want headroom.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

import config
from models import Lead

log = logging.getLogger("reddit")

_ATOM = "{http://www.w3.org/2005/Atom}"
_TAG_RE = re.compile(r"<[^>]+>")


def _is_offering(sub: str, title: str) -> bool:
    # Reddit-wide convention: [Hiring] = seeking someone, [For Hire] = offering
    # services. Offering posts are never leads, whatever the sub.
    return "[for hire]" in title.lower()


def _fetch_praw() -> list[Lead]:
    import praw  # lazy import

    reddit = praw.Reddit(
        client_id=config.REDDIT_CLIENT_ID,
        client_secret=config.REDDIT_CLIENT_SECRET,
        user_agent=config.REDDIT_USER_AGENT,
    )
    reddit.read_only = True

    leads: list[Lead] = []
    for sub in config.SUBREDDITS:
        try:
            for post in reddit.subreddit(sub).new(limit=25):
                title = post.title or ""
                if _is_offering(sub, title):
                    continue
                leads.append(Lead(
                    source=f"r/{sub}",
                    url=f"https://www.reddit.com{post.permalink}",
                    raw_text=f"{title}\n\n{post.selftext or ''}",
                    author=str(post.author) if post.author else None,
                    posted_at=datetime.fromtimestamp(post.created_utc, tz=timezone.utc),
                ))
        except Exception as e:
            log.error("r/%s (praw) fetch failed: %s", sub, e)
    log.info("Reddit (API): fetched %d posts", len(leads))
    return leads


def _text(entry, tag: str) -> str:
    el = entry.find(_ATOM + tag)
    return (el.text or "").strip() if el is not None else ""


def _parse_feed(content: bytes, source: str) -> list[Lead]:
    """Parse a Reddit Atom feed (sub feed or search feed) into Leads."""
    leads: list[Lead] = []
    feed = ET.fromstring(content)
    for entry in feed.findall(_ATOM + "entry"):
        title = _text(entry, "title")
        if _is_offering(source, title):
            continue
        link_el = entry.find(_ATOM + "link")
        url = link_el.get("href") if link_el is not None else ""
        # search.rss mixes SUBREDDIT hits (".../r/computervision/") in with post
        # hits; only real permalinks ("/comments/<id>/...") are leads.
        if "/comments/" not in (url or ""):
            continue
        author = ""
        author_el = entry.find(_ATOM + "author")
        if author_el is not None:
            author = (author_el.findtext(_ATOM + "name") or "").strip()
        body = _TAG_RE.sub(" ", _text(entry, "content"))
        body = re.sub(r"\s+", " ", body).strip()
        published = _text(entry, "published")
        posted = None
        if published:
            try:
                posted = datetime.fromisoformat(published.replace("Z", "+00:00"))
            except ValueError:
                pass
        leads.append(Lead(
            source=source,
            url=url,
            raw_text=f"{title}\n\n{body}",
            author=author or None,
            posted_at=posted,
        ))
    return leads


def _get_with_backoff(client, url: str, params: dict, label: str):
    """GET with Reddit's two-step 429 backoff. Returns the response."""
    r = client.get(url, params=params)
    for backoff in (20, 40):                # two backoff retries on 429
        if r.status_code != 429:
            break
        log.info("%s rate-limited; backing off %ds", label, backoff)
        time.sleep(backoff)
        r = client.get(url, params=params)
    r.raise_for_status()
    return r


def _fetch_public_rss() -> list[Lead]:
    import httpx

    headers = {"User-Agent": config.REDDIT_USER_AGENT}
    leads: list[Lead] = []
    with httpx.Client(headers=headers, timeout=20, follow_redirects=True) as client:
        for i, sub in enumerate(config.SUBREDDITS):
            if i:
                time.sleep(8)  # Reddit rate-limits bursts; space requests out
            try:
                r = _get_with_backoff(
                    client, f"https://www.reddit.com/r/{sub}/new/.rss",
                    {"limit": 25}, f"r/{sub}")
                leads.extend(_parse_feed(r.content, f"r/{sub}"))
            except Exception as e:
                log.error("r/%s (rss) fetch failed: %s", sub, e)
    log.info("Reddit (public RSS): fetched %d posts", len(leads))
    return leads


def fetch() -> list[Lead]:
    if config.REDDIT_CLIENT_ID and config.REDDIT_CLIENT_SECRET:
        return _fetch_praw()
    return _fetch_public_rss()


def fetch_search() -> list[Lead]:
    """Sitewide Reddit search via search.rss - finds hiring posts in subs we
    don't poll. Keyless; same UA + backoff as the sub feeds. Results are fuzzy
    (Reddit honours booleans loosely), so r/search is gated as an
    INTENT_REQUIRED source and cross-posts dedup on url_hash downstream."""
    import httpx

    headers = {"User-Agent": config.REDDIT_USER_AGENT}
    leads: list[Lead] = []
    with httpx.Client(headers=headers, timeout=20, follow_redirects=True) as client:
        for i, query in enumerate(config.REDDIT_SEARCHES):
            if i:
                time.sleep(8)
            try:
                r = _get_with_backoff(
                    client, "https://www.reddit.com/search.rss",
                    {"q": query, "sort": "new", "t": "week"}, "r/search")
                leads.extend(_parse_feed(r.content, "r/search"))
            except Exception as e:
                log.error("reddit search %r failed: %s", query, e)
    log.info("Reddit (search): fetched %d posts", len(leads))
    return leads
