"""Find Facebook groups worth scraping (public) or JOINING (private).

Companion to probe_fb_groups.py, which only re-probes groups already listed in
config.FACEBOOK_GROUPS. This script finds groups that aren't in that list yet.

Division of labour, and the reason for it:
  * PUBLIC groups  -> graduate into config.FACEBOOK_GROUPS and are scraped
                      logged-out, which never touches the user's account.
  * PRIVATE groups -> written to a ranked join list (facebook_groups.md) plus one
                      Telegram ping. The user joins by hand and turns on "All
                      posts" notifications; email_fetcher then ingests them over
                      IMAP. The agent NEVER sends a join request - automating the
                      user's Facebook account is the one thing that can get it
                      banned, and a scraper block only ever costs us an IP.

Discovery surfaces, cheapest first (all free, all logged-out):
  1. mine_db  - facebook.com/groups/<slug> links already sitting in fetched posts.
                Zero network. Measured 2026-08-06: 17 slugs found, ALL already in
                config, 0 new. Unlike WhatsApp - where invite links get shared
                constantly and DB-mining was the best surface - FB posts mostly
                link their own group. Kept because it costs nothing.
  2. search_ddg - DuckDuckGo HTML. Measured the same day as the ONLY engine still
                serving organic results from this IP (Bing/Startpage/Mojeek all
                captcha-walled, Brave 429'd). Detects the challenge and skips
                rather than failing the run.

PROBING is deliberately NOT done here. Facebook rate-limits per IP, and a block
on the machine the user browses Facebook from surfaces as a login/checkpoint wall
on THEIR account. Probing therefore runs in GitHub Actions (--probe, see
SETUP_CLOUD.md), never on the user's home IP.

Usage:
  python -X utf8 discover_fb_groups.py                  # mine + rank + table
  python -X utf8 discover_fb_groups.py --search         # + DuckDuckGo surface
  python -X utf8 discover_fb_groups.py --probe          # CLOUD ONLY: classify pending
  python -X utf8 discover_fb_groups.py --write          # + facebook_groups.md
  python -X utf8 discover_fb_groups.py --notify         # Telegram-ping new finds
  python -X utf8 discover_fb_groups.py --joined <slug>  # mark a private group joined
  python -X utf8 discover_fb_groups.py --config-lines   # paste-ready config entries
"""
from __future__ import annotations

import argparse
import logging
import re
import sqlite3
import time
from datetime import datetime, timezone

import config
import db
import notifier

log = logging.getLogger("fbgroups")

# facebook.com/groups/<slug>. Slugs are either numeric ids or vanity names.
FB_GROUP_RE = re.compile(r"facebook\.com/groups/([A-Za-z0-9._-]{3,60})", re.IGNORECASE)
HEBREW_RE = re.compile("[֐-׿]")

# Path segments that look like slugs but aren't groups.
_NOT_A_SLUG = {"search", "feed", "discover", "create", "permalink", "posts",
               "joins", "member", "members", "about", "www", "groups"}

_DDG_SLEEP = 10
_REDDIT_SLEEP = 8
_PROBE_SLEEP = 20   # FB throttles ~10 quick loads; matches probe_fb_groups.py


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _known_config_slugs() -> set[str]:
    return {g["slug"].lower() for g in config.FACEBOOK_GROUPS}


def _score(name: str) -> tuple[int, str]:
    """Group name -> (relevance, region). Same shape as the WhatsApp scorer."""
    region = "IL" if HEBREW_RE.search(name or "") else "GLOBAL"
    if config.FB_NOISE_RE.search(name or ""):
        return 0, region
    hits = {m.group(0).lower() for m in config.FB_RELEVANT_RE.finditer(name or "")}
    return len(hits), region


def _add(conn: sqlite3.Connection, slug: str, found_via: str) -> bool:
    """Record a group slug. Returns True if it was new."""
    if slug.lower() in _NOT_A_SLUG or slug.isdigit() and len(slug) < 6:
        return False
    in_config = 1 if slug.lower() in _known_config_slugs() else 0
    cur = conn.execute(
        "INSERT OR IGNORE INTO facebook_groups (slug, url, status, found_via,"
        " first_seen, in_config) VALUES (?, ?, 'pending', ?, ?, ?)",
        (slug, f"https://www.facebook.com/groups/{slug}/", found_via, _now(), in_config),
    )
    conn.commit()
    return cur.rowcount > 0


