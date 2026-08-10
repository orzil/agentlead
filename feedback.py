"""Turn Or's one-word Telegram replies into permanent training signal.

Every accuracy fix in this project so far started with him spotting a bad lead
and explaining it in chat: a full-time role scored 7, an expired listing, a
seeker self-promo, a $30 budget. Each was a real gate gap - and each judgement
was then thrown away, so nothing stopped the same class of mistake returning.

This closes that loop with the smallest possible interface. He replies to the
lead's Telegram message with ONE WORD. The verdict is recorded against the lead,
appended to eval_cases.json (the regression set), and - for the negative
verdicts - names the gate that should have caught it, so tuning has a target.

Nothing here sends messages or changes leads he did not judge.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import config
import db

log = logging.getLogger("feedback")

EVAL_FILE = config.BASE_DIR / "eval_cases.json"

# verdict -> (what it means for the lead, which gate SHOULD have caught it)
VERDICTS = {
    "good":     ("keep", None),
    "applied":  ("handled", None),
    "fulltime": ("bad", "gate_full_time"),
    "old":      ("bad", "gate_stale"),
    "expired":  ("bad", "gate_stale"),
    "closed":   ("bad", "gate_closed"),
    "spam":     ("bad", "gate_spam"),
    "seeker":   ("bad", "gate_seeker"),
    "lowpay":   ("bad", "gate_lowbudget"),
    "crowded":  ("bad", "gate_crowded"),
    "offtopic": ("bad", "gate_offtopic"),
}
# volume controls - Or tunes the push threshold himself rather than asking
TUNING = {"less": +1, "more": -1}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _append_eval_case(lead_row, verdict: str, expected_gate: str | None) -> None:
    """Grow the regression set. Positive cases matter as much as negative ones:
    a gate that rejects everything scores 100% on rejections alone."""
    cases = []
    if EVAL_FILE.exists():
        try:
            cases = json.loads(EVAL_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cases = []
    # A later verdict REPLACES an earlier one rather than being ignored: Or
    # changing his mind about a lead is information, and silently keeping the
    # first answer would bake a wrong label into the regression set forever.
    cases = [c for c in cases if c.get("url") != lead_row["url"]]
    cases.append({
        "url": lead_row["url"],
        "source": lead_row["source"],
        "text": (lead_row["raw_text"] or "")[:1200],
        "posted_at": lead_row["posted_at"],
        "verdict": verdict,
        "expect": expected_gate or "pass",
        "scored": lead_row["score"],
        "added": _now(),
    })
    EVAL_FILE.write_text(json.dumps(cases, ensure_ascii=False, indent=1),
                         encoding="utf-8")


def _apply(conn, lead_id: int, word: str) -> str:
    row = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    if row is None:
        return "lead gone"
    action, expected_gate = VERDICTS[word]
    conn.execute("UPDATE leads SET verdict=?, verdict_at=? WHERE id=?",
                 (word, _now(), lead_id))
    if action == "bad":
        conn.execute("UPDATE leads SET status='gated_out', reasoning=? WHERE id=?",
                     (f"user verdict: {word} (should have been {expected_gate})", lead_id))
    elif action == "handled":
        conn.execute("UPDATE leads SET status='handled' WHERE id=?", (lead_id,))
    # "good" deliberately changes no status - it is a positive label, not an action
    conn.commit()
    _append_eval_case(row, word, expected_gate)
    return f"lead {lead_id} marked {word}"


def poll(conn) -> dict:
    """Read replies since the last offset and act on them."""
    import httpx

    if not config.TELEGRAM_BOT_TOKEN:
        return {}
    offset = int(db.kv_get(conn, "tg_update_offset", "0") or 0)
    try:
        r = httpx.get(
            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates",
            params={"offset": offset + 1, "timeout": 0, "allowed_updates": '["message"]'},
            timeout=25)
        r.raise_for_status()
        updates = r.json().get("result", [])
    except Exception as e:
        log.info("feedback poll failed: %s", str(e)[:90])
        return {}

    counts: dict[str, int] = {}
    for u in updates:
        offset = max(offset, u.get("update_id", 0))
        msg = u.get("message") or {}
        word = (msg.get("text") or "").strip().lower().split()[:1]
        word = word[0] if word else ""
        if word in TUNING:
            new = max(1, min(10, config.PUSH_THRESHOLD + TUNING[word]))
            db.kv_set(conn, "push_threshold_override", str(new))
            counts[f"threshold->{new}"] = counts.get(f"threshold->{new}", 0) + 1
            log.info("push threshold retuned to %d by '%s'", new, word)
            continue
        if word not in VERDICTS:
            continue
        replied_to = (msg.get("reply_to_message") or {}).get("message_id")
        if not replied_to:
            continue          # a bare word with no reply target judges nothing
        lead_id = db.lead_for_message(conn, replied_to)
        if not lead_id:
            continue
        log.info("%s", _apply(conn, lead_id, word))
        counts[word] = counts.get(word, 0) + 1
    db.kv_set(conn, "tg_update_offset", str(offset))
    if counts:
        log.info("feedback: %s", counts)
    return counts
