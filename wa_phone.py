"""Join and read WhatsApp groups by driving the OFFICIAL app on a dedicated phone.

WhatsApp has no read API for other people's groups, and every unofficial client
(neonize/whatsmeow, Baileys) logs in as a linked device - the same surface as
WhatsApp Web, and the one Meta bans for automation. So this does what a person
does: the Android phone with the second SIM sits on a USB cable, and `adb`
opens invite links, taps Join, opens group chats and reads the screen through
`uiautomator dump`. No linked device, no protocol client.

Rules, all load-bearing:
  * DEDICATED NUMBER ONLY. Or's own WhatsApp is never touched.
  * NEVER SENDS. No code path types text. The only taps are: the Join button,
    the close/OK buttons of WhatsApp's own sheets and banners, and chat rows
    whose title is on the allowlist.
  * ALLOWLIST. Only groups this module joined (title_on_phone in
    whatsapp_groups) are opened. Private chats and other groups on the phone
    are never read.
  * SLOW JOINS. One join per pass, daytime only, at most JOIN_DAILY_CAP a day,
    best groups first. A fresh number joining 50 groups in an hour is exactly
    what gets banned. `--join-all on` overrides this on Or's say-so (BURST_*).
  * KILL SWITCH. A ban / re-verify / logged-out screen stops every pass
    (kv `wa_phone_killed`) and alerts Telegram once. Clear it by hand:
    python -X utf8 wa_phone.py --unkill
  * NOTHING PERSONAL IN LOGS. Logs carry counts, never message text or phone
    numbers - the repo is public and agent.log is easy to paste.

Run by Windows Task Scheduler every 2h through `main.py --wa-pass` (see
wa_pass.bat). Local only: the phone is on this PC's USB port.

    python -X utf8 wa_phone.py --status     # device, joined groups, quota
    python -X utf8 wa_phone.py --pass       # one pass (join + read), no ingest
    python -X utf8 wa_phone.py --unkill     # clear the kill switch after a check
    python -X utf8 wa_phone.py --join-all on  # burst-join the rest (see BURST_*)
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
import subprocess
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import config
import db
from models import Lead

log = logging.getLogger("wa_phone")

ADB = config.env("ADB_PATH", os.path.expandvars(r"%USERPROFILE%\tools\platform-tools\adb.exe"))
PKG = "com.whatsapp"
RID = "com.whatsapp:id/"
IL = ZoneInfo("Asia/Jerusalem")

JOIN_DAILY_CAP = int(config.env("WA_JOIN_DAILY_CAP", "6"))
JOIN_HOURS = (9, 21)               # local Israel time, [start, end)
JOIN_MIN_GAP_MIN = 90              # never two joins closer than this
# JOIN-ALL burst (Or's call, 2026-10-19: "join all the groups"). Switched on by
# `--join-all` (kv wa_join_all); each pass then joins for up to an hour with
# random human-ish gaps, and wa_loop re-runs passes every few minutes until the
# list is done. Still daytime only, still stops on any ban screen, and stops
# itself after a few failed joins in a row (that pattern = WhatsApp rate limit).
BURST_KEY = "wa_join_all"
BURST_HOURS = (8, 23)
BURST_DAILY_CAP = int(config.env("WA_BURST_DAILY_CAP", "50"))
BURST_GAP_MIN = (3.0, 8.0)         # random minutes between joins
BURST_MINUTES_PER_PASS = 60        # wa_loop's pass timeout is 90
BURST_MAX_FAILS = 3
MAX_SCREENS_PER_CHAT = 25
MAX_LIST_PAGES = 12
KILL_KEY = "wa_phone_killed"

# Get-rich / MLM / crypto sheets. Seen on the first probe: "AI Freelancers" with
# "Stop wasting time alone on your monthly salary..." - joining those wastes a
# daily join slot and makes the number look like a spam account.
SCAM_RE = re.compile(
    r"(monthly\s+salary|passive\s+income|make\s+money|earn\s+\$?\d|per\s+day\s+from\s+home"
    r"|crypto|forex|trading\s+signals|binary|invest(ment)?\s+plan|airdrop|mlm|network\s+marketing"
    r"|הכנסה\s+פסיבית|להרוויח\s+מהבית|קריפטו|פורקס|השקעה\s+בטוחה|שיווק\s+רשתי)",
    re.IGNORECASE)

# Screens that mean the account is gone or must re-register. Checked against the
# focused activity name and the visible text.
BAN_ACTIVITY_RE = re.compile(r"(registration|RegisterPhone|VerifySms|VerifyPhone|"
                             r"Banned|Eula|ChangeNumber)", re.IGNORECASE)
BAN_TEXT_RE = re.compile(r"(account\s+is\s+(banned|not\s+allowed)|this\s+account\s+can\s*not"
                         r"|החשבון\s+שלך\s+(נחסם|הושעה)|אין\s+לך\s+אפשרות\s+להשתמש\s+בוואטסאפ"
                         r"|verify\s+your\s+phone\s+number|אימות\s+מספר\s+הטלפון)", re.IGNORECASE)


class PhoneError(RuntimeError):
    """The phone is not usable right now (unplugged, locked, wrong screen)."""


class Banned(PhoneError):
    """WhatsApp shows a ban / re-verification screen. Stops all passes."""


# --- adb primitives -------------------------------------------------------------

def adb(*args: str, timeout: int = 60, binary: bool = False):
    """One adb call. Subprocess with an argument list, so no shell ever rewrites
    /sdcard paths (Git Bash does)."""
    try:
        r = subprocess.run([ADB, *args], capture_output=True, timeout=timeout)
    except FileNotFoundError:
        raise PhoneError(f"adb not found at {ADB} (set ADB_PATH in .env)")
    except subprocess.TimeoutExpired:
        raise PhoneError(f"adb {' '.join(args[:2])} timed out")
    return r.stdout if binary else r.stdout.decode("utf-8", "replace")


def shell(*args: str, timeout: int = 60) -> str:
    return adb("shell", *args, timeout=timeout)


def tap(x: int, y: int) -> None:
    shell("input", "tap", str(x), str(y))


def back() -> None:
    shell("input", "keyevent", "KEYCODE_BACK")


def swipe(y_from: int, y_to: int, ms: int = 450) -> None:
    shell("input", "swipe", "540", str(y_from), "540", str(y_to), str(ms))


def dump() -> ET.Element:
    """The current screen as a uiautomator XML tree. WhatsApp's list animations
    occasionally make the dump fail with 'could not get idle state'; retry."""
    for attempt in range(4):
        if attempt == 3:
            # still failing (2026-10-19: four passes in a row): a stuck
            # uiautomator from an earlier pass, or an animated screen. Kill it
            # and relaunch WhatsApp before the last try.
            shell("pkill", "-f", "uiautomator")
            shell("input", "keyevent", "KEYCODE_HOME")
            time.sleep(1)
            shell("am", "start", "-n", f"{PKG}/.Main")
            time.sleep(3)
        out = shell("uiautomator", "dump", "/sdcard/wa.xml", timeout=40)
        if "dumped" in out:
            raw = adb("exec-out", "cat", "/sdcard/wa.xml", binary=True)
            try:
                return ET.fromstring(raw)
            except ET.ParseError:
                pass
        time.sleep(1.5 + attempt)
    # uiautomator's own error line (e.g. "could not get idle state"), no screen text
    raise PhoneError(f"uiautomator dump failed 4 times: {out.strip()[:80]}")


def rid(node: ET.Element) -> str:
    return (node.get("resource-id") or "").removeprefix(RID)


def find(root: ET.Element, name: str) -> list[ET.Element]:
    return [n for n in root.iter("node") if rid(n) == name]


def first(root: ET.Element, name: str) -> ET.Element | None:
    found = find(root, name)
    return found[0] if found else None


def center(node: ET.Element) -> tuple[int, int]:
    x1, y1, x2, y2 = map(int, re.findall(r"\d+", node.get("bounds", "[0,0][0,0]")))
    return (x1 + x2) // 2, (y1 + y2) // 2


def clean(s: str | None) -> str:
    """Strip the bidi control marks WhatsApp wraps Hebrew UI strings in."""
    return re.sub(r"[‎‏‪-‮⁦-⁩]", "", s or "").strip()


def focus() -> str:
    out = shell("dumpsys", "window")
    m = re.search(r"mCurrentFocus=Window\{\S+ \S+ ([^}]+)\}", out)
    return m.group(1) if m else ""


# --- readiness / safety -----------------------------------------------------------

def device_state() -> str:
    """'device' when attached and authorized; 'unauthorized', 'offline' or ''."""
    out = adb("devices", timeout=20)
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            return parts[1]
    return ""


def check_not_banned(root: ET.Element | None = None) -> None:
    f = focus()
    if BAN_ACTIVITY_RE.search(f):
        raise Banned(f"WhatsApp is on a registration/ban screen ({f.split('/')[-1]})")
    root = root if root is not None else dump()
    text = " ".join(clean(n.get("text")) for n in root.iter("node"))
    if BAN_TEXT_RE.search(text):
        raise Banned("WhatsApp shows a ban / verify-number message")


def wake() -> None:
    # stay awake only while a pass runs: an always-on AMOLED (Galaxy S9) burns in
    shell("settings", "put", "global", "stay_on_while_plugged_in", "3")
    shell("input", "keyevent", "KEYCODE_WAKEUP")
    shell("wm", "dismiss-keyguard")
    time.sleep(1.5)


def sleep_screen() -> None:
    try:
        shell("input", "keyevent", "KEYCODE_HOME")
        shell("settings", "put", "global", "stay_on_while_plugged_in", "0")
        shell("input", "keyevent", "KEYCODE_SLEEP")
    except PhoneError:
        pass


def ensure_ready() -> None:
    state = device_state()
    if state != "device":
        raise PhoneError(f"phone not available over USB (adb state: {state or 'none'})")
    wake()
    if "deviceLocked=1" in shell("dumpsys", "trust"):
        raise PhoneError("phone is locked - set Screen lock to None/Swipe")
    open_home()
    check_not_banned()


def open_home() -> ET.Element:
    """WhatsApp's chat list, freshly launched."""
    shell("am", "start", "-n", f"{PKG}/.Main")
    time.sleep(2.5)
    for _ in range(3):
        root = dump()
        if find(root, "conversations_row_contact_name") or first(root, "conversation_list_view_host") is not None:
            return root
        back()                    # some sub-screen was left open; step out
        time.sleep(1)
        shell("am", "start", "-n", f"{PKG}/.Main")
        time.sleep(2)
    if PKG not in focus():
        raise PhoneError(f"WhatsApp did not come to the foreground ({focus()})")
    return dump()


