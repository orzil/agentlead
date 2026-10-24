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
    whose title is on the allowlist. Allowlisted groups are also opened by
    their own invite link (a member lands in the chat).
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
import json
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
BURST_PAUSED_KEY = "wa_join_all_paused"   # set by a failure pause; blocks the auto re-arm
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

# Wi-Fi fallback (2026-10-21: the USB link dropped mid-evening and every pass
# failed until morning). `--wifi-setup` (cable plugged) switches the phone's adbd
# to TCP and saves its address here; device_state() then uses USB when present
# and this address otherwise. Lost on a phone reboot - re-run the setup.
WIFI_FILE = config.BASE_DIR / ".adb_wifi"
SERIAL = ""                        # picked by device_state() each pass
_NO_SERIAL = {"devices", "connect", "disconnect", "kill-server", "start-server"}


def adb(*args: str, timeout: int = 60, binary: bool = False, stderr: bool = False):
    """One adb call. Subprocess with an argument list, so no shell ever rewrites
    /sdcard paths (Git Bash does)."""
    pick = ["-s", SERIAL] if SERIAL and args[0] not in _NO_SERIAL else []
    try:
        r = subprocess.run([ADB, *pick, *args], capture_output=True, timeout=timeout)
    except FileNotFoundError:
        raise PhoneError(f"adb not found at {ADB} (set ADB_PATH in .env)")
    except subprocess.TimeoutExpired:
        raise PhoneError(f"adb {' '.join(args[:2])} timed out")
    if binary:
        return r.stdout
    return (r.stdout + r.stderr if stderr else r.stdout).decode("utf-8", "replace")


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
            # and relaunch WhatsApp before the last try. Force-stop, not HOME:
            # 2026-10-21 the home screen stayed "could not get idle state"
            # across relaunches until the app process was killed.
            shell("pkill", "-f", "uiautomator")
            shell("am", "force-stop", PKG)
            time.sleep(1)
            shell("am", "start", "-n", f"{PKG}/.Main")
            time.sleep(4)
        # uiautomator prints its errors on stderr - keep them for the message
        out = adb("shell", "uiautomator", "dump", "/sdcard/wa.xml", timeout=40, stderr=True)
        if "dumped" in out:
            raw = adb("exec-out", "cat", "/sdcard/wa.xml", binary=True)
            try:
                return ET.fromstring(raw)
            except ET.ParseError:
                pass
        time.sleep(1.5 + attempt)
    if not out.strip() and device_state() != "device":
        # empty output = adb lost the phone (2026-10-20 22:10: cable/port dropped)
        raise PhoneError("phone disconnected (no USB or Wi-Fi adb) - replug the cable")
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

def _devices() -> dict[str, str]:
    out = adb("devices", timeout=20)
    return dict(line.split()[:2] for line in out.splitlines()[1:] if len(line.split()) >= 2)


def _wifi_addr() -> str:
    try:
        return WIFI_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def device_state() -> str:
    """'device' when attached and authorized; 'unauthorized', 'offline' or ''.
    Picks SERIAL: the USB phone first, the saved Wi-Fi address second."""
    global SERIAL
    devs = _devices()
    usb = {s: st for s, st in devs.items() if ":" not in s}
    for s, st in usb.items():
        if st == "device":
            SERIAL = s
            return st
    wifi = _wifi_addr()
    if wifi:
        if devs.get(wifi) != "device":
            try:
                adb("connect", wifi, timeout=20)
            except PhoneError:      # phone off Wi-Fi: a timeout, not a crash (2026-10-23)
                pass
            devs = _devices()
        if devs.get(wifi) == "device":
            log.info("wa: using Wi-Fi adb (USB not attached)")
            SERIAL = wifi
            return "device"
    SERIAL = ""
    return next(iter(usb.values()), "")


def keep_wifi_fallback() -> None:
    """On USB and the saved Wi-Fi link is dead (phone rebooted or roamed): set it
    up again, so the cable can come out without anyone running --wifi-setup."""
    if not SERIAL or ":" in SERIAL:
        return
    wifi = _wifi_addr()
    if wifi and _devices().get(wifi) == "device":
        return
    try:
        shell("settings", "put", "global", "wifi_sleep_policy", "2")   # keep Wi-Fi up asleep
        log.info("wa: Wi-Fi adb restored at %s", wifi_setup())
    except PhoneError as e:
        log.warning("wa: Wi-Fi adb setup failed: %s", e)


