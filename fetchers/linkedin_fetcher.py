"""LinkedIn fetcher - logged-out guest endpoints, no account, no key.

LinkedIn serves its job search to signed-out visitors through two "jobs-guest"
endpoints that return plain HTML fragments:

  1. .../seeMoreJobPostings/search  -> up to 10 job CARDS per query
     (title, company, location, posted date, link). Filters used:
       f_JT=P,C,T  part-time / contract / temporary
       f_WT=2      remote               f_TPR=r86400  posted in the last 24h
  2. .../jobPosting/<job_id>        -> the full description + the
     "Employment type / Seniority level" criteria list.

Two things learned by probing the live endpoints, both load-bearing:

  * The guest filters are UNRELIABLE and NON-DETERMINISTIC. Measured: f_JT does
    work sometimes (f_JT=C and f_JT=F return disjoint result sets), but the same
    query re-run minutes later can silently ignore it - one probe of
    f_JT=P,C,T&f_WT=2&f_TPR=r604800 returned exactly the same 10 jobs as an
    explicit f_JT=F (full-time) query, i.e. LinkedIn dropped both the job-type
    and the remote filter and served generic results. So the "Employment type"
    criteria line is folded into raw_text and the normal FT_RE gate does the
    real filtering. The URL filters are a hint, never a guarantee - expect a
    large share of every run to be gated out as full-time, and never assume a
    returned job matched the filters you asked for.
  * Card links carry a country subdomain and a slug
    ("https://at.linkedin.com/jobs/view/computer-vision-engineer-at-specs-4440682438?...").
    The same job reached from the email alerts looks different again
    ("linkedin.com/comm/jobs/view/<id>?trackingId=..."), so every URL is
    canonicalised to https://www.linkedin.com/jobs/view/<id> - that is the
    shared dedup key between this fetcher and the email path.

The card alone has no contract/hours/location-restriction text, so a job is
only ingested once its description has been fetched. Detail fetches are capped
per run (LINKEDIN_DETAIL_CAP); jobs over the cap are simply not ingested and
are picked up on the next run, still inside the 24h freshness window.

LinkedIn bot-walls aggressively (HTTP 999/403). On a wall we abort the run and
set a 6h cooldown in the kv store - retrying a 999 only extends the block.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import time
from datetime import datetime, timezone

import config
import db
from models import Lead

log = logging.getLogger("linkedin")

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"

# "/jobs/view/computer-vision-engineer-at-specs-4440682438" -> 4440682438
# also matches the bare "/jobs/view/4440682438" form used in alert emails
JOB_ID_RE = re.compile(r"/jobs/view/(?:[^/?#]*?-)?(\d{6,})")

# Rendered in the topcard of a closed posting, for signed-out visitors too.
CLOSED_RE = re.compile(r"no longer accepting applications", re.I)

_SEARCH_SLEEP = 10          # seconds between search queries
_DETAIL_SLEEP = 8           # seconds between detail fetches
_BLOCK_COOLDOWN = 6 * 3600  # after a 999/403 bot-wall
_KV_BLOCKED_UNTIL = "li_blocked_until"


class _Blocked(Exception):
    """LinkedIn served a bot-wall; abort the run and cool down."""


def canonical_job_url(url: str) -> str | None:
    """Any LinkedIn job URL -> https://www.linkedin.com/jobs/view/<id>.

    Collapses country subdomains, title slugs, /comm/ email links and tracking
    params so the scraped and email-alert paths dedup against each other.
    """
    m = JOB_ID_RE.search(url or "")
    if not m:
        return None
    return f"https://www.linkedin.com/jobs/view/{m.group(1)}"


def _get(client, url: str, params: dict | None = None):
    r = client.get(url, params=params)
    if r.status_code in (999, 403):
        raise _Blocked(f"HTTP {r.status_code}")
    if r.status_code == 429:
        log.info("rate-limited; backing off 30s")
        time.sleep(30)
        r = client.get(url, params=params)
        if r.status_code in (999, 403):
            raise _Blocked(f"HTTP {r.status_code}")
        if r.status_code == 429:
            raise _Blocked("429 twice")
    r.raise_for_status()
    return r


def _search(client, keywords: str, location: str, geo_id: str, remote: bool,
            region: str = "WW", easy: bool = False) -> list[dict]:
    """One search query -> list of {job_id, url, title, company, location, posted_at, region, easy}."""
    from bs4 import BeautifulSoup

    params = {
        "keywords": keywords,
        "location": location,
        "f_JT": "P,C,T",      # part-time / contract / temporary (loosely applied)
        "f_TPR": "r86400",    # last 24h
        "start": "0",
    }
    if geo_id:
        params["geoId"] = geo_id
    if remote:
        params["f_WT"] = "2"
    if easy:
        # f_AL is the one filter measured to actually work (see config).
        params["f_AL"] = "true"
        params["f_TPR"] = config.LINKEDIN_EASYAPPLY_TPR

    r = _get(client, SEARCH_URL, params)
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for card in soup.select("div.base-card"):
        a = card.select_one("a.base-card__full-link") or card.select_one("a[href*='/jobs/view/']")
        href = a.get("href") if a else ""
        url = canonical_job_url(href or "")
        if not url:
            continue
        m = JOB_ID_RE.search(href)
        title = card.select_one(".base-search-card__title")
        company = card.select_one(".base-search-card__subtitle")
        loc = card.select_one(".job-search-card__location")
        tm = card.select_one("time")
        posted = None
        if tm and tm.get("datetime"):
            try:
                posted = datetime.fromisoformat(tm["datetime"]).replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        out.append({
            "job_id": m.group(1),
            "url": url,
            "title": title.get_text(strip=True) if title else "",
            "company": company.get_text(strip=True) if company else "",
            "location": loc.get_text(strip=True) if loc else "",
            "posted_at": posted,
            "region": region,
            "easy": easy,
        })
    return out


def _detail_meta(client, job_id: str) -> dict:
    """Job id -> description, criteria, real post age, and applicant count.

    The applicant count is the competition signal the user actually rates on -
    a 200-applicant posting is the LinkedIn equivalent of a marketplace bid war
    and is worth near zero, however well it matches. The "N days ago" line is
    the only reliable post date for the email path, whose own date is just when
    the alert was mailed.

    "closed" reports whether the posting stopped accepting applications. An
    earlier probe concluded this was invisible logged-out and that was WRONG -
    it checked a job that happened to still be open. The banner does render for
    signed-out visitors ("... 3 weeks ago Be among the first 25 applicants ...
    No longer accepting applications"), but it lives in the topcard, NOT in the
    description div, which is why a description-only search kept missing it.
    Hence the whole-page text below.
    """
    from bs4 import BeautifulSoup

    r = _get(client, DETAIL_URL.format(job_id=job_id))
    soup = BeautifulSoup(r.text, "html.parser")
    desc_el = soup.select_one("div.show-more-less-html__markup")
    desc = desc_el.get_text("\n", strip=True) if desc_el else ""
    criteria = []
    for li in soup.select("li.description__job-criteria-item"):
        head = li.select_one("h3")
        val = li.select_one("span")
        if head and val:
            criteria.append(f"{head.get_text(strip=True)}: {val.get_text(strip=True)}")

    def _txt(sel):
        el = soup.select_one(sel)
        return el.get_text(strip=True) if el else ""

    posted_ago = _txt(".posted-time-ago__text")
    applicants = _txt(".num-applicants__caption")
    page_text = soup.get_text(" ", strip=True)
    closed = bool(CLOSED_RE.search(page_text))
    return {"desc": desc, "criteria": "\n".join(criteria),
            "posted_ago": posted_ago, "applicants": applicants, "closed": closed}


def _detail(client, job_id: str) -> tuple[str, str]:
    """Job id -> (description text, 'Employment type: Contract' style criteria lines)."""
    d = _detail_meta(client, job_id)
    return d["desc"], d["criteria"]


def _known(conn: sqlite3.Connection, url: str) -> bool:
    row = conn.execute("SELECT 1 FROM leads WHERE url_hash = ?", (db.url_hash(url),)).fetchone()
    return row is not None


def fetch(conn: sqlite3.Connection) -> list[Lead]:
    import httpx

    blocked_until = db.kv_get(conn, _KV_BLOCKED_UNTIL, "0")
    try:
        if time.time() < float(blocked_until or 0):
            mins = int((float(blocked_until) - time.time()) / 60)
            log.info("cooling down after a bot-wall; %d min left", mins)
            return []
    except ValueError:
        pass

    queries = [(kw, "Worldwide", "92000000", True, "WW", False) for kw in config.LINKEDIN_QUERIES]
    # Israel searches drop the remote filter so on-site-in-Israel gigs surface too
    queries += [(kw, "Israel", "", False, "IL", False) for kw in config.LINKEDIN_IL_QUERIES]
    # Easy Apply pass: one-tap applications, so they're worth surfacing separately
    # even though most will gate out as full-time. Israel first, then worldwide-remote.
    if config.LINKEDIN_EASYAPPLY:
        queries += [(kw, "Israel", "", False, "IL", True)
                    for kw in config.LINKEDIN_EASYAPPLY_QUERIES]
        queries += [(kw, "Worldwide", "92000000", True, "WW", True)
                    for kw in config.LINKEDIN_EASYAPPLY_QUERIES]

    headers = {"User-Agent": config.USER_AGENT,
               "Accept": "text/html,application/xhtml+xml"}
    cards: dict[str, dict] = {}
    leads: list[Lead] = []

    with httpx.Client(headers=headers, timeout=25, follow_redirects=True) as client:
        try:
            for i, (kw, loc, geo, remote, region, easy) in enumerate(queries):
                if i:
                    time.sleep(_SEARCH_SLEEP)
                try:
                    for c in _search(client, kw, loc, geo, remote, region, easy):
                        cards.setdefault(c["url"], c)   # dedup across queries
                except _Blocked:
                    raise
                except Exception as e:
                    log.error("search %r/%s failed: %s", kw, loc, e)

            fresh = [c for c in cards.values() if not _known(conn, c["url"])]
            # Israel first, then Easy Apply: the engineer is in Israel, so IL gigs
            # (remote OR on-site) are the highest-value segment, and a one-tap
            # application is worth more than an equivalent 20-minute one. Without
            # this sort the worldwide queries - which run first - would eat the
            # detail-fetch cap every time.
            fresh.sort(key=lambda c: (0 if c["region"] == "IL" else 1,
                                      0 if c.get("easy") else 1))
            log.info("%d cards, %d new (%d IL, %d easy-apply)", len(cards), len(fresh),
                     sum(1 for c in fresh if c["region"] == "IL"),
                     sum(1 for c in fresh if c.get("easy")))
            if len(fresh) > config.LINKEDIN_DETAIL_CAP:
                log.info("capping detail fetches at %d; the rest come next run",
                         config.LINKEDIN_DETAIL_CAP)
            for i, c in enumerate(fresh[:config.LINKEDIN_DETAIL_CAP]):
                if i:
                    time.sleep(_DETAIL_SLEEP)
                try:
                    d = _detail_meta(client, c["job_id"])
                except _Blocked:
                    raise
                except Exception as e:
                    log.error("detail %s failed: %s", c["job_id"], e)
                    continue
                desc, criteria = d["desc"], d["criteria"]
                if not desc:
                    continue
                if d.get("closed"):
                    log.info("skipping %s - no longer accepting applications",
                             c["job_id"])
                    continue
                easy_line = "Application: LinkedIn Easy Apply (one-tap)\n" if c.get("easy") else ""
                # applicant count = the competition signal the user rates on
                meta = " | ".join(x for x in (d["posted_ago"], d["applicants"]) if x)
                text = (f"{c['title']} at {c['company']}\n"
                        f"Location: {c['location']}\n{easy_line}"
                        f"{meta}\n{criteria}\n\n{desc[:3500]}")
                leads.append(Lead(
                    source="linkedin/easyapply" if c.get("easy") else "linkedin",
                    url=c["url"],
                    raw_text=text,
                    author=c["company"] or None,
                    posted_at=c["posted_at"],
                ))
        except _Blocked as e:
            db.kv_set(conn, _KV_BLOCKED_UNTIL, str(time.time() + _BLOCK_COOLDOWN))
            log.warning("LinkedIn bot-wall (%s); cooling down 6h, returning %d partial lead(s)",
                        e, len(leads))

    log.info("LinkedIn: %d leads", len(leads))
    return leads