def scroll_list_top(root: ET.Element) -> ET.Element:
    """WhatsApp keeps the chat list's scroll position between launches, so a
    pass can start mid-list; swipe down until the top row stops changing."""
    def top(r):
        names = [n.get("text") for n in find(r, "conversations_row_contact_name")]
        return names[:2]
    prev = top(root)
    for _ in range(10):
        swipe(700, 1700, 300)
        time.sleep(0.8)
        root = dump()
        now = top(root)
        if now == prev:
            break
        prev = now
    return root


def killed(conn) -> str:
    return db.kv_get(conn, KILL_KEY, "")


# --- group targets ------------------------------------------------------------------

_MD_ROW = re.compile(r"^\| ([ABC]) \| (HE|EN) \| (.*) \| https://chat\.whatsapp\.com/([A-Za-z0-9]+) \|\s*$")
# Or's ordering (2026-10-18): freelance/AI groups and Israeli AI/dev boards first,
# general hi-tech job boards last. The md is sorted by the hunt's own rank, which
# put the general boards on top.
_P0 = re.compile(r"(freelanc|פרילנס|\bAI\b|machine\s+learning|\bML\b|data|python|remote|ראייה|בינה)",
                 re.IGNORECASE)
_P1 = re.compile(r"(פיתוח|תוכנה|מתכנת|developer|backend|frontend|full\s*stack|פולסטאק|סטארטאפ)",
                 re.IGNORECASE)