def wifi_setup() -> str:
    """Cable plugged in: put adbd on TCP 5555, connect, save the address."""
    if device_state() != "device" or ":" in SERIAL:
        raise PhoneError("plug the phone in by USB first")
    m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", shell("ip", "-f", "inet", "addr", "show", "wlan0"))
    if not m:
        raise PhoneError("phone has no Wi-Fi address - is Wi-Fi on?")
    addr = f"{m.group(1)}:5555"
    adb("tcpip", "5555", timeout=20)
    time.sleep(3)
    out = adb("connect", addr, timeout=20)
    if "connected" not in out:
        raise PhoneError(f"adb connect {addr} failed: {out.strip()[:80]}")
    WIFI_FILE.write_text(addr, encoding="utf-8")
    return addr


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
        wifi = _wifi_addr() or "not set up"
        raise PhoneError(f"phone unreachable (adb state: {state or 'none'}): not on USB and "
                         f"Wi-Fi {wifi} does not answer. Plug the USB cable in (file-transfer "
                         "mode); the next pass restores the Wi-Fi link by itself.")
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
    pass can start mid-list; swipe down until the top rows stop changing.
    Two unchanged dumps in a row, not one: a single dump taken mid-animation
    looked "stopped" and left passes reading from the middle of the list."""
    def top(r):
        names = [n.get("text") for n in find(r, "conversations_row_contact_name")]
        return names[:3]
    prev, same = top(root), 0
    for _ in range(30):
        swipe(700, 1700, 300)
        time.sleep(0.8)
        root = dump()
        now = top(root)
        same = same + 1 if now == prev else 0
        if same >= 2:
            break
        prev = now
    return root


def open_home_top() -> ET.Element:
    """The chat list scrolled to its top - where every group with new messages
    is. A fresh app process always starts there (measured 2026-10-24), while
    the swipe-up alone left passes reading from mid-list: each pass scrolled
    down up to MAX_LIST_PAGES, the next one swiped back up at most 10 times,
    and the groups with new messages, sorted above, were never seen."""
    shell("am", "force-stop", PKG)
    time.sleep(1)
    return scroll_list_top(open_home())


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


RESEARCH_PRIORITY = -3000         # ahead of everything, CV-named groups included


def add_targets(conn, path: str) -> int:
    """Queue hand-vetted invites (web research, or links Or sends) ahead of the
    night hunt's list. The join sheet still drops dead and get-rich groups, and
    already-tried codes are left alone. Returns how many were queued."""
    now = datetime.now(timezone.utc).isoformat()
    n = 0
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    for i, line in enumerate(lines):
        m = re.search(r"chat\.whatsapp\.com/(?:invite/)?([A-Za-z0-9]{16,32})", line)
        if not m:
            continue
        code = m.group(1)
        name = line.split("|")[0].strip() if "|" in line else ""
        conn.execute(
            "INSERT OR IGNORE INTO whatsapp_groups (code, url, name, status, found_via, first_seen)"
            " VALUES (?, ?, ?, 'live', 'research', ?)",
            (code, f"https://chat.whatsapp.com/{code}", name, now))
        cur = conn.execute(
            "UPDATE whatsapp_groups SET priority=?, status='live' WHERE code=? "
            "AND join_status IS NULL AND COALESCE(joined,0)=0", (RESEARCH_PRIORITY + i, code))
        n += cur.rowcount
    conn.commit()
    return n


def _joined_titles(conn) -> dict[str, str]:
    rows = conn.execute("SELECT code, title_on_phone FROM whatsapp_groups "
                        "WHERE join_status='joined' AND title_on_phone IS NOT NULL").fetchall()
    return {r["title_on_phone"]: r["code"] for r in rows}


def _requested_titles(conn) -> dict[str, str]:
    """Groups this phone asked to join, by the name the invite sheet showed.
    A pending request never creates a chat, so one of these names in the chat
    list means the admin approved it."""
    rows = conn.execute("SELECT code, COALESCE(title_on_phone, name) AS t FROM whatsapp_groups "
                        "WHERE join_status='requested' AND COALESCE(title_on_phone, name) IS NOT NULL"
                        ).fetchall()
    return {clean(r["t"]): r["code"] for r in rows if len(clean(r["t"])) >= 4}


def _mark_accepted(conn, code: str, title: str) -> None:
    _set_group(conn, code, joined=1, join_status="joined", title_on_phone=title,
               joined_at=datetime.now(timezone.utc).isoformat())


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
    for _ in range(10):                      # skip at most a few spam/off-topic sheets per call
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
        if not _sheet_ok(title, desc, row["found_via"]):
            # the sheet's real title + description decide, before a join slot is spent
            _set_group(conn, code, join_status="skipped_offtopic", name=row["name"] or title)
            _close_sheet(root)
            log.info("wa join: skipped an off-topic group on its join sheet (%s)", code[:4])
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
IN_GROUP_GOOD_PRIORITY = 500      # pasted in a work-passing group: tier-0 band


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


def _sheet_ok(title: str, desc: str, found_via: str | None) -> bool:
    """Every target's join sheet is checked, not just in-group links (2026-10-23:
    43 joined job boards gave 0 leads). Off-topic, foreign or full-time-only
    groups are skipped without spending a join slot. In-group links are
    unvetted, so they must also show on-topic vocabulary (_on_topic)."""
    if found_via == IN_GROUP:
        return _on_topic(title, desc)
    import discover_whatsapp_groups as dwg
    import wa_night
    if (config.WA_SKIP_GROUP_RE.search(title) or dwg.WA_NOISE_RE.search(title)
            or wa_night.FOREIGN_RE.search(title)):
        return False
    work = f"{title} {desc}"
    if config.WA_JOB_BOARD_TITLE_RE.search(title) and not (
            config.WA_FREELANCE_GROUP_RE.search(work) or config.WA_BUYER_GROUP_RE.search(work)
            or config.WA_CV_GROUP_RE.search(title)):
        return False
    return not (config.WA_FT_ONLY_SHEET_RE.search(desc)
                and not config.WA_FREELANCE_GROUP_RE.search(f"{title} {desc}"))


def harvest_invites(conn, msgs: list[dict], src_code: str = "") -> int:
    """Members paste other groups' invite links all the time - the cheapest
    discovery surface there is. Queue them behind the night-hunt targets, or in
    the freelance band when the group they came from is itself a work-passing
    one; join_next vets each one on its join sheet (_on_topic)."""
    import discover_whatsapp_groups as dwg
    now = datetime.now(timezone.utc).isoformat()
    base = IN_GROUP_PRIORITY
    src = conn.execute("SELECT name, title_on_phone, found_via FROM whatsapp_groups WHERE code=?",
                       (src_code,)).fetchone() if src_code else None
    if src is not None:
        src_name = f"{src['name'] or ''} {src['title_on_phone'] or ''}"
        if (src["found_via"] == "research" or config.WA_FREELANCE_GROUP_RE.search(src_name)
                or config.WA_BUYER_GROUP_RE.search(src_name)):
            base = IN_GROUP_GOOD_PRIORITY
    new = 0
    for m in msgs:
        for code in set(dwg.WA_INVITE_RE.findall(m["text"])):
            cur = conn.execute(
                "INSERT OR IGNORE INTO whatsapp_groups (code, url, status, found_via, first_seen,"
                " priority) VALUES (?, ?, 'live', ?, ?, ?)",
                (code, f"https://chat.whatsapp.com/{code}", IN_GROUP, now, base + new))
            if cur.rowcount:
                new += 1
            else:   # known from the hunt but never a target: make it one
                conn.execute("UPDATE whatsapp_groups SET priority=?, status='live' WHERE code=? "
                             "AND priority IS NULL AND status IN ('pending','live')",
                             (base, code))
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
            db.kv_set(conn, BURST_PAUSED_KEY, datetime.now(timezone.utc).isoformat())
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
# after each pass - how to confirm or fix the ids below without dumping
# anyone's messages.
BUBBLE_IDS_SEEN: set[str] = set()
# The sender's display name, then the number WhatsApp shows next to an unsaved
# name ("+92 325 ..."); a number becomes the wa.me link on the lead.
_SENDER_IDS = ("name_in_group_tv", "secondary_name_in_group_tv", "name_in_group",
               "pushname_in_group_tv", "pushname_in_group")
# WhatsApp's own text in a bubble, not the sender's: not-yet-decrypted
# ("Waiting for this message") and deleted messages.
_PLACEHOLDER_RE = re.compile(r"בהמתנה להודעה זו|Waiting for this message|ההודעה נמחקה|הודעה זו נמחקה"
                             r"|This message was deleted")
_TRUNCATED_RE = re.compile(r"(קרא עוד|Read more)\s*$")
# A new member sees no history from before the join, and a group never read
# before starts this far back.
WATERMARK_SEED_DAYS = 3
_OLD = date(1970, 1, 1)         # "older than anything": rows above a divider we stopped at


def _bubble_of(n: ET.Element, parent: dict) -> ET.Element | None:
    """The message row that holds text node `n`. The sender's name and number
    sit in the row, one level ABOVE the text+time block; stopping at the first
    ancestor that holds a time node (the old rule) lost every sender
    (2026-10-24). Falls back to that ancestor for row types not seen yet."""
    timed, p = None, parent.get(n)
    while p is not None:
        if rid(p).startswith("conversation_row"):
            return p
        if timed is None and any(rid(x) == "date" for x in p.iter("node")):
            timed = p
        p = parent.get(p)
    return timed


def _messages_on_screen(root: ET.Element, carry_date: date | None, today: date
                        ) -> tuple[list[dict], date | None]:
    """Messages visible now, top to bottom, plus the date in force at the bottom.
    A message's date is the last date divider above it (`carry_date` for the
    ones above the first divider on this screen)."""
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
        bubble = _bubble_of(n, parent)
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
                        number = number or re.sub(r"\D", "", val)
                    elif not sender:
                        sender = val.lstrip("~ ").strip()
        out.append({"text": text, "time": hhmm, "date": cur_date,
                    "sender": sender, "number": number})
    return out, cur_date


def _posted(msg: dict, today: date) -> datetime | None:
    if msg.get("posted"):
        return msg["posted"]
    m = re.match(r"(\d{1,2}):(\d{2})", msg.get("time") or "")
    if not m:
        return None
    d = msg.get("date") or today
    local = datetime(d.year, d.month, d.day, int(m.group(1)), int(m.group(2)), tzinfo=IL)
    if local > datetime.now(IL) + timedelta(minutes=5):     # undated row seen after midnight
        local -= timedelta(days=1)
    return local.astimezone(timezone.utc)


def wa_msg_key(code: str, posted: datetime | None, text: str) -> str:
    """One identity per message, however it was read: group, minute (Israel
    time) and the start of the text. No sender - a notification says '~ name',
    a bubble a name or a number. So a message seen in a notification and again
    on screen, or cut at 'קרא עוד' and later whole, gets the same lead URL and
    db.insert_lead drops the second copy."""
    minute = posted.astimezone(IL).strftime("%Y-%m-%d %H:%M") if posted else "?"
    body = re.sub(r"\s+", " ", clean(_TRUNCATED_RE.sub("", text)))[:200]
    return hashlib.sha1(f"{code}|{minute}|{body}".encode("utf-8")).hexdigest()[:16]


def _row_time(text: str, today: date) -> datetime | None:
    """A chat-list row's last-activity stamp, as an UPPER bound in Israel time:
    '13:44' is today at 13:44; 'אתמול', a weekday or '22.10.2026' name only
    the day, so the end of that day."""
    t = clean(text)
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", t)
    if m:
        return datetime(today.year, today.month, today.day, int(m.group(1)), int(m.group(2)),
                        tzinfo=IL)
    d = parse_divider(t, today) if t else None
    return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=IL) if d else None


def _watermarks(conn, titles: dict[str, str]) -> dict[str, datetime]:
    """last_msg_at per allowlisted title (UTC). A group never read through the
    watermark starts at the newest message already stored from it, else
    WATERMARK_SEED_DAYS back."""
    floor = datetime.now(timezone.utc) - timedelta(days=WATERMARK_SEED_DAYS)
    out = {}
    for title, code in titles.items():
        row = conn.execute("SELECT last_msg_at FROM whatsapp_groups WHERE code=?",
                           (code,)).fetchone()
        if row and row[0]:
            out[title] = datetime.fromisoformat(row[0])
            continue
        got = conn.execute("SELECT MAX(posted_at) FROM leads WHERE source=?",
                           (f"whatsapp/{title}",)).fetchone()[0]
        out[title] = datetime.fromisoformat(got) if got else floor
    return out


def _advance_watermark(conn, code: str, msgs: list[dict],
                       read_at: datetime | None = None) -> None:
    """Move the group's watermark forward (never back): to its newest message,
    and after a complete read to `read_at` as well - everything before it has
    been seen. Without that, a group whose latest activity was a 'joined' line
    or a photo kept its old watermark and was reopened every pass (2026-10-24:
    46 groups opened for 19 messages)."""
    dated = [m for m in msgs if m.get("posted")]
    conn.execute("UPDATE whatsapp_groups SET msgs_seen=COALESCE(msgs_seen,0)+? WHERE code=?",
                 (len(msgs), code))
    marks = []
    if dated:
        newest = max(dated, key=lambda m: m["posted"])
        marks.append((newest["posted"], wa_msg_key(code, newest["posted"], newest["text"])))
    if read_at is not None:
        # a margin for the phone clock and for a message landing mid-read
        marks.append((read_at - timedelta(minutes=2), None))
    if marks:
        at, key = max(marks, key=lambda x: x[0])
        conn.execute("UPDATE whatsapp_groups SET last_msg_at=?, "
                     "last_msg_key=COALESCE(?, last_msg_key) "
                     "WHERE code=? AND (last_msg_at IS NULL OR last_msg_at < ?)",
                     (at.isoformat(), key, code, at.isoformat()))
    conn.commit()


def _dismiss_banners(root: ET.Element) -> bool:
    """WhatsApp's own notification-settings banner in big groups: tap its OK."""
    if first(root, "notification_activity_floating_banner_content") is not None:
        ok = first(root, "notif_action_view_2")
        if ok is not None:
            tap(*center(ok))
            time.sleep(1)
            return True
    return False


