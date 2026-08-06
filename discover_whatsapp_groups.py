"""Find WhatsApp groups worth JOINING - a discovery tool, not a fetcher.

WhatsApp has no logged-out read surface: you cannot see a group's messages
without joining, and joining/reading via WhatsApp Web automation risks a ban on
the user's personal number. So this script deliberately stops at discovery -
same rule as Facebook, where the account is never automated. It produces a
ranked list of invite links; the user joins the good ones by hand.

NON-GOAL (do not add): reading messages out of joined groups. If those groups
turn out to carry leads, the safe path is the one already used for private
Facebook groups - forward/notify by email and let email_fetcher ingest them.

Three free discovery surfaces, cheapest first:
  1. mine_db      - invite links already sitting in fetched posts (Telegram and
                    Facebook posts share them constantly). Zero network, and on
                    the first run it already found an Israeli dev-jobs group.
  2. search_reddit- Reddit's search.rss for "chat.whatsapp.com" + keywords.
                    Keyless and reliable; the primary network surface.
  3. search_ddg    - DuckDuckGo HTML. Frequently captcha-walls datacenter IPs
                    (it does on this machine), so it detects the challenge and
                    skips instead of failing the run. May work from a home IP.

Validation is logged-out: GET chat.whatsapp.com/<code> and read og:title.
A live invite returns the group name; a revoked/invalid one returns HTTP 200
with an EMPTY og:title (verified against live and dead codes).

Usage:
  python -X utf8 discover_whatsapp_groups.py                # mine + validate + table
  python -X utf8 discover_whatsapp_groups.py --search       # + reddit/ddg search
  python -X utf8 discover_whatsapp_groups.py --write        # + whatsapp_groups.md
  python -X utf8 discover_whatsapp_groups.py --recheck      # re-probe stale live rows
  python -X utf8 discover_whatsapp_groups.py --joined <code>
"""
from __future__ import annotations

import argparse
import logging
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import config
import db
import notifier

log = logging.getLogger("whatsapp")

WA_INVITE_RE = re.compile(r"chat\.whatsapp\.com/(?:invite/)?([A-Za-z0-9]{16,32})")
HEBREW_RE = re.compile("[֐-׿]")   # any Hebrew char => Israeli group

# Relevance = number of distinct hits in the GROUP NAME. Bilingual on purpose:
# the Israeli groups name themselves in Hebrew ("משרות פיתוח" = dev jobs).
WA_RELEVANT_RE = re.compile(
    r"(freelanc|פרילנס|הייטק|high[\s-]?tech|\bAI\b|בינה מלאכותית|machine learning"
    r"|למידת מכונה|deep learning|computer vision|\bdata\b|דאטה|\bML\b|\bdev\b"
    r"|developer|פיתוח|מתכנתים|jobs|משרות|עבודה|\bgig\b|startup|סטארטאפ|python"
    r"|תכנות|אלגוריתמ|algorithm)", re.IGNORECASE)

# Student cohorts, course batches and internship mills match the domain words
# ("...M.Tech Data Science 2026") but never carry client work. Measured: they
# dominated the Reddit-search surface on the first real run, and three of them
# scored high enough to be pinged. Forced to relevance 0 - still listed in the
# md file, never notified, never ranked above a real group.
WA_NOISE_RE = re.compile(
    r"(internship|training\s+program|freshers?|batch\s*\d|cohort|semester|admission"
    r"|m\.?tech|b\.?tech|imba|\bmba\b|\bmsc\b|\bbsc\b|placement|college"
    r"|university|alumni|helpdesk|fall\s*\d{2}|ws\s*\d{2}/\d{2}|20\d\d[-/]20\d\d"
    # events/meetups/courses are noise here for the same reason NOISE_RE kills
    # them in the lead gate: they are not client work
    r"|meetup|\bevents?\b|webinar|\bcourse\b|bootcamp)",
    re.IGNORECASE)

