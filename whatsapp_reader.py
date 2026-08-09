"""Read job posts out of WhatsApp groups - on a DEDICATED number, never Or's.

WhatsApp has no public read surface at all: message content is not published and
not indexed, only the invite page is. So unlike Facebook (where the search index
saves us) the only way in is to be a member. That means an account, and an
account means ban risk - which is why this runs on a THROWAWAY number. If Meta
bans it for automation, Or loses a spare SIM, not his personal WhatsApp.

Design rules, all load-bearing:
  * LOCAL ONLY. A linked-device session must persist; GitHub runners are
    ephemeral, so this can never move to the cloud. It is also an authenticated
    session, so none of Meta's datacenter-IP blocking applies.
  * ALLOWLIST ONLY. It ingests messages from group JIDs listed in
    WHATSAPP_GROUP_ALLOWLIST and ignores everything else, so private chats on
    that number are never read.
  * READ-ONLY. It never sends a message, never replies, never joins a group.
    Joining stays a human action, as it is for Facebook.
  * DORMANT BY DEFAULT. With no session and no library installed, fetch()
    returns [] and logs one line. It must never break the scheduler.

Backends, in order:
  1. neonize (PyPI, whatsmeow bindings) - pure pip, preferred.
  2. Baileys under Node (v24 present) writing JSONL that this tails - fallback
     if the compiled bindings misbehave on Windows.

Setup (one time, with the second phone):
    pip install neonize
    python -X utf8 whatsapp_reader.py --pair      # shows a QR; scan it
    python -X utf8 whatsapp_reader.py --groups    # list JIDs you're in
    # put the wanted JIDs in WHATSAPP_GROUP_ALLOWLIST in .env, comma-separated
    python -X utf8 whatsapp_reader.py --listen    # runs the collector
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import config
from models import Lead

log = logging.getLogger("whatsapp")

SESSION_DIR = config.BASE_DIR / "wa_session"      # gitignored: these are credentials
INBOX = SESSION_DIR / "inbox.jsonl"               # backend writes here, we read it
_CURSOR_KEY = "wa_inbox_offset"


def _allowlist() -> set[str]:
    raw = config.env("WHATSAPP_GROUP_ALLOWLIST", "")
    return {j.strip() for j in raw.split(",") if j.strip()}


def available() -> tuple[bool, str]:
    """Is the reader usable right now? Returns (ready, human explanation)."""
    if not SESSION_DIR.exists():
        return False, "not paired (no wa_session/) - see whatsapp_reader.py docstring"
    if not _allowlist():
        return False, "paired but WHATSAPP_GROUP_ALLOWLIST is empty"
    return True, "ready"


# --- ingestion ----------------------------------------------------------------

def _to_lead(msg: dict) -> Lead | None:
    """One WhatsApp message -> a Lead the normal pipeline can handle.

    WhatsApp messages have no URL, so a synthetic one carries the group JID and
    message id. That is what db.insert_lead hashes for dedup, so re-reading the
    same history is harmless.
    """
    body = (msg.get("text") or "").strip()
    if len(body) < 40:            # "thanks", "+1", stickers - never a job post
        return None
    jid = msg.get("chat_jid") or "unknown"
    group = msg.get("chat_name") or jid.split("@")[0]
    posted = None
    ts = msg.get("timestamp")
    if ts:
        try:
            posted = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        except (ValueError, OSError, TypeError):
            pass
    return Lead(
        source=f"whatsapp/{group}",
        url=f"whatsapp://{jid}/{msg.get('id') or hash(body)}",
        raw_text=body[:4000],
        author=msg.get("sender_name") or None,
        posted_at=posted,
    )


def fetch(conn: sqlite3.Connection) -> list[Lead]:
    """Scheduler entry point. Drains whatever the backend has written since the
    last run. No-ops loudly-but-harmlessly when unpaired."""
    ready, why = available()
    if not ready:
        log.debug("whatsapp reader idle: %s", why)
        return []
    if not INBOX.exists():
        log.info("whatsapp: no inbox yet (is --listen running?)")
        return []

    allow = _allowlist()
    offset = int(_kv_get(conn, _CURSOR_KEY, "0") or "0")
    leads: list[Lead] = []
    line_no = 0
    with INBOX.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if line_no <= offset:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("chat_jid") not in allow:
                continue          # allowlist: private chats never get read
            lead = _to_lead(msg)
            if lead:
                leads.append(lead)
    _kv_set(conn, _CURSOR_KEY, str(line_no))
    log.info("whatsapp: %d new message(s) from %d allowlisted group(s)",
             len(leads), len(allow))
    return leads


def _kv_get(conn, key, default=""):
    import db
    return db.kv_get(conn, key, default)


def _kv_set(conn, key, value):
    import db
    db.kv_set(conn, key, value)


# --- backend (only touched during setup / listening) --------------------------

def _require_neonize():
    try:
        import neonize  # noqa: F401
        return True
    except ImportError:
        print("neonize is not installed. Run:  pip install neonize")
        print("(fallback: Baileys under Node - see the module docstring)")
        return False


def pair() -> None:
    """One-time QR pairing with the DEDICATED number. Never Or's own."""
    if not _require_neonize():
        return
    SESSION_DIR.mkdir(exist_ok=True)
    print("\n*** Scan this QR with the SECOND phone, not your personal one. ***\n")
    # NOTE: the decorator lives on the INSTANCE (NewClient.__init__ does
    # `self.event = Event(self)`), not on the class - checking the class for it
    # is misleading.
    from neonize.client import NewClient
    from neonize.events import ConnectedEv, PairStatusEv

    client = NewClient(str(SESSION_DIR / "session.sqlite3"))

    @client.event(ConnectedEv)
    def _on_connected(_c, _e):
        print("connected - pairing stored in wa_session/. Ctrl+C, then --groups.")

    @client.event(PairStatusEv)
    def _on_pair(_c, e):
        print("paired as:", getattr(e, "ID", "?"))

    client.connect()