def _screen_sig(root: ET.Element) -> tuple:
    return tuple(clean(n.get("text"))[:40] for n in root.iter("node")
                 if rid(n) in _TEXT_IDS + ("date", "conversation_row_date_divider", "info"))


def _reaches(root: ET.Element, since: datetime, latest_day: date, divider_seen: bool,
             today: date) -> bool:
    """While scrolling UP: is this screen already back at the watermark, so
    nothing above it can be new?"""
    since_il = since.astimezone(IL)
    dividers = [d for d in (parse_divider(n.get("text") or "", today)
                            for n in find(root, "conversation_row_date_divider")) if d]
    if dividers and dividers[0] <= since_il.date():
        return True             # everything above the top divider is from an older day
    # below this screen's first divider the date is known; with no divider seen
    # yet at all, the bottom of the chat is the day of its last activity
    page, _ = _messages_on_screen(root, None if divider_seen or dividers else latest_day, today)
    for m in page:
        if m["date"] is None:
            continue
        posted = _posted(m, today)
        if posted is not None and posted <= since:
            return True
    return False


def read_chat(title: str, since: datetime, latest_day: date | None = None) -> list[dict]:
    """The messages newer than `since` (the group's watermark), oldest first.
    Called with the chat open. Jumps to the bottom, reads UP a screen at a
    time until a screen reaches back to `since` (or the top of the chat), then
    parses those screens top-down so each message gets the date divider in
    force above it. The unread badge plays no part: a badge cleared on the
    phone no longer loses messages."""
    today = datetime.now(IL).date()
    latest_day = latest_day or today
    root = dump()
    if _dismiss_banners(root):
        root = dump()
    # (an Element with no children is falsy - never `first(...) or default`)
    header = first(root, "conversation_contact_name")
    if header is None or clean(header.get("text"))[:6] != title[:6]:
        raise PhoneError("opened chat does not match the allowlisted title")
    jump = first(root, "scroll_bottom")
    if jump is not None:
        tap(*center(jump))
        time.sleep(1.5)
        root = dump()
    screens = [root]
    divider_seen = False
    for _ in range(MAX_SCREENS_PER_CHAT):
        if _reaches(root, since, latest_day, divider_seen, today):
            break
        divider_seen = divider_seen or bool(find(root, "conversation_row_date_divider"))
        swipe(600, 1500)
        time.sleep(1.2)
        nxt = dump()
        if _screen_sig(nxt) == _screen_sig(root):
            break                                   # top of the chat
        root = nxt
        screens.append(root)
    any_divider = any(find(s, "conversation_row_date_divider") for s in screens)
    # rows above the top-most divider belong to an older day we did not
    # scroll to; with no divider anywhere, the whole range is latest_day
    carry: date | None = _OLD if any_divider else latest_day
    seen: set[tuple] = set()
    msgs: list[dict] = []
    for scr in reversed(screens):
        page, carry = _messages_on_screen(scr, carry, today)
        for m in page:
            k = (m["sender"], m["time"], m["text"][:80])
            if k not in seen:
                seen.add(k)
                msgs.append(m)
    out = []
    for m in msgs:
        m["posted"] = _posted(m, today)
        if m["posted"] is None or m["posted"] >= since:
            out.append(m)
    return out