def _priority(name: str, index: int) -> int:
    """Freelance/contract groups and the groups where buyers talk first
    (Or, 2026-10-20: "part time, contract, freelance"), then AI/data, then
    general dev boards. Tier 0 wins ties by the hunt's own md order."""
    if config.WA_CV_GROUP_RE.search(name):
        return index - 1000                      # computer vision: Or's core niche, first
    if config.WA_FREELANCE_GROUP_RE.search(name) or config.WA_BUYER_GROUP_RE.search(name):
        tier = 0
    else:
        tier = 1 if _P0.search(name) else 2 if _P1.search(name) else 2
    return tier * 1000 + index


def load_targets(conn) -> int:
    """Upsert the night hunt's whatsapp_top50.md into whatsapp_groups as join
    targets. Only rows with a priority are ever joined, so the 40 old July rows
    in the table stay untouched. Returns the number of new targets."""
    path = config.BASE_DIR / "whatsapp_top50.md"
    if not path.exists():
        return 0
    now = datetime.now(timezone.utc).isoformat()
    new = 0
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        m = _MD_ROW.match(line)
        if not m:
            continue
        _tier, lang, name, code = m.groups()
        name = name.replace("\\|", "|").strip()
        cur = conn.execute(
            "INSERT OR IGNORE INTO whatsapp_groups (code, url, name, status, region, found_via, first_seen)"
            " VALUES (?, ?, ?, 'live', ?, 'top50', ?)",
            (code, f"https://chat.whatsapp.com/{code}", name, "IL" if lang == "HE" else "GLOBAL", now))
        new += cur.rowcount
        # re-rank every untried target, so a ranking change reorders the queue
        conn.execute("UPDATE whatsapp_groups SET priority=? WHERE code=? AND join_status IS NULL",
                     (_priority(name, i), code))
    # full-time-only boards and job-seeker communities are never joined; the
    # name decides, no join slot spent (reversible: clear join_status)
    for code, name in conn.execute("SELECT code, name FROM whatsapp_groups WHERE "
                                   "priority IS NOT NULL AND join_status IS NULL").fetchall():
        if name and config.WA_SKIP_GROUP_RE.search(name):
            conn.execute("UPDATE whatsapp_groups SET join_status='skipped_offtopic' WHERE code=?",
                         (code,))
    conn.commit()
    return new


def _joined_titles(conn) -> dict[str, str]:
    rows = conn.execute("SELECT code, title_on_phone FROM whatsapp_groups "
                        "WHERE join_status='joined' AND title_on_phone IS NOT NULL").fetchall()
    return {r["title_on_phone"]: r["code"] for r in rows}


def _match_title(shown: str, titles: dict[str, str]) -> str | None:
    """Chat-list titles are cut with '…'. Match by prefix against the exact
    titles recorded at join time; require a long-enough prefix to be unique."""
    shown = clean(shown)
    if shown in titles:
        return shown
    if shown.endswith("…"):
        stem = shown[:-1].rstrip()
        hits = [t for t in titles if t.startswith(stem)]
        if len(stem) >= 8 and len(hits) == 1:
            return hits[0]
    return None


# --- joining -----------------------------------------------------------------------

def _open_invite(code: str) -> ET.Element:
    shell("am", "start", "-a", "android.intent.action.VIEW",
          "-d", f"https://chat.whatsapp.com/{code}", "-p", PKG)
    time.sleep(4)
    return dump()


def _close_sheet(root: ET.Element) -> None:
    btn = first(root, "join_group_bottom_sheet_close_button")
    if btn is not None:
        tap(*center(btn))
    else:
        back()
    time.sleep(1.5)


def _join_quota_open(conn) -> tuple[bool, str]:
    burst = bool(db.kv_get(conn, BURST_KEY, ""))
    hours, cap, gap = ((BURST_HOURS, BURST_DAILY_CAP, BURST_GAP_MIN[0]) if burst
                       else (JOIN_HOURS, JOIN_DAILY_CAP, JOIN_MIN_GAP_MIN))
    now = datetime.now(IL)
    if not (hours[0] <= now.hour < hours[1]):
        return False, "night"
    today = now.date().isoformat()
    if db.kv_get(conn, "wa_join_day", "") != today:
        db.kv_set(conn, "wa_join_day", today)
        db.kv_set(conn, "wa_join_count", "0")
    if int(db.kv_get(conn, "wa_join_count", "0") or 0) >= cap:
        return False, "daily cap"
    last = float(db.kv_get(conn, "wa_join_last", "0") or 0)
    if time.time() - last < gap * 60:
        return False, "gap"
    return True, ""


def _count_join(conn) -> None:
    db.kv_set(conn, "wa_join_count", str(int(db.kv_get(conn, "wa_join_count", "0") or 0) + 1))
    db.kv_set(conn, "wa_join_last", str(time.time()))


def _set_group(conn, code: str, **cols) -> None:
    sets = "".join(f"{k}=?, " for k in cols)          # no cols = just stamp last_checked
    conn.execute(f"UPDATE whatsapp_groups SET {sets}last_checked=? WHERE code=?",
                 (*cols.values(), datetime.now(timezone.utc).isoformat(), code))
    conn.commit()


