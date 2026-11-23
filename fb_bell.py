"""Local receiver for the AgentLead bell reader (fb_bell_ext/), 2026-11-22 TEST.

Facebook pushes no group posts to email, phone or desktop (all measured), but the
bell page facebook.com/notifications lists "Now in <group>: "<first ~50 chars>...""
within minutes for groups set to "All posts". The Chrome extension in Or's own
browser reads that page and POSTs the entries here.

Each new group-post entry posted within FRESH_MINUTES becomes a Lead
(`facebook/<group>`, post URL, snippet) and goes through pipeline.ingest.
Everything is logged to fb_bell.log (gitignored) for the test.

    python -X utf8 fb_bell.py            # serve on 127.0.0.1:8765
    python -X utf8 fb_bell.py --stats    # summarise fb_bell.log
"""
from __future__ import annotations

import json
import logging
import queue
import re
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config

HOST, PORT = "127.0.0.1", 8765
# Entries older than this are logged, not ingested. 24 h, not 1 h: no safety-net reloads run
# 23:30-07:00, so the morning reload is the catch-up for the night, and Facebook sometimes
# adds a bell entry hours after the post (an 8 h old one arrived live, 2026-11-22). URL dedup
# in db.insert_lead stops a second push when old entries are re-sent.
FRESH_MINUTES = 24 * 60
LOG_FILE = config.BASE_DIR / "fb_bell.log"

log = logging.getLogger("fb_bell")
_jobs: "queue.Queue[dict]" = queue.Queue()
_seen: set[str] = set()


def _minutes(ago: str) -> float | None:
    """'42m' -> 42, '1h' -> 60, 'Just now' -> 0; None when unknown."""
    a = (ago or "").strip().lower()
    if a in ("just now", "now"):
        return 0
    m = re.fullmatch(r"(\d+)\s*([smhdwy])", a)
    if not m:
        return None
    return int(m.group(1)) * {"s": 1 / 60, "m": 1, "h": 60, "d": 1440, "w": 10080, "y": 525600}[m.group(2)]


# the entry's tail: the age label, sometimes followed by " · 1 reaction · 9 comments"
# (measured 2026-11-22), in which case the extension's `ago` is empty
_TAIL_RE = re.compile(r"\s*(just now|now|\d+\s*[smhdwy])(\s*·[^·]*)*\s*$", re.I)


def _age(e: dict) -> str:
    if e.get("ago"):
        return e["ago"]
    m = _TAIL_RE.search(e.get("text") or "")
    return m.group(1) if m else ""


def _snippet(e: dict) -> str:
    """The post's first ~50 chars: the text after the bold group name (or after the first
    ': "' when the bold run is only part of the name), minus the trailing age label."""
    text, group = e.get("text") or "", e.get("group") or ""
    after = text.split(group, 1)[1] if group and group in text else text
    if ': "' in after:
        after = after.split(': "', 1)[1]
    after = _TAIL_RE.sub("", after)
    return after.strip().lstrip(":").strip().strip('"').strip()


AGGREGATE_RE = re.compile(r"^has (a|\d+) new posts?\.?$", re.I)


def to_lead(e: dict):
    """One Lead per entry that shows post text. `multi_permalinks` is a comma list
    (newest first, measured 2026-11-22): the snippet is the first post's. Entries
    that only say "has N new posts." carry no text to score and return None."""
    from models import Lead
    ids = re.findall(r"\d+", e.get("post") or "")
    post = ids[0] if ids else ""
    gpath = re.match(r"/groups/([^/?#]+)", e.get("path") or "")
    if not (post and gpath and e.get("notif_t") == "group_activity"):
        return None
    if not _snippet(e) or AGGREGATE_RE.match(_snippet(e)):
        return None
    group = re.sub(r"[‎‏/]", "", e.get("group") or "").strip()[:60]
    return Lead(source=f"facebook/{group}" if group else "facebook",
                url=f"https://www.facebook.com/groups/{gpath.group(1)}/posts/{post}",
                raw_text=_snippet(e))