def _count_truncated(conn, msgs: list[dict]) -> None:
    """Long posts end in WhatsApp's 'קרא עוד' span and are read cut off. When
    the message also came in a notification, that copy is whole and shares the
    lead URL (wa_msg_key), so it wins. The tap that expands the span isn't
    built: none had been seen when this was written, and a blind tap can hit a
    link and leave WhatsApp. Count them (kv wa_truncated_seen) to know when it
    is worth building."""
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


def _row_text(row: ET.Element, name: str) -> str:
    n = next((x for x in row.iter("node") if rid(x) == name), None)
    return "" if n is None else (n.get("text") or n.get("content-desc") or "")


def _autoskip_codes(conn, titles: dict[str, str]) -> set[str]:
    """Joined groups whose last 7 days were (almost) all full-time job cards:
    stop opening them, as WA_SKIP_GROUP_RE does by name. Measured, not guessed."""
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    out = set()
    for src, n, ft in conn.execute(
            "SELECT source, COUNT(*), SUM(reasoning='gate: full_time') FROM leads "
            "WHERE source LIKE 'whatsapp/%' AND fetched_at >= ? GROUP BY source", (since,)):
        code = titles.get(src.removeprefix("whatsapp/"))
        if (code and n >= config.WA_AUTOSKIP_MIN_MSGS
                and (ft or 0) >= config.WA_AUTOSKIP_FT_SHARE * n):
            out.add(code)
    return out