def join_next(conn) -> str:
    """Join (or request to join) the best not-yet-tried target. At most one real
    join per call; spam groups are skipped without spending the slot."""
    ok, why = _join_quota_open(conn)
    if not ok:
        return f"no join ({why})"
    for _ in range(5):                       # skip at most a few spam sheets per pass
        row = conn.execute(
            "SELECT code, name, found_via FROM whatsapp_groups WHERE priority IS NOT NULL "
            "AND joined=0 AND status='live' AND join_status IS NULL "
            "ORDER BY priority LIMIT 1").fetchone()
        if not row:
            return "no join (all targets tried)"
        code = row["code"]
        root = _open_invite(code)
        check_not_banned(root)
        title_n = first(root, "join_group_bottom_sheet_group_title")
        title = clean(title_n.get("text")) if title_n is not None else ""
        desc_n = first(root, "join_group_bottom_sheet_description_text")
        desc = clean(desc_n.get("text")) if desc_n is not None else ""

        if first(root, "join_group_bottom_sheet_view_group") is not None:
            # already a member (joined by hand, or by an earlier pass)
            _set_group(conn, code, joined=1, join_status="joined", title_on_phone=title,
                       joined_at=datetime.now(timezone.utc).isoformat())
            _close_sheet(root)
            continue
        btn = first(root, "join_group_bottom_sheet_join_button")
        if btn is None or not title:
            _set_group(conn, code, status="revoked", join_status="failed")
            _close_sheet(root)
            log.info("wa join: invite %s… is dead or unreadable", code[:4])
            continue
        if SCAM_RE.search(f"{title} {desc}"):
            _set_group(conn, code, join_status="skipped_spam")
            _close_sheet(root)
            log.info("wa join: skipped a get-rich group (priority %s)", code[:4])
            continue
        if row["found_via"] == IN_GROUP and not _on_topic(title, desc):
            # a link someone pasted in a group: unvetted, so the sheet decides
            _set_group(conn, code, join_status="skipped_offtopic", name=title)
            _close_sheet(root)
            log.info("wa join: skipped an off-topic in-group link (%s)", code[:4])
            continue

        approval = bool(first(root, "join_group_bottom_sheet_disclaimer") is not None)
        tap(*center(btn))
        _count_join(conn)
        time.sleep(6)
        after = dump()
        check_not_banned(after)
        if first(after, "join_group_bottom_sheet_view_group") is not None:
            status = "joined"
        elif approval:
            status = "requested"
        else:
            status = "failed"
        _set_group(conn, code, joined=1 if status == "joined" else 0, join_status=status,
                   title_on_phone=title, joined_at=datetime.now(timezone.utc).isoformat())
        _close_sheet(after)
        log.info("wa join: %s (%s)", status, code[:4])
        return f"join: {status}"
    return "no join (skipped several)"


IN_GROUP = "in_group"
IN_GROUP_PRIORITY = 3000          # after every night-hunt target (tiers 0-2)


def _on_topic(title: str, desc: str) -> bool:
    """Join sheet of an in-group link: jobs/dev/AI or client-side (founders,
    business owners - the people who pay) vocabulary, not a student cohort or
    course, not a foreign-language group."""
    import discover_whatsapp_groups as dwg
    import wa_night
    s = f"{title} {desc}"
    return (bool(dwg.WA_RELEVANT_RE.search(s) or config.STRONG_DOMAIN_RE.search(s)
                 or wa_night.CLIENT_SIDE_RE.search(s))
            and not dwg.WA_NOISE_RE.search(title) and not wa_night.FOREIGN_RE.search(title)
            and not config.WA_SKIP_GROUP_RE.search(title))


def harvest_invites(conn, msgs: list[dict]) -> int:
    """Members paste other groups' invite links all the time - the cheapest
    discovery surface there is. Queue them behind the night-hunt targets;
    join_next vets each one on its join sheet (_on_topic)."""
    import discover_whatsapp_groups as dwg
    now = datetime.now(timezone.utc).isoformat()
    new = 0
    for m in msgs:
        for code in set(dwg.WA_INVITE_RE.findall(m["text"])):
            cur = conn.execute(
                "INSERT OR IGNORE INTO whatsapp_groups (code, url, status, found_via, first_seen,"
                " priority) VALUES (?, ?, 'live', ?, ?, ?)",
                (code, f"https://chat.whatsapp.com/{code}", IN_GROUP, now, IN_GROUP_PRIORITY + new))
            if cur.rowcount:
                new += 1
            else:   # known from the hunt but never a target: make it one
                conn.execute("UPDATE whatsapp_groups SET priority=?, status='live' WHERE code=? "
                             "AND priority IS NULL AND status IN ('pending','live')",
                             (IN_GROUP_PRIORITY, code))
    conn.commit()
    return new


TRIED_FILE = config.BASE_DIR / "whatsapp_tried.txt"