def rescore(conn: sqlite3.Connection) -> None:
    """Re-apply keyword scoring to known groups. Free, so it runs every time -
    keeps the table honest when the regexes are tuned."""
    for row in conn.execute("SELECT slug, name FROM facebook_groups"
                            " WHERE name IS NOT NULL").fetchall():
        relevance, region = _score(row["name"])
        conn.execute("UPDATE facebook_groups SET relevance=?, region=? WHERE slug=?",
                     (relevance, region, row["slug"]))
    conn.commit()


def seed_from_config(conn: sqlite3.Connection) -> int:
    """Mirror config.FACEBOOK_GROUPS into the table so the join list shows the
    private groups already identified (13 of them) alongside newly found ones."""
    new = 0
    status_of = {True: "public", False: "private", None: "pending"}
    for g in config.FACEBOOK_GROUPS:
        slug = g["slug"]
        if _add(conn, slug, "config"):
            new += 1
        conn.execute(
            "UPDATE facebook_groups SET name=COALESCE(name, ?), region=COALESCE(region, ?),"
            " in_config=1, status=CASE WHEN status='pending' THEN ? ELSE status END"
            " WHERE slug=?",
            (g.get("name"), g.get("region"), status_of[g.get("public")], slug))
    conn.commit()
    rescore(conn)
    return new


# --- discovery surfaces ------------------------------------------------------

def mine_db(conn: sqlite3.Connection) -> int:
    """Harvest group slugs out of already-fetched posts. No network."""
    new = 0
    rows = conn.execute("SELECT raw_text, extra_urls, url FROM leads").fetchall()
    for r in rows:
        blob = f"{r['raw_text'] or ''} {r['extra_urls'] or ''} {r['url'] or ''}"
        for slug in FB_GROUP_RE.findall(blob):
            if _add(conn, slug, "leads_db"):
                new += 1
    log.info("mine_db: %d new group(s) from %d stored posts", new, len(rows))
    return new


def search_reddit(conn: sqlite3.Connection) -> int:
    """Reddit search.rss for shared FB group links. Keyless and never captchas -
    the surface that stayed reliable for WhatsApp discovery, and the reason this
    exists is that DDG now challenges both the home IP and the GitHub runner."""
    import httpx

    from fetchers import reddit_fetcher

    new = 0
    headers = {"User-Agent": config.REDDIT_USER_AGENT}
    with httpx.Client(headers=headers, timeout=20, follow_redirects=True) as client:
        for i, query in enumerate(config.FB_REDDIT_QUERIES):
            if i:
                time.sleep(_REDDIT_SLEEP)
            try:
                r = reddit_fetcher._get_with_backoff(
                    client, "https://www.reddit.com/search.rss",
                    {"q": query, "sort": "new", "t": "year"}, "fb/reddit")
                found = 0
                for slug in FB_GROUP_RE.findall(r.text):
                    if _add(conn, slug, "reddit_search"):
                        new += 1
                        found += 1
                log.info("  %-50s -> %d new", query[:50], found)
            except Exception as e:
                log.error("reddit search %r failed: %s", query, e)
    log.info("search_reddit: %d new group(s)", new)
    return new


def _ddg_results(html: str) -> list[tuple[str, str]]:
    """DDG /lite/ HTML -> [(slug, group name)]. The result title is normally
    '<Group name> | Facebook', so it gives the name without ever loading
    facebook.com - which matters, because Facebook throttles every IP we have."""
    from bs4 import BeautifulSoup

    out: list[tuple[str, str]] = []
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        m = FB_GROUP_RE.search(a["href"])
        if not m:
            continue
        title = a.get_text(" ", strip=True)
        for suffix in (" | Facebook", " - Facebook", " | פייסבוק"):
            if title.endswith(suffix):
                title = title[: -len(suffix)].strip()
        out.append((m.group(1), title if len(title) > 2 else ""))
    return out