def _open_chat(code: str, title: str) -> bool:
    """Open a joined group straight from its invite link: for a member WhatsApp
    goes to the chat itself (verified 2026-10-24), wherever the group sits in
    the list and also inside a community. False when the link was reset or
    the chat that opened is not this one."""
    root = _open_invite(code)
    header = first(root, "conversation_contact_name")
    if header is not None and clean(header.get("text"))[:6] == title[:6]:
        return True
    if (first(root, "join_group_bottom_sheet_view_group") is not None
            or first(root, "join_group_bottom_sheet_close_button") is not None):
        _close_sheet(root)
    else:
        back()
        time.sleep(1)
    return False


def read_pass(conn, notified: dict[str, int] | None = None) -> list[Lead]:
    """Read every allowlisted group that has something new since its
    watermark - and open nothing else.

    1. Walk the chat list from the top. A group is picked when its row is
       newer than its watermark, shows an unread badge, or a notification
       said it has news. No tap happens here.
    2. The list is newest-first, so once a row is older than every
       not-yet-seen group's watermark nothing below it can be new: stop.
       (Once a day the walk goes the full MAX_LIST_PAGES, to catch approved
       join requests whose 'you joined' line has sunk.)
    3. Open each picked group by its invite link (row tap as the fallback)
       and read only the messages after its watermark.
    Joined groups that are full-time feeds - by name (WA_SKIP_GROUP_RE) or by
    their measured last 7 days - are not opened (Or, 2026-10-20)."""
    notified = notified or {}
    joined = _joined_titles(conn)
    auto = _autoskip_codes(conn, joined)
    titles = {t: c for t, c in joined.items()
              if not config.WA_SKIP_GROUP_RE.search(t) and c not in auto}
    if len(titles) < len(joined):
        log.info("wa read: %d full-time feed group(s) not read (%d by measurement)",
                 len(joined) - len(titles), len(auto))
    # recheck_requested only spots an approval on the invite sheet, and once
    # you are a member WhatsApp skips the sheet and opens the chat - so 24
    # approved groups (2026-10-24) sat as 'requested' and were never read
    requested = _requested_titles(conn)
    marks = _watermarks(conn, titles)
    today = datetime.now(IL).date()
    picked: dict[str, date] = {}            # title -> day of its last activity
    checked: set[str] = set()
    listed: set[str] = set()                # codes seen on the list in this walk
    was_listed = set(_kv_json(conn, "wa_listed_codes", []))
    full_walk = (db.kv_get(conn, "wa_full_walk_day", "") != today.isoformat()
                 or not was_listed)
    unreachable = _recent_unreachable(conn)
    read_at = datetime.now(timezone.utc)
    root = open_home_top()
    last_page: tuple = ()
    pages = rows = accepted = 0
    stop = False
    while pages < MAX_LIST_PAGES and not stop:
        page_names = []
        for row in find(root, "contact_row_container"):
            name = _row_text(row, "conversations_row_contact_name")
            if not name:
                continue
            page_names.append(name)
            rows += 1
            when = _row_time(_row_text(row, "conversations_row_date"), today)
            approved = _match_title(name, requested)
            if approved:
                code = requested.pop(approved)
                _mark_accepted(conn, code, approved)
                accepted += 1
                if not config.WA_SKIP_GROUP_RE.search(approved):
                    titles[approved] = code
                    marks[approved] = (datetime.now(timezone.utc)
                                       - timedelta(days=WATERMARK_SEED_DAYS))
            title = _match_title(name, titles)
            if title is None and "קהילה" in _row_text(row, "conversations_row_header"):
                # a group inside a community is listed under the community's
                # name; the line under it names the sub-group
                title = _match_title(clean(_row_text(row, "msg_from_tv")).strip(" :~ "),
                                     titles)
            if title and title not in checked:
                checked.add(title)
                listed.add(titles[title])
                # a row with no time (a community row) counts only with a badge
                news = (title in notified
                        or (title not in unreachable
                            and (_unread(row) or (when is not None
                                                  and when > marks[title].astimezone(IL)))))
                if news:
                    picked[title] = (when or datetime.now(IL)).date()
            if not full_walk and rows > 3 and when is not None:   # pinned chats sit on top
                # groups not on the chat list at all (left, or reachable only
                # through a community) must not hold the walk open
                waiting = [marks[t] for t in titles if t not in checked
                           and titles[t] in was_listed and t not in unreachable]
                if not waiting or when < min(waiting).astimezone(IL):
                    stop = True
                    break
        if stop or tuple(page_names) == last_page:
            break                                   # nothing older can be new / list end
        last_page = tuple(page_names)
        pages += 1
        swipe(1700, 700)
        time.sleep(1.2)
        root = dump()
    if full_walk:
        db.kv_set(conn, "wa_full_walk_day", today.isoformat())
        db.kv_set(conn, "wa_listed_codes", json.dumps(sorted(listed)))
    for title in notified:                          # news the list walk missed
        if title in titles and title not in picked:
            picked[title] = today
    # a row no newer than its watermark means nothing new up to now: move the
    # watermark to now, so the next walk can stop as soon as it passes the
    # previous pass instead of digging down to the quietest group's last post
    for title in checked - set(picked):
        _advance_watermark(conn, titles[title], [], read_at)
    log.info("wa read: %d list page(s), %d group row(s) checked, %d with news, %d unchanged "
             "(not opened)", pages + 1, len(checked), len(picked),
             len(checked - set(picked)))

    leads: list[Lead] = []
    by_row: list[str] = []
    new_msgs = 0
    for title, last_day in picked.items():
        code = titles[title]
        msgs, opened = None, False
        try:
            opened = _open_chat(code, title)
            if opened:
                msgs = read_chat(title, marks[title], last_day)
            else:
                by_row.append(title)
        except PhoneError as e:
            if isinstance(e, Banned):
                raise
            log.error("wa read: one group failed: %s", e)     # keep the other groups' leads
            LAST_ERRORS.append(f"read: {e}")
        finally:
            if opened:
                back()
                time.sleep(1)
        if msgs is not None:
            leads += _ingestable(conn, code, title, msgs, read_at)
            new_msgs += len(msgs)
    if by_row:
        leads += _read_by_row(conn, by_row, titles, marks, picked, read_at)
    if accepted:
        log.info("wa read: %d join request(s) found approved on the chat list", accepted)
    log.info("wa read: %d new message(s) from %d group(s)", new_msgs, len(picked))
    _bump_read_stats(conn, opened=len(picked), skipped=len(checked - set(picked)),
                     msgs=new_msgs)
    return leads