def export_tried(conn) -> bool:
    """Write every invite code the phone has tried to whatsapp_tried.txt and
    push it (at most once a day), so the cloud night hunt (wa_night.select_top)
    stops re-listing them. Codes only: invite links are public and already sit
    in the committed whatsapp_top50.md - no names, no lead data."""
    codes = sorted(r[0] for r in conn.execute(
        "SELECT code FROM whatsapp_groups WHERE join_status IS NOT NULL"))
    body = "# invite codes the WhatsApp phone already tried (wa_phone.export_tried)\n" + \
           "".join(f"{c}\n" for c in codes)
    old = TRIED_FILE.read_text(encoding="utf-8") if TRIED_FILE.exists() else ""
    if body != old:
        TRIED_FILE.write_text(body, encoding="utf-8")
    today = datetime.now(IL).date().isoformat()
    if db.kv_get(conn, "wa_tried_pushed", "") == today:
        return False
    git = ["git", "-C", str(config.BASE_DIR)]
    if not subprocess.run([*git, "status", "--porcelain", "--", TRIED_FILE.name],
                          capture_output=True, text=True).stdout.strip():
        return False
    subprocess.run([*git, "add", "--", TRIED_FILE.name], capture_output=True)
    r = subprocess.run([*git, "commit", "-q", "-m", "whatsapp: tried codes", "--",
                        TRIED_FILE.name], capture_output=True, text=True)
    if r.returncode == 0:
        # the cloud commits every night run; rebase so `--wa-pass`'s ff-only
        # pull never meets a diverged branch
        subprocess.run([*git, "pull", "-q", "--rebase", "--autostash"],
                       capture_output=True, timeout=120)
        r = subprocess.run([*git, "push", "-q"], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        log.warning("wa tried-codes push failed (will retry next pass)")
        return False
    db.kv_set(conn, "wa_tried_pushed", today)
    return True


def _targets_left(conn) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM whatsapp_groups WHERE priority IS NOT NULL AND joined=0 "
        "AND status='live' AND join_status IS NULL").fetchone()[0]


def join_burst(conn) -> str:
    """JOIN-ALL mode: join one group after another for up to an hour, with a
    random 3-8 min gap. Ends the burst (clears the kv flag + tells Telegram)
    when the list is done or joins keep failing."""
    import random
    import notifier
    deadline = time.time() + BURST_MINUTES_PER_PASS * 60
    done: dict[str, int] = {}
    fails_in_row = 0
    why = ""
    while time.time() < deadline:
        r = join_next(conn)
        if r == "no join (skipped several)":
            continue
        if r.startswith("no join"):
            why = r
            break
        done[r] = done.get(r, 0) + 1
        fails_in_row = fails_in_row + 1 if r == "join: failed" else 0
        if fails_in_row >= BURST_MAX_FAILS:
            db.kv_set(conn, BURST_KEY, "")
            notifier._send_raw(f"⚠️ <b>WhatsApp join-all paused</b>: {fails_in_row} joins "
                               "failed in a row - maybe a WhatsApp limit. Back to slow joins "
                               "(6/day). Check the phone.")
            why = "paused after failures"
            break
        wait = random.uniform(*BURST_GAP_MIN) * 60
        if time.time() + wait > deadline:
            break
        time.sleep(wait)
    if _targets_left(conn) == 0 and db.kv_get(conn, BURST_KEY, ""):
        db.kv_set(conn, BURST_KEY, "")
        groups = dict(conn.execute(
            "SELECT COALESCE(join_status,'todo'), COUNT(*) FROM whatsapp_groups "
            "WHERE priority IS NOT NULL GROUP BY 1").fetchall())
        notifier._send_raw(f"✅ <b>WhatsApp join-all done</b>: {groups.get('joined', 0)} joined, "
                           f"{groups.get('requested', 0)} waiting for admin approval, "
                           f"{groups.get('failed', 0)} dead links, "
                           f"{groups.get('skipped_spam', 0)} skipped as spam")
    summary = ", ".join(f"{k} x{v}" for k, v in done.items()) or "nothing joined"
    return f"burst: {summary}" + (f" ({why})" if why else "")