def search_ddg(conn: sqlite3.Connection, per_run: int = 2) -> int:
    """DuckDuckGo, ROTATING a couple of queries per run.

    Measured 2026-08-08: DDG now challenges (HTTP 202) after a SINGLE query from
    this IP, and it challenged the GitHub runner too. Firing the whole query list
    in one run therefore harvests one query's worth of results and wastes the
    rest. So the list is consumed a couple of queries at a time across runs, with
    a cursor in kv - the same rotation trick the group scraper uses. Slow, but it
    never trips the wall and the list grows every run.

    Uses the /lite/ endpoint via POST: measured to still return organic results
    when /html/ was already returning 202.
    """
    import httpx

    queries = config.FB_DDG_QUERIES
    if not queries:
        return 0
    cursor = int(db.kv_get(conn, "fb_ddg_cursor", "0") or "0") % len(queries)
    batch = [queries[(cursor + i) % len(queries)] for i in range(min(per_run, len(queries)))]
    db.kv_set(conn, "fb_ddg_cursor", str((cursor + len(batch)) % len(queries)))

    new = 0
    headers = {"User-Agent": config.USER_AGENT,
               "Accept": "text/html",
               "Accept-Language": "en-US,en;q=0.9,he;q=0.8"}
    with httpx.Client(headers=headers, timeout=20, follow_redirects=True) as client:
        for i, query in enumerate(batch):
            if i:
                time.sleep(_DDG_SLEEP)
            try:
                r = client.post("https://lite.duckduckgo.com/lite/", data={"q": query})
                if r.status_code != 200 or "anomaly" in r.text.lower():
                    log.warning("DDG challenge (HTTP %s) after %d quer(y/ies) - "
                                "stopping; the cursor resumes here next run",
                                r.status_code, i)
                    return new
                found = 0
                # Take the NAME from the result title too. Facebook throttles
                # both the home IP and GitHub runners, so probing is scarce -
                # but a search title gives the group's name for free, which is
                # all the relevance scorer needs to rank it.
                for slug, title in _ddg_results(r.text):
                    if _add(conn, slug, "ddg"):
                        new += 1
                        found += 1
                    if title:
                        relevance, region = _score(title)
                        conn.execute(
                            "UPDATE facebook_groups SET name=COALESCE(name, ?),"
                            " relevance=?, region=COALESCE(region, ?) WHERE slug=?",
                            (title, relevance, region, slug))
                conn.commit()
                log.info("  %-52s -> %d new", query[:52], found)
            except Exception as e:
                log.error("ddg %r failed: %s", query, e)
                return new
    log.info("search_ddg: %d new group(s) (cursor %d/%d)", new, cursor, len(queries))
    return new


# --- probing (CLOUD ONLY) ----------------------------------------------------

_PRIV = re.compile(r"(this group is private|private group|join this group to see|"
                   r"קבוצה פרטית|הצטרפ)", re.I)

# "2h", "15 m", "3 d", "Yesterday", "לפני שעה" - Facebook uses relative stamps on
# RECENT posts and an explicit date on old ones, so counting these is a cheap
# liveness proxy. The user asked for groups with actual traffic, not just groups
# that exist.
_RECENT_RE = re.compile(r"(\d{1,2}\s?[hmd]|yesterday|hours? ago|minutes? ago"
                        r"|לפני|אתמול)", re.I)
_MEMBERS_RE = re.compile(r"([\d.,]+[KMk]?)\s*(?:members|חברים)", re.I)