def _kv_json(conn, key: str, default):
    try:
        return json.loads(db.kv_get(conn, key, "") or "null") or default
    except ValueError:
        return default


UNREACHABLE_HOURS = 24


def _recent_unreachable(conn) -> set[str]:
    """Titles neither the invite link nor the row tap could open lately (a
    reset link plus a community row): not retried for UNREACHABLE_HOURS,
    unless a notification says they have news."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=UNREACHABLE_HOURS)).isoformat()
    return {t for t, at in _kv_json(conn, "wa_unreachable", {}).items() if at >= cutoff}


def _remember_unreachable(conn, titles: set[str]) -> None:
    cur = _kv_json(conn, "wa_unreachable", {})
    now = datetime.now(timezone.utc).isoformat()
    cur.update({t: now for t in titles})
    db.kv_set(conn, "wa_unreachable", json.dumps(cur, ensure_ascii=False))


def _bump_read_stats(conn, **add: int) -> None:
    """Today's reader totals for the heartbeat (kv wa_read_stats)."""
    today = datetime.now(IL).date().isoformat()
    try:
        cur = json.loads(db.kv_get(conn, "wa_read_stats", "") or "{}")
    except ValueError:
        cur = {}
    if cur.get("day") != today:
        if cur.get("day"):
            db.kv_set(conn, "wa_read_stats_prev", json.dumps(cur))   # the heartbeat's "yesterday"
        cur = {"day": today}
    for k, v in add.items():
        cur[k] = cur.get(k, 0) + v
    db.kv_set(conn, "wa_read_stats", json.dumps(cur))