def recheck_requested(conn, limit: int = 2) -> int:
    """Admin-approval groups: once a day, see whether the request was accepted."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    rows = conn.execute("SELECT code FROM whatsapp_groups WHERE join_status='requested' "
                        "AND (last_checked IS NULL OR last_checked < ?) LIMIT ?",
                        (cutoff, limit)).fetchall()
    accepted = 0
    for r in rows:
        root = _open_invite(r["code"])
        check_not_banned(root)
        if first(root, "join_group_bottom_sheet_view_group") is not None:
            _set_group(conn, r["code"], joined=1, join_status="joined")
            accepted += 1
        else:
            _set_group(conn, r["code"])            # just stamp last_checked
        _close_sheet(root)
    return accepted


# --- reading -------------------------------------------------------------------------

_HE_MONTHS = {m: i for i, m in enumerate(
    ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי", "אוגוסט",
     "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"], 1)}
_EN_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}
_HE_DAYS = {"שני": 0, "שלישי": 1, "רביעי": 2, "חמישי": 3, "שישי": 4, "שבת": 5, "ראשון": 6}
_EN_DAYS = {d: i for i, d in enumerate(
    ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"])}


def parse_divider(text: str, today: date) -> date | None:
    """WhatsApp's date dividers: היום / אתמול / a weekday / '12 באוקטובר 2026'
    (and the English equivalents if the phone language ever changes)."""
    t = clean(text).lower()
    if t in ("היום", "today"):
        return today
    if t in ("אתמול", "yesterday"):
        return today - timedelta(days=1)
    for names in (_HE_DAYS, _EN_DAYS):
        for name, wd in names.items():
            if t in (name, f"יום {name}"):
                delta = (today.weekday() - wd) % 7 or 7
                return today - timedelta(days=delta)
    m = re.search(r"(\d{1,2})\s+ב?(\S+?),?\s*(\d{4})?$", t)
    if m:
        month = _HE_MONTHS.get(m.group(2)) or _EN_MONTHS.get(m.group(2))
        if month:
            year = int(m.group(3)) if m.group(3) else today.year
            try:
                d = date(year, month, int(m.group(1)))
                return d if d <= today else date(year - 1, month, int(m.group(1)))
            except ValueError:
                return None
    m = re.search(r"(\d{1,2})[./](\d{1,2})[./](\d{2,4})", t)
    if m:
        y = int(m.group(3))
        try:
            return date(y + 2000 if y < 100 else y, int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


_TEXT_IDS = ("message_text", "caption")
# Ids of text-bearing nodes seen inside bubbles, saved to kv `wa_bubble_ids`
# after each pass. The sender ids below are WhatsApp's usual names but were not
# yet observed on this phone (2026-10-18: only admin-only groups to test on);
# this list is how to confirm or fix them without dumping anyone's messages.
BUBBLE_IDS_SEEN: set[str] = set()
_SENDER_IDS = ("name_in_group_tv", "name_in_group", "pushname_in_group_tv", "pushname_in_group")
# Not-yet-decrypted bubble ("Waiting for this message"): WhatsApp's text, not the sender's.
_PLACEHOLDER_RE = re.compile(r"בהמתנה להודעה זו|Waiting for this message")


def _messages_on_screen(root: ET.Element, carry_date: date | None, today: date
                        ) -> tuple[list[dict], date | None]:
    """Messages visible now, top to bottom, plus the date in force at the bottom.
    A bubble is the nearest ancestor of a text node that also holds a 'date'
    (time) node; the sender is any name_in_group* node inside it."""
    parent = {c: p for p in root.iter() for c in p}
    out: list[dict] = []
    cur_date = carry_date
    for n in root.iter("node"):
        r = rid(n)
        if r == "conversation_row_date_divider":
            cur_date = parse_divider(n.get("text") or "", today) or cur_date
            continue
        if r not in _TEXT_IDS:
            continue
        text = (n.get("text") or "").strip()
        if not text or _PLACEHOLDER_RE.search(text):
            continue
        bubble, p = None, parent.get(n)
        while p is not None:
            if any(rid(x) == "date" for x in p.iter("node")):
                bubble = p
                break
            p = parent.get(p)
        hhmm, sender, number = "", "", ""
        if bubble is not None:
            for x in bubble.iter("node"):
                xr = rid(x)
                if xr and clean(x.get("text")):
                    BUBBLE_IDS_SEEN.add(xr)
                if xr == "date":
                    hhmm = clean(x.get("text"))
                elif xr in _SENDER_IDS and clean(x.get("text")):
                    val = clean(x.get("text"))
                    if re.fullmatch(r"\+?[\d\s\-()]{8,}", val):
                        number = re.sub(r"\D", "", val)
                    elif not sender:
                        sender = val.lstrip("~ ").strip()
        out.append({"text": text, "time": hhmm, "date": cur_date,
                    "sender": sender, "number": number})
    return out, cur_date


def _posted(msg: dict, today: date) -> datetime | None:
    m = re.match(r"(\d{1,2}):(\d{2})", msg.get("time") or "")
    if not m:
        return None
    d = msg.get("date") or today
    local = datetime(d.year, d.month, d.day, int(m.group(1)), int(m.group(2)), tzinfo=IL)
    if local > datetime.now(IL) + timedelta(minutes=5):     # undated row seen after midnight
        local -= timedelta(days=1)
    return local.astimezone(timezone.utc)


def _dismiss_banners(root: ET.Element) -> bool:
    """WhatsApp's own notification-settings banner in big groups: tap its OK."""
    if first(root, "notification_activity_floating_banner_content") is not None:
        ok = first(root, "notif_action_view_2")
        if ok is not None:
            tap(*center(ok))
            time.sleep(1)
            return True
    return False


def read_chat(title: str) -> list[dict]:
    """Read from where WhatsApp opened the chat (the first unread message) down
    to the bottom. Called with the chat already open."""
    today = datetime.now(IL).date()
    root = dump()
    if _dismiss_banners(root):
        root = dump()
    # (an Element with no children is falsy - never `first(...) or default`)
    header = first(root, "conversation_contact_name")
    if header is None or clean(header.get("text"))[:6] != title[:6]:
        raise PhoneError("opened chat does not match the allowlisted title")
    seen: set[tuple] = set()
    msgs: list[dict] = []
    carry: date | None = None
    if not find(root, "conversation_row_date_divider"):
        # no date on screen: peek one screen up for the divider in force, so
        # yesterday's posts aren't stamped as today's
        swipe(600, 1500)
        time.sleep(1)
        dividers = find(dump(), "conversation_row_date_divider")
        if dividers:
            carry = parse_divider(dividers[-1].get("text") or "", today)
        swipe(1500, 600)
        time.sleep(1)
        root = dump()
    for _ in range(MAX_SCREENS_PER_CHAT):
        page, carry = _messages_on_screen(root, carry, today)
        fresh = 0
        for m in page:
            key = (m["sender"], m["time"], m["text"][:80])
            if key not in seen:
                seen.add(key)
                msgs.append(m)
                fresh += 1
        if fresh == 0 and first(root, "scroll_bottom") is None:
            break                                   # bottom reached, nothing new
        swipe(1500, 600)
        time.sleep(1.2)
        root = dump()
    return msgs


_TRUNCATED_RE = re.compile(r"(קרא עוד|Read more)\s*$")


def _count_truncated(conn, msgs: list[dict]) -> None:
    """Long posts end in WhatsApp's 'קרא עוד' span and are read cut off. The tap
    that expands them isn't built yet: no truncated message had arrived to test
    where the span sits, and a blind tap can hit a link and leave WhatsApp.
    Count them (kv wa_truncated_seen) so we know when it's worth building."""
    n = sum(1 for m in msgs if _TRUNCATED_RE.search(clean(m["text"])))
    if n:
        db.kv_set(conn, "wa_truncated_seen",
                  str(int(db.kv_get(conn, "wa_truncated_seen", "0") or 0) + n))


