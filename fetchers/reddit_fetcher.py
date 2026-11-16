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


_SEARCH_SUB_MARK = "search-sub"     # feed kind: a sub read in place of sitewide search
_oauth: dict = {"token": "", "until": 0.0}


def _has_oauth() -> bool:
    return bool(config.REDDIT_CLIENT_ID and config.REDDIT_CLIENT_SECRET)


def _oauth_token(client) -> str:
    """Application-only OAuth token (read-only, no user login), cached ~1h.
    Sitewide search is 403 for keyless clients since 2026-11-10; with a token it
    is served from oauth.reddit.com at the API's far higher limits."""
    if _oauth["token"] and time.time() < _oauth["until"]:
        return _oauth["token"]
    r = client.post("https://www.reddit.com/api/v1/access_token",
                    auth=(config.REDDIT_CLIENT_ID, config.REDDIT_CLIENT_SECRET),
                    data={"grant_type": "client_credentials"})
    r.raise_for_status()
    d = r.json()
    _oauth["token"] = d["access_token"]
    _oauth["until"] = time.time() + int(d.get("expires_in", 3600)) - 120
    return _oauth["token"]


def _parse_listing(data: dict, source: str) -> list[Lead]:
    """Parse an API listing (oauth.reddit.com/search) into Leads."""
    leads: list[Lead] = []
    for child in (data.get("data") or {}).get("children") or []:
        if child.get("kind") != "t3":
            continue
        p = child.get("data") or {}
        title = p.get("title") or ""
        if _is_offering(source, title) or not p.get("permalink"):
            continue
        leads.append(Lead(
            source=source,
            url=f"https://www.reddit.com{p['permalink']}",
            raw_text=f"{title}\n\n{p.get('selftext') or ''}",
            author=p.get("author") or None,
            posted_at=(datetime.fromtimestamp(p["created_utc"], tz=timezone.utc)
                       if p.get("created_utc") else None),
        ))
    return leads


def _title_filtered(leads: list[Lead]) -> list[Lead]:
    """Keep what the sitewide `title:(hiring OR task) (<domain terms>)` search
    would have kept. The domain check happens here, not only in the gate:
    r/jobboardsearch alone posts ~1,350 a day, and storing them all as gated
    rows would double the DB and the fuzzy-dedup work for nothing."""
    return [l for l in leads
            if config.REDDIT_SEARCH_TITLE_RE.search(l.raw_text.split("\n", 1)[0])
            and config.DOMAIN_RE.search(l.raw_text)]


def _trickle_feeds() -> list[tuple[str, str, dict, str]]:
    """(source label, url, params, kind) for every feed: polled subs, the subs
    read in place of sitewide search, and - only with API credentials - the
    sitewide searches themselves (keyless they are a 403 and waste the slot)."""
    feeds = [(f"r/{s}", f"https://www.reddit.com/r/{s}/new/.rss", {"limit": 25}, "sub")
             for s in config.SUBREDDITS]
    feeds += [("r/search", f"https://www.reddit.com/r/{s}/new/.rss", {"limit": 100},
               _SEARCH_SUB_MARK) for s in config.REDDIT_SEARCH_SUBS]
    if _has_oauth():
        feeds += [("r/search", "https://oauth.reddit.com/search",
                   {"q": q, "sort": "new", "t": "week", "limit": 50, "raw_json": 1},
                   "oauth-search") for q in config.REDDIT_SEARCHES]
    return feeds


def _note_feed_result(conn, name: str, ok: bool) -> None:
    """Count consecutive failures per feed; raise at the threshold so
    run_job_safe sends its (throttled) Telegram alert. A feed that fails
    quietly is how sitewide search stayed dead for six days."""
    import db
    key = f"reddit_fail_{name}"
    if ok:
        if db.kv_get(conn, key, "0") != "0":
            db.kv_set(conn, key, "0")
        return
    n = int(db.kv_get(conn, key, "0") or 0) + 1
    db.kv_set(conn, key, str(n))
    if n % config.REDDIT_FEED_FAIL_ALERT == 0:
        raise RuntimeError(f"Reddit feed {name} failed {n} times in a row")


def fetch_next(conn) -> tuple[list[Lead], bool]:
    """Home trickle: fetch ONE feed (round-robin, cursor in kv) and return
    (leads, ok). A 429 does not advance the cursor; it waits out Reddit's own
    x-ratelimit-reset instead of the blind 20/40 s backoff."""
    import httpx
    import db

    if time.time() < float(db.kv_get(conn, "reddit_trickle_wait", "0") or 0):
        return [], False
    feeds = _trickle_feeds()
    i = int(db.kv_get(conn, "reddit_trickle_i", "0") or 0) % len(feeds)
    label, url, params, kind = feeds[i]
    name = url.split("/r/")[1].split("/")[0] if "/r/" in url else kind
    with httpx.Client(headers={"User-Agent": config.REDDIT_USER_AGENT}, timeout=20,
                      follow_redirects=True) as client:
        headers = ({"Authorization": f"bearer {_oauth_token(client)}"}
                   if kind == "oauth-search" else {})
        r = client.get(url, params=params, headers=headers)
    if r.status_code == 429:
        reset = float(r.headers.get("x-ratelimit-reset", "30") or 30)
        db.kv_set(conn, "reddit_trickle_wait", str(time.time() + reset + 2))
        log.info("reddit trickle: %s rate-limited, waiting %.0fs", label, reset + 2)
        return [], False
    # any other answer moves on: a dead feed (404 - r/freelance_forhire, 2026-11-04)
    # must not pin the rotation to itself
    db.kv_set(conn, "reddit_trickle_i", str(i + 1))
    if r.status_code != 200:
        if r.status_code == 401:
            _oauth["token"] = ""
        log.warning("reddit trickle: %s (%s) -> HTTP %d, skipped", label, name, r.status_code)
        _note_feed_result(conn, name, False)
        return [], False
    _note_feed_result(conn, name, True)
    if kind == "oauth-search":
        leads = _parse_listing(r.json(), label)
    else:
        leads = _parse_feed(r.content, label)
        if kind == _SEARCH_SUB_MARK:
            total = len(leads)
            leads = _title_filtered(leads)
            log.info("reddit trickle: %s via r/%s -> %d of %d posts (feed %d/%d)",
                     label, name, len(leads), total, i + 1, len(feeds))
            return leads, True
    log.info("reddit trickle: %s -> %d posts (feed %d/%d)", label, len(leads), i + 1, len(feeds))
    return leads, True


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
        # the subs read in place of the keyless search (403 since 2026-11-10)
        for i, sub in enumerate(config.REDDIT_SEARCH_SUBS):
            if i:
                time.sleep(8)
            try:
                r = _get_with_backoff(
                    client, f"https://www.reddit.com/r/{sub}/new/.rss",
                    {"limit": 100}, f"r/{sub}")
                leads.extend(_title_filtered(_parse_feed(r.content, "r/search")))
            except Exception as e:
                log.error("r/%s (search-sub) fetch failed: %s", sub, e)
        if _has_oauth():
            for query in config.REDDIT_SEARCHES:
                time.sleep(2)
                try:
                    r = client.get(
                        "https://oauth.reddit.com/search",
                        params={"q": query, "sort": "new", "t": "week", "limit": 50,
                                "raw_json": 1},
                        headers={"Authorization": f"bearer {_oauth_token(client)}"})
                    r.raise_for_status()
                    leads.extend(_parse_listing(r.json(), "r/search"))
                except Exception as e:
                    log.error("reddit search %r failed: %s", query, e)
    log.info("Reddit (search): fetched %d posts", len(leads))
    return leads