def probe_pending(conn: sqlite3.Connection, cap: int = 12) -> list[sqlite3.Row]:
    """Classify pending groups public/private/gone, logged-out, via Playwright.

    RUN THIS IN THE CLOUD. On the user's own IP a Facebook throttle surfaces as a
    login/checkpoint wall on their personal account.
    """
    from playwright.sync_api import sync_playwright

    # 'gone' is included on purpose: it is not a trustworthy verdict (a throttled
    # IP produces it too), so those rows get another chance on a later run with a
    # presumably un-throttled IP. 'public'/'private' are settled and skipped.
    rows = conn.execute(
        "SELECT * FROM facebook_groups WHERE status IN ('pending','unknown','gone')"
        " ORDER BY relevance DESC, first_seen LIMIT ?", (cap,)).fetchall()
    if not rows:
        log.info("probe: nothing pending")
        return []

    log.info("probe: %d group(s), %ds apart", len(rows), _PROBE_SLEEP)
    out = []
    # A throttled IP and a dead slug produce the IDENTICAL signature (bare
    # "Facebook" title, no articles), so a run of them means the IP is walled,
    # not that 20 groups vanished. Measured 2026-08-08: a cap of 40 on a GitHub
    # runner returned 40/40 "gone", including groups already verified real -
    # all of it garbage that overwrote good rows. Bail out and leave the rest
    # pending, mirroring facebook_public_fetcher's early abort on a login wall.
    consecutive_gone = 0
    _GONE_LIMIT = 3
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        ctx = b.new_context(user_agent=config.USER_AGENT, locale="en-US",
                            viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        for i, row in enumerate(rows):
            if i:
                page.wait_for_timeout(_PROBE_SLEEP * 1000)
            slug, status, name = row["slug"], "unknown", row["name"]
            notes = ""
            try:
                page.goto(row["url"], wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(3500)
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
                page.wait_for_timeout(1200)
                page.mouse.wheel(0, 1400)
                page.wait_for_timeout(2500)
                title = (page.title() or "").strip()
                arts = len(page.query_selector_all("div[role='article']"))
                body = page.inner_text("body")
                if title and title != "Facebook":
                    name = title.split(" | ")[0].strip()
                if title == "Facebook" and arts == 0:
                    status = "gone"          # wrong slug, or this IP is throttled
                elif arts >= 2 and not _PRIV.search(body):
                    status = "public"
                else:
                    status = "private"
                # A public group with no recent posts is worth nothing to scrape,
                # so record how alive it looks: rendered posts, plus whether any
                # carry a recent-relative timestamp ("2h", "3 d", "Yesterday").
                # Facebook shows an explicit date only on older posts.
                members = _MEMBERS_RE.search(body)
                activity = len(_RECENT_RE.findall(body))
                notes = f"posts={arts} recent={activity}"
                if members:
                    notes += f" members={members.group(1)}"
            except Exception as e:
                log.error("probe %s failed: %s", slug, str(e)[:60])
            if status == "gone":
                consecutive_gone += 1
                if consecutive_gone >= _GONE_LIMIT:
                    log.warning("%d consecutive 'gone' results - this IP is being "
                                "throttled by Facebook, not %d dead groups. Aborting; "
                                "the rest stay pending for the next run.",
                                consecutive_gone, consecutive_gone)
                    break
            else:
                consecutive_gone = 0
            relevance, region = _score(name or "")
            conn.execute(
                "UPDATE facebook_groups SET status=?, name=?, relevance=?, region=?,"
                " last_checked=?, activity=? WHERE slug=?",
                (status, name, relevance, region, _now(), notes, slug))
            conn.commit()
            log.info("  %-8s rel=%d %-26s %-34s %s", status, relevance, slug[:26],
                     (name or "")[:34], notes)
            out.append(conn.execute("SELECT * FROM facebook_groups WHERE slug=?",
                                    (slug,)).fetchone())
        b.close()
    return out


# --- output ------------------------------------------------------------------

def _rows(conn: sqlite3.Connection, status: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM facebook_groups WHERE status=? ORDER BY relevance DESC,"
        " region, name", (status,)).fetchall()


def print_table(conn: sqlite3.Connection) -> None:
    counts = dict(conn.execute(
        "SELECT status, COUNT(*) FROM facebook_groups GROUP BY status").fetchall())
    print(f"\nFacebook groups discovered: {counts}")
    for status in ("public", "private", "pending"):
        rows = _rows(conn, status)
        if not rows:
            continue
        print(f"\n=== {status.upper()} ({len(rows)}) ===")
        print(f"{'rel':>3}  {'region':<7} {'cfg':<4} {'name':<40} slug")
        for r in rows[:40]:
            print(f"{r['relevance']:>3}  {r['region'] or '':<7} "
                  f"{'yes' if r['in_config'] else '':<4} "
                  f"{(r['name'] or '')[:40]:<40} {r['slug']}")


def write_md(conn: sqlite3.Connection, path: str = "facebook_groups.md") -> str:
    """The user-facing deliverable: which groups to JOIN, ranked."""
    private = [r for r in _rows(conn, "private") if not r["joined"]]
    public = _rows(conn, "public")
    pending = _rows(conn, "pending")
    lines = [
        "# Facebook groups",
        "",
        f"*Generated {_now()} by `discover_fb_groups.py`.*",
        "",
        "## Join these by hand (private groups)",
        "",
        "The agent never sends join requests — automating your Facebook account is",
        "the one thing that can get it banned. After joining, open the group and set",
        "**🔔 → All posts**; Facebook then emails every new post and the agent ingests",
        "it over IMAP. This is the ban-proof channel and it scales to unlimited groups.",
        "",
        "| rel | region | group | link |",
        "|----:|:-------|:------|:-----|",
    ]
    for r in private:
        name = (r["name"] or r["slug"]).replace("|", "\\|")
        lines += [f"| {r['relevance']} | {r['region'] or ''} | {name} | {r['url']} |"]
    lines += [
        "",
        f"## Scraped automatically (public, {len(public)})",
        "",
        "No action needed — the logged-out scraper reads these on GitHub's IPs.",
        "",
        "| rel | region | group | in config |",
        "|----:|:-------|:------|:----------|",
    ]
    for r in public:
        name = (r["name"] or r["slug"]).replace("|", "\\|")
        lines += [f"| {r['relevance']} | {r['region'] or ''} | {name} | "
                  f"{'yes' if r['in_config'] else '**add**'} |"]
    if pending:
        lines += ["", f"## Not yet probed ({len(pending)})", "",
                  "Run `discover_fb_groups.py --probe` **in the cloud** to classify these.", ""]
        for r in pending:
            lines += [f"- `{r['slug']}` (found via {r['found_via']})"]
    lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    log.info("wrote %s (%d private to join, %d public)", path, len(private), len(public))
    return path


def config_lines(conn: sqlite3.Connection) -> None:
    """Paste-ready config.FACEBOOK_GROUPS entries for public groups not in it yet."""
    rows = [r for r in _rows(conn, "public") if not r["in_config"]]
    if not rows:
        print("\n# No new public groups to add to config.FACEBOOK_GROUPS.")
        return
    print("\n# Add to config.FACEBOOK_GROUPS:")
    for r in rows:
        name = (r["name"] or r["slug"]).replace('"', "'")
        print(f'    {{"slug": "{r["slug"]}", "name": "{name}", '
              f'"public": True, "region": "{r["region"] or "GLOBAL"}"}},')


def notify_new(conn: sqlite3.Connection) -> bool:
    """Telegram-ping newly classified relevant groups. Per-row `notified` flag,
    same reasoning as the WhatsApp version: a group found today may be probed
    days later, so a global cursor would silently skip it."""
    rows = conn.execute(
        "SELECT * FROM facebook_groups WHERE status IN ('public','private')"
        " AND relevance >= 2 AND COALESCE(notified,0)=0 AND COALESCE(in_config,0)=0"
        " ORDER BY relevance DESC").fetchall()
    if not rows:
        return False
    priv = [r for r in rows if r["status"] == "private"]
    pub = [r for r in rows if r["status"] == "public"]
    lines = [f"\U0001F465 <b>{len(rows)} new Facebook group(s) found</b>", ""]
    if priv:
        lines += [f"<b>Join by hand ({len(priv)})</b> - then \U0001F514 All posts:"]
        for r in priv[:12]:
            lines.append(f"[{r['relevance']}] {r['region']} - {r['name'] or r['slug']}\n{r['url']}")
        lines.append("")
    if pub:
        lines += [f"<b>Public ({len(pub)})</b> - scraper will cover these:"]
        for r in pub[:12]:
            lines.append(f"[{r['relevance']}] {r['region']} - {r['name'] or r['slug']}")
    sent = notifier._send_raw("\n".join(lines))
    conn.executemany("UPDATE facebook_groups SET notified=1 WHERE slug=?",
                     [(r["slug"],) for r in rows])
    conn.commit()
    return sent


def main() -> None:
    ap = argparse.ArgumentParser(description="Discover Facebook groups (free, logged-out)")
    ap.add_argument("--search", action="store_true", help="run the DuckDuckGo surface")
    ap.add_argument("--probe", action="store_true",
                    help="CLOUD ONLY: classify pending groups public/private")
    ap.add_argument("--cap", type=int, default=12, help="max groups probed this run")
    ap.add_argument("--write", action="store_true", help="write facebook_groups.md")
    ap.add_argument("--notify", action="store_true", help="Telegram-ping new groups")
    ap.add_argument("--config-lines", action="store_true",
                    help="print paste-ready config entries for new public groups")
    ap.add_argument("--joined", metavar="SLUG", help="mark a private group as joined")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s")
    conn = db.connect()

    if args.joined:
        cur = conn.execute("UPDATE facebook_groups SET joined=1 WHERE slug=?", (args.joined,))
        conn.commit()
        print("marked joined" if cur.rowcount else "no such slug")
        return

    seed_from_config(conn)
    mine_db(conn)
    if args.search:
        search_reddit(conn)
        search_ddg(conn)
    if args.probe:
        probe_pending(conn, cap=args.cap)
    rescore(conn)
    if args.notify:
        notify_new(conn)
    if args.write:
        print(f"\nwrote {write_md(conn)}")
    if args.config_lines:
        config_lines(conn)
    print_table(conn)


if __name__ == "__main__":
    main()