def _unread(row: ET.Element) -> bool:
    # the badge's count is in content-desc ("3 הודעות שלא נקראו"); its text is
    # empty on this phone - checking text only read nothing on 2026-10-19
    for x in row.iter("node"):
        r = rid(x)
        if ("message_count" in r or "unread" in r) and re.search(
                r"\d", f"{x.get('text') or ''} {x.get('content-desc') or ''}"):
            return True
    return False


def read_pass(conn) -> list[Lead]:
    """Open every allowlisted group that shows an unread badge, read it, and
    return its messages as Leads. Walks the chat list page by page.
    Joined groups that turned out to be full-time feeds (WA_SKIP_GROUP_RE) are
    not opened (Or, 2026-10-20: stay in them, stop reading them)."""
    joined = _joined_titles(conn)
    titles = {t: c for t, c in joined.items() if not config.WA_SKIP_GROUP_RE.search(t)}
    if len(titles) < len(joined):
        log.info("wa read: %d full-time feed group(s) not read", len(joined) - len(titles))
    if not titles:
        return []
    leads: list[Lead] = []
    done: set[str] = set()
    root = scroll_list_top(open_home())
    last_page: tuple = ()
    today = datetime.now(IL).date()
    pages = 0
    while pages < MAX_LIST_PAGES and len(done) < len(titles):
        target, page_names = None, []
        for row in find(root, "contact_row_container"):
            name_n = next((x for x in row.iter("node")
                           if rid(x) == "conversations_row_contact_name"), None)
            if name_n is None:
                continue
            shown = name_n.get("text") or ""
            page_names.append(shown)
            title = _match_title(shown, titles)
            if title and title not in done and _unread(row):
                target = (title, row)
                break
        if target is None:                          # nothing (more) on this page
            if tuple(page_names) == last_page:
                break                               # end of the chat list
            last_page = tuple(page_names)
            pages += 1
            swipe(1700, 700)
            time.sleep(1.2)
            root = dump()
            continue
        title, row = target
        done.add(title)
        tap(*center(row))
        time.sleep(2.5)
        try:
            msgs = read_chat(title)
        except PhoneError as e:
            if isinstance(e, Banned):
                raise
            log.error("wa read: one group failed: %s", e)     # keep the other groups' leads
            LAST_ERRORS.append(f"read: {e}")
            msgs = []
        finally:
            back()
            time.sleep(1.5)
        code = titles[title]
        found = harvest_invites(conn, msgs)
        if found:
            log.info("wa read: %d new invite link(s) queued from a group", found)
        _count_truncated(conn, msgs)
        for m in msgs:
            lead = _to_lead(code, title, m, today)
            if lead:
                leads.append(lead)
        _set_group(conn, code, last_read=datetime.now(timezone.utc).isoformat())
        log.info("wa read: a group gave %d message(s)", len(msgs))
        root = dump()                               # same page; rows may have shifted
    return leads


def _to_lead(code: str, title: str, m: dict, today: date) -> Lead | None:
    """Reuse whatsapp_reader._to_lead so every WhatsApp path builds leads the
    same way. The id hashes group+sender+day+time+text: stable across passes,
    so re-reading a screen is a no-op in db.insert_lead."""
    import whatsapp_reader
    posted = _posted(m, today)
    text = m["text"]
    if m["number"]:
        text += f"\n\nhttps://wa.me/{m['number']}"
    key = f"{code}|{m['sender'] or m['number']}|{m['date']}|{m['time']}|{m['text']}"
    return whatsapp_reader._to_lead({
        "text": text, "chat_jid": code, "chat_name": title,
        "id": hashlib.sha1(key.encode("utf-8")).hexdigest()[:16],
        "sender_name": m["sender"] or (f"+{m['number']}" if m["number"] else None),
        "timestamp": int(posted.timestamp()) if posted else None,
    })


# --- the pass ------------------------------------------------------------------------

def _stage(name: str, fn, conn, default):
    """Run one pass stage. A PhoneError is recorded in LAST_ERRORS and the next
    stage still runs - a crash in the requests re-check blocked every read on
    2026-10-19. Banned is never swallowed."""
    try:
        return fn(conn)
    except Banned:
        raise
    except (PhoneError, sqlite3.Error) as e:
        log.error("wa %s failed: %s", name, e)
        LAST_ERRORS.append(f"{name}: {e}")
        return default


# Errors from the last run_pass's stages; main.job_whatsapp_read raises them
# AFTER ingesting whatever was read, so run_job_safe still alerts.
LAST_ERRORS: list[str] = []


def run_pass(conn) -> list[Lead]:
    """Join (one group, or a burst), re-check pending requests, then read every
    unread allowlisted group. Stage errors land in LAST_ERRORS; a Banned error
    sets the kill switch, alerts and raises."""
    LAST_ERRORS.clear()
    if killed(conn):
        log.warning("wa pass skipped: kill switch set (%s)", killed(conn))
        return []
    load_targets(conn)
    try:
        ensure_ready()
        result = _stage("join", lambda c: join_burst(c) if db.kv_get(c, BURST_KEY, "")
                        else join_next(c), conn, "join failed")
        accepted = _stage("recheck", recheck_requested, conn, 0)
        _stage("home", lambda c: open_home(), conn, None)    # a failed stage may leave a sheet open
        leads = _stage("read", read_pass, conn, [])
        try:
            export_tried(conn)
        except (OSError, subprocess.SubprocessError) as e:
            log.warning("wa tried-codes export failed: %s", e)
        if BUBBLE_IDS_SEEN:
            known = set(filter(None, db.kv_get(conn, "wa_bubble_ids", "").split(",")))
            db.kv_set(conn, "wa_bubble_ids", ",".join(sorted(known | BUBBLE_IDS_SEEN)))
        log.info("wa pass: %s, %d request(s) accepted, %d message lead(s)",
                 result, accepted, len(leads))
        _daily_heartbeat(conn)
        return leads
    except Banned as e:
        db.kv_set(conn, KILL_KEY, f"{datetime.now(timezone.utc).isoformat()} {e}")
        import notifier
        notifier._send_raw(f"\U0001F6D1 <b>WhatsApp phone stopped</b>: {e}\n"
                           "Nothing will touch the phone until you check it and run\n"
                           "<code>python -X utf8 wa_phone.py --unkill</code>")
        raise
    finally:
        sleep_screen()


