"""The processing pipeline every fetched post goes through:

    dedup (URL + fuzzy text)  ->  keyword gate  ->  LLM score  ->  route
"""
from __future__ import annotations

import logging
import sqlite3

import config
import db
import freshness
import notifier
import prefilter
import scorer
from models import Lead

log = logging.getLogger("pipeline")


def ingest(conn: sqlite3.Connection, lead: Lead) -> str:
    """Process one lead end-to-end. Returns final status string."""
    if not lead.url or not lead.raw_text:
        return "skipped_empty"

    lead_id = db.insert_lead(conn, lead)
    if lead_id is None:
        return "duplicate"

    verdict = prefilter.classify(lead)
    if verdict == "partnership":
        # equity/co-founder asks: low-priority bucket, no scoring, no pushes
        conn.execute("UPDATE leads SET status='partnership', reasoning='gate: partnership' "
                     "WHERE id=?", (lead_id,))
        conn.commit()
        return "partnership"
    if verdict != "pass":
        # keep the gate reason in `reasoning` for tuning (e.g. 'gate: full_time')
        conn.execute("UPDATE leads SET status='gated_out', reasoning=? WHERE id=?",
                     (f"gate: {verdict.removeprefix('gate_')}", lead_id))
        conn.commit()
        return verdict  # per-reason stats, e.g. gate_full_time

    try:
        score = scorer.score_lead(lead)
    except Exception as e:
        log.error("scoring failed for lead %s: %s", lead_id, e)
        db.set_status(conn, lead_id, "error")
        return "error"

    if score is None:  # no LLM backend configured -> store for later
        db.set_status(conn, lead_id, "scored")
        return "stored_unscored"

    # Age is applied here, not in the rubric: the model rarely knows the date
    # because posts seldom state it, while the fetcher always does. A month-old
    # gig is usually filled and must not sit at the top of the table.
    score, _days = freshness.apply(score, lead.posted_at, lead.raw_text)

    if score.score >= config.PUSH_THRESHOLD:
        db.save_score(conn, lead_id, score, "scored")
        row = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
        pitch = scorer.draft_pitch(lead) if config.PITCH_DRAFTS else None
        ok = notifier.notify_lead(row, pitch=pitch)
        db.set_status(conn, lead_id, "notified" if ok else "scored")
        if score.score >= config.REPLY_MIN_SCORE:
            try:
                import replier
                replier.consider(conn, lead_id)
            except Exception as e:
                log.error("replier failed for lead %s: %s", lead_id, e)
        return "notified"

    if score.score >= config.DIGEST_THRESHOLD:
        db.save_score(conn, lead_id, score, "digest_pending")
        return "digest_pending"

    db.save_score(conn, lead_id, score, "scored")
    return "scored_low"


def ingest_many(conn: sqlite3.Connection, leads: list[Lead], job: str) -> dict[str, int]:
    stats: dict[str, int] = {}
    for lead in leads:
        try:
            status = ingest(conn, lead)
        except Exception as e:
            log.exception("ingest failed in %s: %s", job, e)
            status = "error"
        stats[status] = stats.get(status, 0) + 1
    if stats:
        log.info("[%s] %s", job, stats)
    return stats