def list_groups() -> None:
    """Print the JIDs of groups this account is in, for the allowlist."""
    if not _require_neonize():
        return
    from neonize.client import NewClient

    client = NewClient(str(SESSION_DIR / "session.sqlite3"))
    try:
        for g in client.get_joined_groups():
            print(f"{getattr(g, 'JID', '?')}\t{getattr(g, 'GroupName', {})}")
    except Exception as e:
        print("could not list groups (is the session paired?):", e)


def listen() -> None:
    """Append allowlisted group messages to inbox.jsonl for fetch() to drain.

    Kept deliberately dumb: it only writes lines. All filtering, scoring and
    notifying stays in the normal pipeline, so WhatsApp gets exactly the same
    treatment as every other source.
    """
    if not _require_neonize():
        return
    SESSION_DIR.mkdir(exist_ok=True)
    allow = _allowlist()
    if not allow:
        print("WHATSAPP_GROUP_ALLOWLIST is empty - nothing would be read. "
              "Run --groups first.")
        return
    from neonize.client import NewClient
    from neonize.events import MessageEv

    client = NewClient(str(SESSION_DIR / "session.sqlite3"))

    @client.event(MessageEv)
    def _on_message(_c, e):
        try:
            info = e.Info
            jid = f"{info.MessageSource.Chat.User}@{info.MessageSource.Chat.Server}"
            if jid not in allow:
                return
            text = (e.Message.conversation
                    or getattr(e.Message.extendedTextMessage, "text", "") or "")
            if not text:
                return
            rec = {"id": info.ID, "chat_jid": jid,
                   "chat_name": getattr(info, "PushName", "") or jid.split("@")[0],
                   "sender_name": getattr(info, "PushName", ""),
                   "timestamp": int(getattr(info, "Timestamp", 0) or 0),
                   "text": text}
            with INBOX.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception as ex:      # never let one bad message kill the listener
            log.debug("whatsapp message skipped: %s", ex)

    print(f"listening to {len(allow)} allowlisted group(s); Ctrl+C to stop")
    client.connect()


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="WhatsApp reader (dedicated number, read-only)")
    ap.add_argument("--pair", action="store_true", help="one-time QR pairing")
    ap.add_argument("--groups", action="store_true", help="list joined group JIDs")
    ap.add_argument("--listen", action="store_true", help="collect messages to inbox.jsonl")
    ap.add_argument("--status", action="store_true", help="is the reader ready?")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s [%(name)s] %(message)s")
    if args.pair:
        pair()
    elif args.groups:
        list_groups()
    elif args.listen:
        listen()
    else:
        ready, why = available()
        print(f"whatsapp reader: {'READY' if ready else 'IDLE'} - {why}")
        print(f"session dir : {SESSION_DIR}")
        print(f"allowlist   : {sorted(_allowlist()) or '(empty)'}")
        print(f"inbox lines : {sum(1 for _ in INBOX.open(encoding='utf-8')) if INBOX.exists() else 0}")


if __name__ == "__main__":
    main()