def group_yield(conn) -> tuple[list[tuple[str, int]], list[str]]:
    """Per joined group over the last 7 days: the top 3 by pushed leads, and the
    groups that produced no message at all (joined 7+ days ago). Report only -
    leaving a group is Or's call."""
    week = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    groups = conn.execute("SELECT title_on_phone, joined_at FROM whatsapp_groups "
                          "WHERE join_status='joined' AND title_on_phone IS NOT NULL").fetchall()
    best, silent = [], []
    for g in groups:
        src = f"whatsapp/{g['title_on_phone']}"
        n_msgs, n_push = conn.execute(
            "SELECT COUNT(*), SUM(status IN ('notified','question_notified')) FROM leads "
            "WHERE source=? AND fetched_at >= ?", (src, week)).fetchone()
        if n_push:
            best.append((g["title_on_phone"], n_push))
        if not n_msgs and (g["joined_at"] or "") < week:
            silent.append(g["title_on_phone"])
    best.sort(key=lambda x: -x[1])
    return best[:3], silent


def _daily_heartbeat(conn) -> None:
    """One Telegram line per morning: the phone is alive, how far the joining
    got, what the last 24h of messages produced. The cloud morning report
    can't say any of this - WhatsApp data lives only in this PC's leads.db."""
    now = datetime.now(IL)
    if now.hour < 8 or db.kv_get(conn, "wa_heartbeat_day", "") == now.date().isoformat():
        return
    groups = dict(conn.execute(
        "SELECT COALESCE(join_status,'todo'), COUNT(*) FROM whatsapp_groups "
        "WHERE priority IS NOT NULL GROUP BY 1").fetchall())
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    st = dict(conn.execute(
        "SELECT status, COUNT(*) FROM leads WHERE source LIKE 'whatsapp/%' AND fetched_at >= ? "
        "GROUP BY status", (since,)).fetchall())
    read = sum(st.values())
    pushed = st.get("notified", 0) + st.get("question_notified", 0)
    import html
    import notifier
    best, silent = group_yield(conn)
    lines = [f"\U0001F4F1 <b>WhatsApp phone OK</b>",
             f"groups: {groups.get('joined', 0)} joined, {groups.get('requested', 0)} pending "
             f"approval, {groups.get('todo', 0)} to go, {groups.get('skipped_spam', 0)} spam / "
             f"{groups.get('skipped_offtopic', 0)} off-topic skipped",
             f"last 24h: {read} message(s) read, {pushed} pushed to you"]
    if best:
        lines.append("best 7d: " + ", ".join(f"{html.escape(t[:30])} ({n})" for t, n in best))
    if silent:
        lines.append(f"silent 7d+: {len(silent)} group(s) - " +
                     ", ".join(html.escape(t[:25]) for t in silent[:5]))
    notifier._send_raw("\n".join(lines))
    db.kv_set(conn, "wa_heartbeat_day", now.date().isoformat())


def status(conn) -> None:
    load_targets(conn)
    print(f"adb       : {ADB}")
    try:
        print(f"device    : {device_state() or 'none'}")
    except PhoneError as e:
        print(f"device    : {e}")
    print(f"kill      : {killed(conn) or 'off'}")
    for st, n in conn.execute("SELECT COALESCE(join_status,'todo'), COUNT(*) FROM whatsapp_groups "
                              "WHERE priority IS NOT NULL GROUP BY 1"):
        print(f"groups    : {st:13} {n}")
    burst = bool(db.kv_get(conn, BURST_KEY, ""))
    print(f"join-all  : {'ON' if burst else 'off'}")
    print(f"joins today: {db.kv_get(conn, 'wa_join_count', '0')} / "
          f"{BURST_DAILY_CAP if burst else JOIN_DAILY_CAP} ({db.kv_get(conn, 'wa_join_day', '-')})")
    n = conn.execute("SELECT COUNT(*) FROM leads WHERE source LIKE 'whatsapp/%'").fetchone()[0]
    print(f"leads     : {n} WhatsApp message(s) stored")
    q = conn.execute("SELECT COUNT(*), SUM(join_status IS NULL) FROM whatsapp_groups "
                     "WHERE found_via=?", (IN_GROUP,)).fetchone()
    print(f"in-group  : {q[0]} invite link(s) found inside groups, {q[1] or 0} not tried yet")
    print(f"truncated : {db.kv_get(conn, 'wa_truncated_seen', '0')} 'read more' message(s) seen")


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="WhatsApp groups via the official app over ADB")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--pass", dest="do_pass", action="store_true",
                    help="one join+read pass; prints counts, does not ingest")
    ap.add_argument("--unkill", action="store_true", help="clear the kill switch")
    ap.add_argument("--join-all", choices=["on", "off"],
                    help="burst-join every remaining group (3-8 min apart, 08-23 IL)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)   # its INFO line carries bot tokens
    conn = db.connect()
    if args.unkill:
        db.kv_set(conn, KILL_KEY, "")
        print("kill switch cleared")
    elif args.join_all:
        db.kv_set(conn, BURST_KEY, "1" if args.join_all == "on" else "")
        print(f"join-all {args.join_all}")
    elif args.do_pass:
        leads = run_pass(conn)
        print(f"{len(leads)} message lead(s) read (not ingested; use main.py --wa-pass)")
    else:
        status(conn)


if __name__ == "__main__":
    main()
