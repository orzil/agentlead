"""Measure what the keyword gate throws away.

The gate decides ~88% of everything the agent sees - 8,326 leads rejected
against 1,098 scored - and it had never once been checked. Every fix to it so
far came from Or noticing a bad lead that got through (a false POSITIVE). Nobody
had ever looked at the opposite and far more expensive error: real work silently
killed before it could be scored.

Method: re-score recent gated-out leads with the LLM, WITHOUT telling it the
gate's verdict, so the two judgements are independent. A lead the gate killed
that the LLM now rates >= 6 is a candidate false negative.

Scoped to recent leads on purpose (Or's call) - old rejections are stale gigs
anyway, so re-checking them would burn the night for nothing.

Cost: nothing. Ollama is local and unlimited, which is what makes an audit of
thousands of leads possible at all.

Usage:
  python -X utf8 audit_gate.py --dry-run 20     # inspect, change nothing
  python -X utf8 audit_gate.py --days 5         # full pass, resurrect the misses
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone

import config
import db
import scorer
from models import Lead

log = logging.getLogger("audit")

# A killed lead scoring this well was probably a mistake worth reviewing...
SUSPECT_AT = 6
# ...and this well is worth putting straight back into the flow.
RESURRECT_AT = 7

REPORT = config.BASE_DIR / "gate_audit.md"


def _rows(conn, days: int, limit: int, reasons: list[str] | None):
    q = ("SELECT id, source, url, raw_text, posted_at, fetched_at, reasoning "
         "FROM leads WHERE status='gated_out' "
         f"AND fetched_at >= date('now','-{int(days)} days')")
    params: list = []
    if reasons:
        q += " AND (" + " OR ".join("reasoning LIKE ?" for _ in reasons) + ")"
        params += [f"%{r}%" for r in reasons]
    # Newest first: if the night runs short, the most actionable leads are done.
    q += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    return conn.execute(q, params).fetchall()


def audit(conn, days: int = 5, limit: int = 3000, dry_run: bool = False,
          reasons: list[str] | None = None) -> dict:
    rows = _rows(conn, days, limit, reasons)
    log.info("auditing %d gated-out leads from the last %d days", len(rows), days)
    per_reason: dict[str, dict] = {}
    misses: list[dict] = []

    for i, r in enumerate(rows, 1):
        reason = (r["reasoning"] or "gate: ?").replace("gate: ", "").split(" (")[0]
        stat = per_reason.setdefault(reason, {"checked": 0, "suspect": 0, "resurrect": 0})
        lead = Lead(source=r["source"], url=r["url"], raw_text=r["raw_text"])
        try:
            score = scorer.score_lead(lead)
        except Exception as e:
            log.debug("scoring failed for %s: %s", r["id"], str(e)[:60])
            continue
        if score is None:
            log.warning("no scoring backend available - stopping the audit")
            break
        stat["checked"] += 1
        if score.score >= SUSPECT_AT:
            stat["suspect"] += 1
            misses.append({"id": r["id"], "reason": reason, "score": score.score,
                           "source": r["source"], "url": r["url"],
                           "summary": score.summary,
                           "text": (r["raw_text"] or "")[:300]})
            if score.score >= RESURRECT_AT and not dry_run:
                # back into the normal flow, with the audit recorded so a human
                # can see why it reappeared
                db.save_score(conn, r["id"], score, "scored")
                conn.execute(
                    "UPDATE leads SET reasoning=? WHERE id=?",
                    (f"[gate audit] resurrected from '{reason}' at {score.score}/10 - "
                     f"{score.reasoning or ''}", r["id"]))
                conn.commit()
                stat["resurrect"] += 1
        if i % 50 == 0:
            log.info("  %d/%d checked, %d suspect so far", i, len(rows), len(misses))

    return {"per_reason": per_reason, "misses": misses, "checked": len(rows)}


def write_report(result: dict) -> str:
    per = result["per_reason"]
    misses = result["misses"]
    lines = [
        "# Gate audit",
        "",
        f"*{datetime.now(timezone.utc).isoformat(timespec='seconds')} — re-scored "
        f"recent gate rejections with the LLM, blind to the gate's verdict.*",
        "",
        "A high false-negative rate means the gate is killing real work. A low one "
        "means it is doing its job and the leads simply are not there.",
        "",
        "| gate reason | checked | scored ≥6 | rate | resurrected (≥7) |",
        "|---|---:|---:|---:|---:|",
    ]
    for reason, s in sorted(per.items(), key=lambda kv: -kv[1]["checked"]):
        rate = (s["suspect"] / s["checked"] * 100) if s["checked"] else 0
        lines.append(f"| {reason} | {s['checked']} | {s['suspect']} | "
                     f"**{rate:.1f}%** | {s['resurrect']} |")
    lines += ["", "## Worst misses", ""]
    for m in sorted(misses, key=lambda x: -x["score"])[:10]:
        lines += [f"**{m['score']}/10** — killed as `{m['reason']}` — {m['source']}",
                  f"> {(m['summary'] or m['text'])[:220]}", f"<{m['url']}>", ""]
    if not misses:
        lines.append("*No rejected lead scored ≥6. The gate looks correct.*")
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    return str(REPORT)


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit what the keyword gate rejects")
    ap.add_argument("--days", type=int, default=5)
    ap.add_argument("--limit", type=int, default=3000)
    ap.add_argument("--dry-run", nargs="?", const=20, type=int, metavar="N",
                    help="check N leads and change nothing")
    ap.add_argument("--reason", action="append",
                    help="restrict to a gate reason, e.g. --reason offtopic")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s")

    conn = db.connect()
    limit = args.dry_run if args.dry_run else args.limit
    result = audit(conn, days=args.days, limit=limit,
                   dry_run=bool(args.dry_run), reasons=args.reason)
    print(json.dumps(result["per_reason"], indent=1))
    print("report:", write_report(result))


if __name__ == "__main__":
    main()
