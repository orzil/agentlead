"""Facebook PUBLIC groups fetcher - headless, logged-out, conservative.

Risk model (see README): this never logs in, so your Facebook ACCOUNT is never
at stake. The only thing Meta can do is temporarily block the IP, which just
means a login wall appears and this fetcher backs off (the email channel keeps
covering the same groups). To stay well under reported thresholds we:
  - cap runs to FB_MAX_RUNS_PER_DAY (default 3),
  - visit groups sequentially with a human-ish delay between them,
  - stop the whole run early if we hit a login wall (IP getting rate-limited),
  - only touch groups explicitly marked public in config.

Requires Playwright:  pip install playwright  &&  playwright install chromium
Disabled by default; enable with FB_PUBLIC_ENABLED=1 in .env.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

import config
import db
from models import Lead

log = logging.getLogger("facebook")

_LOGIN_WALL = re.compile(
    r"(log in to continue|you must log in|join this group to see|this group is private"
    r"|קבוצה פרטית|התחבר(?:י)? כדי|הצטרפ(?:י|ו)? לקבוצה כדי)",
    re.I,
)
_BOILERPLATE = re.compile(
    r"^(like|comment|share|see more|see less|עוד|הצג פחות|אהבתי|תגובה|שיתוף|reply|הגב)$", re.I)

# Everything from the first of these markers onward is comments / reactions /
# engagement chrome, not the post body - we cut it off.
_COMMENT_BOUNDARY = re.compile(
    r"(all reactions|view\s+\d+\s+(repl|comment)|view\s+more\s+(comments|answers|repl)"
    r"|view\s+all\s+\d+|write\s+a\s+comment|כל התגובות|הצג(?:\s+עוד)?\s+תגובות"
    r"|כתוב תגובה|צפייה ב)",
    re.I,
)
# Trailing "… See more" (click didn't land) or "See less" (click landed).
_SEEMORE_TAIL = re.compile(r"([….]{1,3}\s*(see more|עוד)|\s*see less|\s*הצג פחות)\s*$", re.I)

# Facebook shows an explicit year ("March 20, 2024") only on OLD posts; fresh
# ones show "2h" / "June 18". A dated year near the top of a post = stale lead.
_STALE_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October"
    r"|November|December)\s+\d{1,2},\s+20\d{2}")


def _is_stale(text: str) -> bool:
    head = "\n".join(text.splitlines()[:4])  # date line sits in the post header
    return bool(_STALE_RE.search(head))


def _clean_post_text(raw: str) -> str:
    # 1) drop everything from the first comment/reaction marker
    m = _COMMENT_BOUNDARY.search(raw)
    if m:
        raw = raw[:m.start()]
    # 2) line-level cleanup
    lines = []
    for ln in raw.splitlines():
        ln = ln.strip()
        if not ln or _BOILERPLATE.match(ln) or re.fullmatch(r"[0-9:]+ / [0-9:]+", ln):
            continue
        ln = _SEEMORE_TAIL.sub("", ln).strip()  # strip inline "… See more"
        if ln:
            lines.append(ln)
    return "\n".join(lines).strip()


# Clicks every "See more" / "עוד" toggle inside post articles, in-page via JS.
# Doing it in the page (rather than Playwright .click(), which enforces
# actionability and was silently timing out on FB's overlapping layers) reliably
# fires FB's expand handler. Returns how many it clicked so we can loop until dry.
_EXPAND_JS = """
() => {
  const posts = document.querySelectorAll("div[role='article']");
  let clicked = 0;
  for (const p of posts) {
    const nodes = p.querySelectorAll("div[role='button'], span[role='button'], span, a");
    for (const n of nodes) {
      const t = (n.textContent || "").trim();
      if (t === "See more" || t === "עוד" || t === "See More") {
        try { n.click(); clicked++; } catch (e) {}
      }
    }
  }
  return clicked;
}
"""


def _expand_see_more(page) -> None:
    """Expand all truncated post bodies. A pass can reveal new "See more"
    toggles (nested/newly rendered), so loop until nothing else clicks."""
    for _ in range(6):
        try:
            clicked = page.evaluate(_EXPAND_JS)
        except Exception:
            break
        page.wait_for_timeout(600)
        if not clicked:
            break


def _extract_permalink(article) -> str | None:
    for a in article.query_selector_all("a[href*='/posts/'], a[href*='permalink'], "
                                        "a[href*='/groups/'][href*='/permalink/']"):
        href = a.get_attribute("href") or ""
        if "/posts/" in href or "permalink" in href:
            href = href.split("?")[0]
            if href.startswith("/"):
                href = "https://www.facebook.com" + href
            return href
    return None


def _scrape_group(page, group: dict, per_group: int) -> list[Lead]:
    slug = group["slug"]
    url = f"https://www.facebook.com/groups/{slug}/"
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(4000)
    try:
        page.keyboard.press("Escape")  # dismiss login modal
    except Exception:
        pass
    page.wait_for_timeout(1500)

    body = page.inner_text("body")
    n_articles = len(page.query_selector_all("div[role='article']"))
    title = (page.title() or "").strip()
    # Two block signatures: an explicit login-wall string, or the generic bare
    # "Facebook" shell (title is just "Facebook", no group name, no posts) that
    # Meta serves once an IP is temporarily rate-limited.
    if (_LOGIN_WALL.search(body) or title == "Facebook") and n_articles < 2:
        log.warning("facebook: wall/rate-limit on %s (title=%r) - backing off", slug, title)
        raise _LoginWall()

    # scroll to render a few posts
    for _ in range(3):
        page.mouse.wheel(0, 1400)
        page.wait_for_timeout(1600)

    _expand_see_more(page)

    label = group.get("name", slug)
    leads: list[Lead] = []
    seen: set[str] = set()
    for art in page.query_selector_all("div[role='article']"):
        try:
            text = _clean_post_text(art.inner_text())
        except Exception:
            continue
        if len(text) < 80:
            continue
        if _is_stale(text):
            continue  # years-old pinned/popular post, not a live lead
        key = text[:70]
        if key in seen:
            continue
        seen.add(key)
        permalink = _extract_permalink(art) or f"{url}#post{len(leads)+1}"
        leads.append(Lead(source=f"facebook/{label}", url=permalink, raw_text=text[:4000]))
        if len(leads) >= per_group:
            break
    log.info("facebook: %s -> %d posts", label, len(leads))
    return leads


class _LoginWall(Exception):
    pass


def _group_pool(conn) -> list[dict]:
    """Curated config groups PLUS the ones discovery promoted.

    Until 2026-08-08 this read config.FACEBOOK_GROUPS alone, which made
    discovery decorative: discover_fb_groups.py could find and verify a group
    and nothing would ever scrape it. Promoted rows (public, cleared the quality
    bar) are appended AFTER the config groups, deliberately - the existing
    rotation order is Or's and stays untouched.
    """
    pool = [g for g in config.FACEBOOK_GROUPS if g.get("public")]
    known = {g["slug"].lower() for g in pool}
    try:
        rows = conn.execute(
            "SELECT slug, name, region FROM facebook_groups "
            "WHERE status='public' AND COALESCE(in_rotation,0)=1 "
            "ORDER BY relevance DESC, slug").fetchall()
    except Exception as e:      # table missing on a very old DB - not fatal
        log.debug("facebook: no discovered-group table (%s)", e)
        return pool
    added = 0
    for r in rows:
        if r["slug"].lower() in known:
            continue
        pool.append({"slug": r["slug"], "name": r["name"] or r["slug"],
                     "public": True, "region": r["region"] or "GLOBAL",
                     "discovered": True})
        added += 1
    if added:
        log.info("facebook: pool = %d config + %d discovered", len(pool) - added, added)
    return pool


def fetch(conn) -> list[Lead]:
    if config.env("FB_PUBLIC_ENABLED", "0") not in ("1", "true", "yes"):
        log.debug("facebook_public disabled (set FB_PUBLIC_ENABLED=1 to enable)")
        return []

    groups = _group_pool(conn)
    if not groups:
        return []

    # --- region filter (FB_REGIONS="IL,US,EU"; EU also matches UK). Empty => all ---
    regions = [r.strip().upper() for r in config.env("FB_REGIONS", "").split(",") if r.strip()]
    if regions:
        wanted: set[str] = set()
        for r in regions:
            wanted |= {"EU", "UK"} if r == "EU" else {r}
        groups = [g for g in groups if (g.get("region") or "").upper() in wanted]
        if not groups:
            log.info("facebook: no public groups match regions %s", regions)
            return []

    # --- daily run cap (skip in cloud/rotation mode via FB_IGNORE_DAILY_CAP=1) ---
    ignore_cap = config.env("FB_IGNORE_DAILY_CAP", "0") in ("1", "true", "yes")
    today = datetime.now().strftime("%Y-%m-%d")
    cap_key = "fb_runs_today"
    runs_today = 0
    if not ignore_cap:
        stored = db.kv_get(conn, cap_key, "")
        if stored.startswith(today + ":"):
            runs_today = int(stored.split(":")[1])
        if runs_today >= int(config.env("FB_MAX_RUNS_PER_DAY", "3")):
            log.info("facebook: daily run cap reached (%d), skipping", runs_today)
            return []

    # --- rotation: scrape a rolling slice of FB_GROUPS_PER_RUN groups each run so
    # many groups get covered across runs without hammering one IP. Unset => all. ---
    pool = groups
    per_run = int(config.env("FB_GROUPS_PER_RUN", "0") or "0")
    if 0 < per_run < len(pool):
        cursor = int(db.kv_get(conn, "fb_group_cursor", "0") or "0") % len(pool)
        rotated = pool[cursor:] + pool[:cursor]   # wrap-around
        groups = rotated[:per_run]
        db.kv_set(conn, "fb_group_cursor", str((cursor + per_run) % len(pool)))
        log.info("facebook: rotation cursor %d -> scraping %d of %d groups in pool",
                 cursor, len(groups), len(pool))

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.warning("facebook: playwright not installed; skipping "
                    "(pip install playwright && playwright install chromium)")
        return []

    per_group = int(config.env("FB_POSTS_PER_GROUP", "12"))
    gap_ms = int(config.env("FB_GROUP_GAP_SECONDS", "20")) * 1000  # gentle default
    all_leads: list[Lead] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=config.USER_AGENT, locale="en-US",
                                  viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        try:
            for i, group in enumerate(groups):
                try:
                    all_leads.extend(_scrape_group(page, group, per_group))
                except _LoginWall:
                    break  # IP getting rate-limited: stop the whole run
                except Exception as e:
                    log.error("facebook: %s failed: %s", group.get("slug"), e)
                if i < len(groups) - 1:
                    page.wait_for_timeout(gap_ms)
        finally:
            browser.close()

    if not ignore_cap:
        db.kv_set(conn, cap_key, f"{today}:{runs_today + 1}")
    log.info("facebook: %d leads from %d public groups (pool=%d, regions=%s)",
             len(all_leads), len(groups), len(pool), regions or "all")
    return all_leads