def _worker() -> None:
    import db
    import notifier
    import pipeline
    conn = db.connect()
    while True:
        job = _jobs.get()
        try:
            if job["type"] == "blocked":
                notifier._send_raw("⚠️ Facebook bell reader STOPPED for 3 days: "
                                   f"{job.get('reason', '')[:80]}")
                db.kv_set(conn, "fb_bell_blocked_at", str(time.time()))
                continue
            lead = job["lead"]
            status = pipeline.ingest(conn, lead)
            log.info("ingest %s | %s | %s", status, lead.source[:40], lead.raw_text[:60])
        except Exception as ex:      # never let one bad entry kill the receiver
            log.error("worker error: %s", ex)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):      # silence the default stderr access log
        pass

    def do_OPTIONS(self):
        origin = self.headers.get("Origin", "")
        self.send_response(204 if origin.startswith("chrome-extension://") else 403)
        if origin.startswith("chrome-extension://"):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "POST")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-AgentLead-Bell")
        self.end_headers()

    def do_POST(self):
        origin = self.headers.get("Origin", "")
        if self.path != "/fb" or self.headers.get("X-AgentLead-Bell") != "1" or (
                origin and not origin.startswith("chrome-extension://")):
            self.send_response(403); self.end_headers(); return
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0))
        except ValueError:
            self.send_response(400); self.end_headers(); return
        self.send_response(204); self.end_headers()
        handle(body)


def handle(body: dict) -> None:
    kind = body.get("type")
    if kind == "heartbeat":
        log.info("heartbeat %s", body.get("state"))
    elif kind == "blocked":
        log.warning("BLOCKED %s %s", body.get("reason"), (body.get("url") or "")[:80])
        _jobs.put({"type": "blocked", "reason": body.get("reason") or ""})
    elif kind == "entries":
        entries = body.get("entries") or []
        new = 0
        for e in entries:
            key = e.get("notif_id") or ""
            if not key or key in _seen:
                continue
            _seen.add(key)
            new += 1
            age = _minutes(_age(e))
            lead = to_lead(e)
            # an unparsed age on an unread entry is treated as new: dropping a fresh post costs
            # more than re-scoring an old one (URL dedup stops a second push)
            fresh = (age <= FRESH_MINUTES) if age is not None else bool(e.get("unread"))
            if age is None:
                log.info("no-age text tail: %s", (e.get("text") or "")[-40:])
            log.info("entry via=%s ago=%s t=%s fresh=%s posts=%d lead=%s | %s | %s", body.get("via"),
                     _age(e), e.get("notif_t"), fresh, len(re.findall(r"\d+", e.get("post") or "")),
                     bool(lead), (e.get("group") or "")[:40], _snippet(e)[:60])
            if lead and fresh:
                _jobs.put({"type": "lead", "lead": lead})
        log.info("batch via=%s entries=%d new=%d", body.get("via"), len(entries), new)


def serve() -> None:
    threading.Thread(target=_worker, daemon=True).start()
    srv = ThreadingHTTPServer((HOST, PORT), _Handler)
    log.info("fb_bell receiver on http://%s:%d/fb", HOST, PORT)
    srv.serve_forever()


def stats() -> None:
    lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines() if LOG_FILE.exists() else []
    c: dict[str, int] = {}
    for ln in lines:
        for k in ("heartbeat reloaded", "heartbeat user_on_tab", "heartbeat night", "entry via=load",
                  "entry via=live", "fresh=True", "lead=False", "BLOCKED", "ingest pass", "ingest duplicate", "ingest gate_", "ingest scored"):
            if k in ln:
                c[k] = c.get(k, 0) + 1
    print(json.dumps(c, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    logging.basicConfig(filename=LOG_FILE, level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)   # its INFO lines carry API keys in URLs
    if "--stats" in sys.argv:
        stats()
    else:
        serve()