def _ingestable(conn, code: str, title: str, msgs: list[dict],
                read_at: datetime | None = None) -> list[Lead]:
    """Bookkeeping after one group's read, then its messages as Leads."""
    found = harvest_invites(conn, msgs, code)
    if found:
        log.info("wa read: %d new invite link(s) queued from a group", found)
    _count_truncated(conn, msgs)
    today = datetime.now(IL).date()
    leads = [ld for ld in (_to_lead(code, title, m, today) for m in msgs) if ld]
    _advance_watermark(conn, code, msgs, read_at)
    _set_group(conn, code, last_read=datetime.now(timezone.utc).isoformat())
    log.info("wa read: a group gave %d new message(s)", len(msgs))
    return leads


def _read_by_row(conn, wanted: list[str], titles: dict[str, str],
                 marks: dict[str, datetime], picked: dict[str, date],
                 read_at: datetime | None = None) -> list[Lead]:
    """Fallback for groups whose invite link was reset: find the row and tap it."""
    leads: list[Lead] = []
    todo = set(wanted)
    failed: set[str] = set()
    root = open_home_top()
    last_page: tuple = ()
    for _ in range(MAX_LIST_PAGES):
        names, hit = [], None
        for row in find(root, "contact_row_container"):
            name = _row_text(row, "conversations_row_contact_name")
            names.append(name)
            title = _match_title(name, {t: titles[t] for t in todo})
            if title:
                hit = (title, row)
                break
        if hit is None:
            if tuple(names) == last_page:
                break
            last_page = tuple(names)
            swipe(1700, 700)
            time.sleep(1.2)
            root = dump()
            continue
        title, row = hit
        todo.discard(title)
        tap(*center(row))
        time.sleep(2.5)
        try:
            msgs = read_chat(title, marks[title], picked.get(title))
            leads += _ingestable(conn, titles[title], title, msgs, read_at)
        except PhoneError as e:
            if isinstance(e, Banned):
                raise
            # expected for a community row (it opens the community, not the
            # sub-group): counted below, not an alert every pass
            log.info("wa read: row fallback did not open the group: %s", e)
            failed.add(title)
        finally:
            back()
            time.sleep(1.5)
        if not todo:
            break
        root = dump()
    if todo or failed:
        log.info("wa read: %d group(s) not reachable by link or row", len(todo) + len(failed))
        _remember_unreachable(conn, todo | failed)
    return leads