_VALIDATE_SLEEP = 6
_REDDIT_SLEEP = 8
_DDG_SLEEP = 10
_RECHECK_DAYS = 30


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _add(conn: sqlite3.Connection, code: str, found_via: str) -> bool:
    """Record an invite code. Returns True if it was new."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO whatsapp_groups (code, url, status, found_via, first_seen)"
        " VALUES (?, ?, 'pending', ?, ?)",
        (code, f"https://chat.whatsapp.com/{code}", found_via, _now()),
    )
    conn.commit()
    return cur.rowcount > 0


def _score(name: str) -> tuple[int, str]:
    """Group name -> (relevance, region)."""
    region = "IL" if HEBREW_RE.search(name or "") else "GLOBAL"
    if WA_NOISE_RE.search(name or ""):
        return 0, region
    hits = {m.group(0).lower() for m in WA_RELEVANT_RE.finditer(name or "")}
    return len(hits), region


def rescore(conn: sqlite3.Connection) -> None:
    """Re-apply the keyword scoring to known groups. Free (no network), so it
    runs every time - keeps the table honest when the regexes are tuned."""
    for row in conn.execute("SELECT code, name FROM whatsapp_groups"
                            " WHERE name IS NOT NULL").fetchall():
        relevance, region = _score(row["name"])
        conn.execute("UPDATE whatsapp_groups SET relevance=?, region=? WHERE code=?",
                     (relevance, region, row["code"]))
    conn.commit()


# --- discovery surfaces ------------------------------------------------------

def mine_db(conn: sqlite3.Connection) -> int:
    """Harvest invite links out of already-fetched posts. No network."""
    new = 0
    rows = conn.execute("SELECT raw_text, extra_urls FROM leads").fetchall()
    for r in rows:
        blob = f"{r['raw_text'] or ''} {r['extra_urls'] or ''}"
        for code in WA_INVITE_RE.findall(blob):
            if _add(conn, code, "leads_db"):
                new += 1
    log.info("mine_db: %d new invite(s) from %d stored posts", new, len(rows))
    return new


def search_reddit(conn: sqlite3.Connection) -> int:
    """Reddit search.rss for shared invite links. Keyless; the reliable surface."""
    import httpx

    from fetchers import reddit_fetcher

    new = 0
    headers = {"User-Agent": config.REDDIT_USER_AGENT}
    with httpx.Client(headers=headers, timeout=20, follow_redirects=True) as client:
        for i, query in enumerate(config.WHATSAPP_REDDIT_QUERIES):
            if i:
                time.sleep(_REDDIT_SLEEP)
            try:
                r = reddit_fetcher._get_with_backoff(
                    client, "https://www.reddit.com/search.rss",
                    {"q": query, "sort": "new", "t": "year"}, "wa/reddit")
                for code in WA_INVITE_RE.findall(r.text):
                    if _add(conn, code, "reddit_search"):
                        new += 1
            except Exception as e:
                log.error("reddit search %r failed: %s", query, e)
    log.info("search_reddit: %d new invite(s)", new)
    return new


def search_ddg(conn: sqlite3.Connection) -> int:
    """DuckDuckGo HTML. Captcha-walls datacenter IPs - detect and skip, never fail."""
    import httpx

    new = 0
    headers = {"User-Agent": config.USER_AGENT}
    with httpx.Client(headers=headers, timeout=20, follow_redirects=True) as client:
        for i, query in enumerate(config.WHATSAPP_DDG_QUERIES):
            if i:
                time.sleep(_DDG_SLEEP)
            try:
                r = client.get("https://html.duckduckgo.com/html/", params={"q": query})
                if r.status_code != 200 or "anomaly" in r.text.lower():
                    log.warning("DDG challenge (HTTP %s) - skipping the DDG surface",
                                r.status_code)
                    return new
                hits = WA_INVITE_RE.findall(r.text)
                if not hits and "result__a" not in r.text:
                    log.warning("DDG returned no organic results - skipping")
                    return new
                for code in hits:
                    if _add(conn, code, "ddg"):
                        new += 1
            except Exception as e:
                log.error("ddg %r failed: %s", query, e)
                return new
    log.info("search_ddg: %d new invite(s)", new)
    return new


# --- validation --------------------------------------------------------------

def validate_pending(conn: sqlite3.Connection, cap: int = 25,
                     recheck: bool = False) -> list[sqlite3.Row]:
    """Probe invites logged-out: og:title present => live (and gives the name)."""
    import httpx
    from bs4 import BeautifulSoup

    rows = conn.execute(
        "SELECT * FROM whatsapp_groups WHERE status IN ('pending', 'unknown')"
        " ORDER BY first_seen LIMIT ?", (cap,)).fetchall()
    if recheck:
        stale = (datetime.now(timezone.utc) - timedelta(days=_RECHECK_DAYS)).isoformat()
        rows = list(rows) + conn.execute(
            "SELECT * FROM whatsapp_groups WHERE status = 'live'"
            " AND (last_checked IS NULL OR last_checked < ?) LIMIT ?",
            (stale, cap)).fetchall()
    if not rows:
        return []

    headers = {"User-Agent": config.USER_AGENT}
    out = []
    with httpx.Client(headers=headers, timeout=20, follow_redirects=True) as client:
        for i, row in enumerate(rows):
            if i:
                time.sleep(_VALIDATE_SLEEP)
            try:
                r = client.get(row["url"])
                if r.status_code != 200:
                    conn.execute("UPDATE whatsapp_groups SET status='unknown', last_checked=?"
                                 " WHERE code=?", (_now(), row["code"]))
                    continue
                soup = BeautifulSoup(r.text, "html.parser")
                og = soup.find("meta", property="og:title")
                name = ((og.get("content") if og else "") or "").strip()
                if not name:
                    conn.execute("UPDATE whatsapp_groups SET status='revoked', last_checked=?"
                                 " WHERE code=?", (_now(), row["code"]))
                    continue
                relevance, region = _score(name)
                conn.execute(
                    "UPDATE whatsapp_groups SET status='live', name=?, relevance=?,"
                    " region=?, last_checked=? WHERE code=?",
                    (name, relevance, region, _now(), row["code"]))
                out.append(conn.execute("SELECT * FROM whatsapp_groups WHERE code=?",
                                        (row["code"],)).fetchone())
            except Exception as e:
                log.error("validate %s failed: %s", row["code"], e)
                conn.execute("UPDATE whatsapp_groups SET status='unknown', last_checked=?"
                             " WHERE code=?", (_now(), row["code"]))
            finally:
                conn.commit()
    log.info("validate: probed %d, %d live", len(rows), len(out))
    return out


# --- output ------------------------------------------------------------------

def _live(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM whatsapp_groups WHERE status='live'"
        " ORDER BY relevance DESC, region, name").fetchall()


def print_table(conn: sqlite3.Connection) -> None:
    rows = _live(conn)
    counts = dict(conn.execute(
        "SELECT status, COUNT(*) FROM whatsapp_groups GROUP BY status").fetchall())
    print(f"\nWhatsApp groups: {counts}")
    if not rows:
        print("  (no live groups yet - try --search)")
        return
    print(f"\n{'rel':>3}  {'region':<7} {'joined':<7} {'name':<44} url")
    for r in rows:
        mark = "yes" if r["joined"] else ""
        print(f"{r['relevance']:>3}  {r['region'] or '':<7} {mark:<7} "
              f"{(r['name'] or '')[:44]:<44} {r['url']}")


def write_md(conn: sqlite3.Connection, path: str = "whatsapp_groups.md") -> str:
    rows = _live(conn)
    lines = [
        "# WhatsApp groups to join",
        "",
        f"*Generated {_now()} by `discover_whatsapp_groups.py` — "
        f"{len(rows)} live invite(s).*",
        "",
        "Join the relevant ones **by hand**. The agent never automates WhatsApp;",
        "it only finds the doors. Higher `rel` = more keyword hits in the group name.",
        "",
        "| rel | region | joined | group | invite |",
        "|----:|:-------|:------:|:------|:-------|",
    ]
    for r in rows:
        name = (r["name"] or "").replace("|", "\\|")
        lines.append(f"| {r['relevance']} | {r['region'] or ''} | "
                     f"{'x' if r['joined'] else ' '} | {name} | {r['url']} |")
    lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    log.info("wrote %s (%d groups)", path, len(rows))
    return path


def notify_new(conn: sqlite3.Connection) -> bool:
    """Telegram-ping live groups that look relevant and haven't been reported yet.

    Keyed on a per-row `notified` flag rather than a global "last notified"
    timestamp: invites over the per-run validation cap are validated on a LATER
    run, so their first_seen is older than that cursor and they would never be
    reported.
    """
    rows = conn.execute(
        "SELECT * FROM whatsapp_groups WHERE status='live' AND relevance >= 1"
        " AND COALESCE(notified, 0) = 0 ORDER BY relevance DESC").fetchall()
    if not rows:
        return False
    lines = [f"\U0001F4AC <b>{len(rows)} new WhatsApp group(s) to consider joining</b>",
             "<i>join by hand - the agent never automates WhatsApp</i>", ""]
    for r in rows[:15]:
        lines.append(f"[{r['relevance']}] {r['region']} - {r['name']}\n{r['url']}")
    sent = notifier._send_raw("\n".join(lines))
    conn.executemany("UPDATE whatsapp_groups SET notified=1 WHERE code=?",
                     [(r["code"],) for r in rows])
    conn.commit()
    return sent


def main() -> None:
    ap = argparse.ArgumentParser(description="Discover joinable WhatsApp groups (free, logged-out)")
    ap.add_argument("--search", action="store_true", help="also run the network search surfaces")
    ap.add_argument("--write", action="store_true", help="write whatsapp_groups.md")
    ap.add_argument("--notify", action="store_true", help="Telegram-ping new relevant groups")
    ap.add_argument("--recheck", action="store_true", help="re-probe live rows older than 30 days")
    ap.add_argument("--cap", type=int, default=25, help="max invites validated this run")
    ap.add_argument("--joined", metavar="CODE", help="mark a group as joined")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s")
    conn = db.connect()

    if args.joined:
        cur = conn.execute("UPDATE whatsapp_groups SET joined=1 WHERE code=?", (args.joined,))
        conn.commit()
        print("marked joined" if cur.rowcount else "no such code")
        return

    mine_db(conn)
    if args.search:
        search_reddit(conn)
        search_ddg(conn)
    validate_pending(conn, cap=args.cap, recheck=args.recheck)
    rescore(conn)
    if args.notify:
        notify_new(conn)
    if args.write:
        print(f"\nwrote {write_md(conn)}")
    print_table(conn)


if __name__ == "__main__":
    main()
