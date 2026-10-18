"""WhatsApp message -> Lead, shared by every WhatsApp read path.

The reader itself is wa_phone.py: it drives the OFFICIAL app on the dedicated
phone over ADB. The earlier backend here (neonize / Baileys) was removed on
2026-10-18 - both log in as a linked device, the WhatsApp Web surface Meta bans
for automation, and Or ruled that out.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from models import Lead


def _to_lead(msg: dict) -> Lead | None:
    """One WhatsApp message -> a Lead the normal pipeline can handle.

    WhatsApp messages have no URL, so a synthetic one carries the group key and
    a stable message id. That is what db.insert_lead hashes for dedup, so
    re-reading the same history is harmless.
    """
    body = (msg.get("text") or "").strip()
    # "thanks", "+1", stickers are never leads; a short domain question can be
    # ("anyone know a good OCR for Hebrew?" is 35 chars), so the floor sits at
    # the gate's own minimum rather than higher
    if len(body) < 25:
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
        url=f"whatsapp://{jid}/{msg.get('id') or hashlib.sha1(body.encode('utf-8')).hexdigest()[:16]}",
        raw_text=body[:4000],
        author=msg.get("sender_name") or None,
        posted_at=posted,
    )