def _to_lead(code: str, title: str, m: dict, today: date) -> Lead | None:
    """Reuse whatsapp_reader._to_lead so every WhatsApp path builds leads the
    same way. The URL id is wa_msg_key: stable across passes and across the
    two read paths (screen, notification), so a re-read is a no-op in
    db.insert_lead."""
    import whatsapp_reader
    posted = _posted(m, today)
    text = m["text"]
    if m["number"]:
        text += f"\n\nhttps://wa.me/{m['number']}"
    return whatsapp_reader._to_lead({
        "text": text, "chat_jid": code, "chat_name": title,
        "id": wa_msg_key(code, posted, m["text"]),
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
    if (load_targets(conn) and config.WA_JOIN_ALL_AUTO and not db.kv_get(conn, BURST_KEY, "")
            and not db.kv_get(conn, BURST_PAUSED_KEY, "")):
        db.kv_set(conn, BURST_KEY, "1")      # a new night list: join it all (Or's call)
        log.info("wa: new night-hunt targets - join-all re-armed")
    try:
        ensure_ready()
        # before anything opens WhatsApp: opening the app clears its notifications
        import wa_notify
        notif_leads, news = _stage("notify", wa_notify.harvest, conn, ([], {}))
        result = _stage("join", lambda c: join_burst(c) if db.kv_get(c, BURST_KEY, "")
                        else join_next(c), conn, "join failed")
        accepted = _stage("recheck", recheck_requested, conn, 0)
        _stage("home", lambda c: open_home(), conn, None)    # a failed stage may leave a sheet open
        # notification copies first: they are whole where the screen shows
        # 'קרא עוד', and share the lead URL, so the screen copy is the duplicate
        leads = notif_leads + _stage("read", lambda c: read_pass(c, news), conn, [])
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
        keep_wifi_fallback()      # after the pass: `adb tcpip` restarts adbd


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
    try:
        prev = json.loads(db.kv_get(conn, "wa_read_stats_prev", "") or "{}")
    except ValueError:
        prev = {}
    if prev:
        lines.append(f"reader {prev['day']}: {prev.get('opened', 0)} group read(s) with news, "
                     f"{prev.get('skipped', 0)} unchanged skipped, {prev.get('msgs', 0)} new msg(s)")
    gate = dict(conn.execute(
        "SELECT reasoning, COUNT(*) FROM leads WHERE source LIKE 'whatsapp/%' AND fetched_at >= ? "
        "AND status='gated_out' GROUP BY reasoning", (since,)).fetchall())
    if gate:
        lines.append("gated 24h: " + ", ".join(f"{k.removeprefix('gate: ')} {v}"
                                                for k, v in sorted(gate.items(), key=lambda x: -x[1])))
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
                    help="burst-join every remaining group (3-8 min apart, 08-23 IL); each new "
                         "night list re-arms it (WA_JOIN_ALL_AUTO) until a manual off")
    ap.add_argument("--wifi-setup", action="store_true",
                    help="(USB plugged) enable adb over Wi-Fi as the fallback link")
    ap.add_argument("--add-targets", metavar="FILE",
                    help="queue hand-vetted invite links (lines 'name | url ...') AHEAD of the "
                         "night hunt's list, in file order")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)   # its INFO line carries bot tokens
    conn = db.connect()
    if args.unkill:
        db.kv_set(conn, KILL_KEY, "")
        print("kill switch cleared")
    elif args.join_all:
        db.kv_set(conn, BURST_KEY, "1" if args.join_all == "on" else "")
        # a manual off also stops the morning auto re-arm until the next `on`
        db.kv_set(conn, BURST_PAUSED_KEY, "" if args.join_all == "on" else "manual off")
        print(f"join-all {args.join_all}")
    elif args.wifi_setup:
        print(f"Wi-Fi adb ready: {wifi_setup()} (saved to {WIFI_FILE.name})")
    elif args.add_targets:
        print(f"{add_targets(conn, args.add_targets)} target(s) queued first")
    elif args.do_pass:
        leads = run_pass(conn)
        print(f"{len(leads)} message lead(s) read (not ingested; use main.py --wa-pass)")
    else:
        status(conn)


if __name__ == "__main__":
    main()
