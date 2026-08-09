"""Lead-generation agent - free-tier-only pipeline.

Run modes:
    python main.py                  run forever (scheduler loop)
    python main.py --once           run every fetcher once, then exit
    python main.py --test-telegram  send a test message to your Telegram bot
    python main.py --score-test "some job post text"   score one text and print it
    python main.py --digest-now     send the pending digest immediately
    python main.py --stats          print DB counts per status/source
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime

import config
import db
import notifier
import pipeline
from fetchers import (
    aijobs_fetcher,
    braintrust_fetcher,
    companies_fetcher,
    email_fetcher,
    facebook_public_fetcher,
    fbsearch_fetcher,
    hn_fetcher,
    jobboards_fetcher,
    jobicy_fetcher,
    linkedin_fetcher,
    reddit_fetcher,
    remotive_fetcher,
    secrettlv_fetcher,
    telegram_fetcher,
    weworkremotely_fetcher,
    xplace_fetcher,
)

log = logging.getLogger("main")

ERROR_THROTTLE_SECONDS = 6 * 3600  # at most one Telegram error alert per job per 6h


def setup_logging() -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s [%(name)s] %(message)s")
    file_h = logging.FileHandler(config.LOG_PATH, encoding="utf-8")
    file_h.setFormatter(fmt)
    console_h = logging.StreamHandler(sys.stdout)
    console_h.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=[file_h, console_h])
    logging.getLogger("httpx").setLevel(logging.WARNING)


# --- jobs --------------------------------------------------------------------

def job_reddit(conn) -> None:
    pipeline.ingest_many(conn, reddit_fetcher.fetch(), "reddit")


def job_reddit_search(conn) -> None:
    pipeline.ingest_many(conn, reddit_fetcher.fetch_search(), "reddit_search")


def job_linkedin(conn) -> None:
    pipeline.ingest_many(conn, linkedin_fetcher.fetch(conn), "linkedin")


def job_whatsapp(conn) -> None:
    """Daily: harvest WhatsApp invite links out of already-stored posts and
    validate them. Discovery only - these are groups for the user to JOIN by
    hand, never automated. Network *search* stays manual (--search)."""
    import discover_whatsapp_groups as wa

    found = wa.mine_db(conn)
    checked = wa.validate_pending(conn, cap=10)
    wa.rescore(conn)
    wa.notify_new(conn)
    log.info("whatsapp: %d new invite(s) mined, %d validated", found, len(checked))


def job_hn(conn) -> None:
    pipeline.ingest_many(conn, hn_fetcher.fetch(), "hn")


def job_email(conn) -> None:
    pipeline.ingest_many(conn, email_fetcher.fetch(conn), "email")


def job_facebook(conn) -> None:
    pipeline.ingest_many(conn, facebook_public_fetcher.fetch(conn), "facebook")


def job_fbsearch(conn) -> None:
    """Facebook group posts via the search index. Replaces the logged-out
    scraper, which is dead from every datacenter IP (measured: all surfaces
    redirect to login, 0 leads across three cloud runs). Touches no Facebook
    URL, so it carries no ban risk and no rate limit of its own."""
    pipeline.ingest_many(conn, fbsearch_fetcher.fetch(conn), "fbsearch")


def job_xplace(conn) -> None:
    pipeline.ingest_many(conn, xplace_fetcher.fetch(), "xplace")


def job_secrettlv(conn) -> None:
    pipeline.ingest_many(conn, secrettlv_fetcher.fetch(), "secrettlv")


def job_remotive(conn) -> None:
    pipeline.ingest_many(conn, remotive_fetcher.fetch(), "remotive")


def job_weworkremotely(conn) -> None:
    pipeline.ingest_many(conn, weworkremotely_fetcher.fetch(), "weworkremotely")


def job_jobboards(conn) -> None:
    pipeline.ingest_many(conn, jobboards_fetcher.fetch(), "jobboards")


def job_jobicy(conn) -> None:
    pipeline.ingest_many(conn, jobicy_fetcher.fetch(), "jobicy")


def job_braintrust(conn) -> None:
    pipeline.ingest_many(conn, braintrust_fetcher.fetch(), "braintrust")


def job_aijobs(conn) -> None:
    pipeline.ingest_many(conn, aijobs_fetcher.fetch(), "aijobs")


def job_companies(conn) -> None:
    pipeline.ingest_many(conn, companies_fetcher.fetch(), "companies")


def job_telegram(conn) -> None:
    pipeline.ingest_many(conn, telegram_fetcher.fetch(), "telegram")


def job_linkcheck(conn) -> None:
    """Verify the leads the user is about to act on are still live. Age alone is
    a poor proxy: boards pull postings early and community threads stay open
    for months."""
    import linkcheck
    linkcheck.verify(conn, limit=40, min_score=config.DIGEST_THRESHOLD)


def job_digest(conn) -> None:
    """Send the daily digest of borderline (6-7) leads once per day after DIGEST_HOUR."""
    today = datetime.now().strftime("%Y-%m-%d")
    if datetime.now().hour < config.DIGEST_HOUR:
        return
    if db.kv_get(conn, "last_digest_date") == today:
        return
    rows = db.digest_pending(conn)
    if rows:
        if notifier.send_digest(rows):
            for r in rows:
                db.set_status(conn, r["id"], "digested")
    db.kv_set(conn, "last_digest_date", today)
    log.info("digest: sent %d leads", len(rows))


JOBS = [
    # (name, interval seconds, function)
    ("email", 10 * 60, job_email),           # Facebook / Upwork / Wellfound / LinkedIn alerts
    ("reddit", 20 * 60, job_reddit),         # 13 subs x 8s spacing ~= 2 min/run
    ("reddit_search", 60 * 60, job_reddit_search),  # sitewide search, t=week window
    ("linkedin", 3 * 3600, job_linkedin),    # guest endpoint; self-cools 6h on a bot-wall
    ("hn", 60 * 60, job_hn),
    ("xplace", 2 * 3600, job_xplace),
    ("secrettlv", 2 * 3600, job_secrettlv),
    ("braintrust", 2 * 3600, job_braintrust),  # 100%-freelance marketplace
    ("aijobs", 2 * 3600, job_aijobs),          # dedicated AI/ML board
    ("companies", 6 * 3600, job_companies),    # curated AI/CV company boards
    ("telegram", 45 * 60, job_telegram),       # public channel previews
    ("weworkremotely", 2 * 3600, job_weworkremotely),
    ("jobboards", 3 * 3600, job_jobboards),    # arbeitnow + workingnomads + jobspresso
    ("jobicy", 4 * 3600, job_jobicy),          # remote AI/ML/data, has freelance/part-time flag
    ("remotive", 8 * 3600, job_remotive),      # rate-limited ~4/day, 24h-delayed
    ("fbsearch", 3 * 3600, job_fbsearch),    # post permalinks from the search index
    ("facebook", 8 * 3600, job_facebook),      # public groups; self-caps at 3 runs/day
    ("whatsapp", 24 * 3600, job_whatsapp),     # mine invite links out of stored posts
    ("linkcheck", 6 * 3600, job_linkcheck),   # drop leads whose posting died
    ("digest", 10 * 60, job_digest),
]


def run_job_safe(conn, name: str, fn) -> None:
    try:
        fn(conn)
    except Exception as e:
        log.exception("job %s failed: %s", name, e)
        # self-report to Telegram, throttled
        key = f"last_error_alert_{name}"
        last = float(db.kv_get(conn, key, "0") or 0)
        if time.time() - last > ERROR_THROTTLE_SECONDS:
            notifier.send_error(name, str(e))
            db.kv_set(conn, key, str(time.time()))


def run_forever() -> None:
    conn = db.connect()
    next_run = {name: 0.0 for name, _, _ in JOBS}
    log.info("lead-agent started (backend=%s, telegram=%s)",
             config.LLM_BACKEND,
             "on" if config.TELEGRAM_BOT_TOKEN else "OFF -> outbox.log")
    while True:
        now = time.time()
        for name, interval, fn in JOBS:
            if now >= next_run[name]:
                run_job_safe(conn, name, fn)
                next_run[name] = time.time() + interval
        time.sleep(30)


def run_once() -> None:
    conn = db.connect()
    for name, _, fn in JOBS:
        if name == "digest":
            continue
        log.info("--- running %s ---", name)
        run_job_safe(conn, name, fn)
    print_stats(conn)


def score_backlog(conn, limit: int) -> None:
    """Score stored-unscored leads (run this right after adding a Gemini key).

    Newest first. Telegram pushes fire only for score>=PUSH leads fetched in
    the last 5 days - older gigs are likely filled, so they go to the DB/exports
    without pinging your phone.
    """
    import json as _json
    from datetime import datetime, timedelta, timezone

    import scorer
    from models import Lead

    rows = conn.execute(
        "SELECT * FROM leads WHERE status='scored' AND score IS NULL "
        "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    if not rows:
        print("backlog empty - nothing to score")
        return
    print(f"scoring {len(rows)} leads (Gemini free tier, ~6.5s per lead; "
          f"ETA ~{len(rows) * 7 // 60} min). Ctrl+C safe - progress is saved per lead.")
    fresh_cutoff = datetime.now(timezone.utc) - timedelta(days=5)
    counts: dict[str, int] = {}
    for i, row in enumerate(rows, 1):
        lead = Lead(source=row["source"], url=row["url"], raw_text=row["raw_text"],
                    author=row["author"])
        try:
            score = scorer.score_lead(lead)
        except Exception as e:
            log.error("backlog scoring failed for %s: %s", row["id"], e)
            continue
        if score is None:
            print("no LLM backend configured - set GEMINI_API_KEY first")
            return
        fetched = None
        try:
            fetched = datetime.fromisoformat(row["fetched_at"])
        except (TypeError, ValueError):
            pass
        is_fresh = fetched is not None and fetched >= fresh_cutoff
        if score.score >= config.PUSH_THRESHOLD:
            db.save_score(conn, row["id"], score, "scored")
            if is_fresh:
                pitch = scorer.draft_pitch(lead) if config.PITCH_DRAFTS else None
                fresh_row = conn.execute("SELECT * FROM leads WHERE id=?", (row["id"],)).fetchone()
                if notifier.notify_lead(fresh_row, pitch=pitch):
                    db.set_status(conn, row["id"], "notified")
            bucket = "pushed" if is_fresh else "high_not_pushed"
        elif score.score >= config.DIGEST_THRESHOLD:
            db.save_score(conn, row["id"], score, "digest_pending")
            bucket = "digest_pending"
        else:
            db.save_score(conn, row["id"], score, "scored")
            bucket = "low"
        counts[bucket] = counts.get(bucket, 0) + 1
        if i % 25 == 0:
            print(f"  {i}/{len(rows)} done {counts}")
    print(f"backlog scored: {counts}")
    print("now run:  python main.py --export-html leads.html   (or --export-csv --min-score 7)")


def regate(conn) -> None:
    """One-time cleanup: re-run the (stricter) classifier over existing unscored
    candidates and re-bucket them. Safe to run repeatedly."""
    import prefilter
    from models import Lead

    # Also reconsider gated_out rows: widening the keyword gate (e.g. adding YOLO
    # and OpenCV in 2026-08) only helps future posts unless what it already
    # rejected gets a second look. Rows killed for reasons that cannot change
    # (stale, closed) are skipped - re-running those wastes an LLM call each.
    rows = conn.execute(
        "SELECT id, source, url, raw_text, posted_at FROM leads "
        "WHERE (status='scored' AND score IS NULL) OR status='partnership' "
        "   OR (status='gated_out' AND COALESCE(reasoning,'') NOT LIKE '%stale%' "
        "       AND COALESCE(reasoning,'') NOT LIKE '%closed%')"
    ).fetchall()
    counts: dict[str, int] = {}
    for r in rows:
        posted = None
        try:
            posted = datetime.fromisoformat(r["posted_at"]) if r["posted_at"] else None
        except (TypeError, ValueError):
            pass
        lead = Lead(source=r["source"], url=r["url"], raw_text=r["raw_text"],
                    posted_at=posted)   # the staleness gate needs this
        verdict = prefilter.classify(lead)
        counts[verdict] = counts.get(verdict, 0) + 1
        if verdict == "pass":
            if r["id"]:  # ensure it's back in the candidate pool
                conn.execute("UPDATE leads SET status='scored', reasoning=NULL WHERE id=?",
                             (r["id"],))
        elif verdict == "partnership":
            conn.execute("UPDATE leads SET status='partnership', "
                         "reasoning='gate: partnership' WHERE id=?", (r["id"],))
        else:
            conn.execute("UPDATE leads SET status='gated_out', reasoning=? WHERE id=?",
                         (f"gate: {verdict.removeprefix('gate_')}", r["id"]))
    conn.commit()
    print(f"re-classified {len(rows)} candidates:")
    for k in sorted(counts, key=counts.get, reverse=True):
        print(f"  {k:18} {counts[k]}")


def print_replies(conn) -> None:
    for status in ("pending", "failed", "sent"):
        rows = db.replies_by_status(conn, status)
        if not rows:
            continue
        print(f"\n=== {status} replies ({len(rows)}) ===")
        for r in rows:
            print(f"[{r['id']}] lead {r['lead_id']} ({r['source']}, score {r['score']})")
            print(f"    {(r['message'] or '')[:200]}")
            if r["error"]:
                print(f"    ERROR: {r['error']}")
            print(f"    {r['url']}")


def approve_replies(conn, which: str) -> None:
    import replier
    if which.strip().lower() == "all":
        rows = db.replies_by_status(conn, "pending")
        ids = [r["id"] for r in rows]
    else:
        ids = [int(x) for x in which.replace(",", " ").split()]
    if not ids:
        print("no pending replies")
        return
    for rid in ids:
        db.set_reply_status(conn, rid, "approved")
        ok, err = replier.send_reply(conn, rid)
        print(f"reply {rid}: {'SENT' if ok else 'FAILED - ' + err}")


def reply_test(conn, lead_id: int) -> None:
    """Draft (but don't queue/send) a reply for one lead - dry run."""
    import replier
    row = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    if not row:
        print(f"lead {lead_id} not found")
        return
    ch = replier.channel_for(row["source"])
    print(f"lead {lead_id} | source {row['source']} | channel: {ch or 'UNSUPPORTED'}")
    d = replier.draft(row)
    if d is None:
        print("no LLM backend configured (set GEMINI_API_KEY)")
        return
    print(f"should_reply: {d.get('should_reply')} | reason: {d.get('reason')}")
    if d.get("message"):
        print(f"--- draft ---\n{d['message']}")


def export_csv(conn, path: str, min_score: int, include_partnerships: bool = False) -> int:
    """Write leads to a UTF-8-BOM CSV (BOM so Excel renders Hebrew correctly)."""
    import csv

    cols = ["id", "score", "source", "category", "work_type", "summary",
            "budget", "red_flags", "status", "posted_at", "fetched_at",
            "url", "author", "lang", "raw_text"]
    excluded = "('handled', 'partnership')" if not include_partnerships else "('handled')"
    if min_score > 0:
        rows = conn.execute(
            f"SELECT * FROM leads WHERE score >= ? AND status NOT IN {excluded} "
            "ORDER BY score DESC, id DESC", (min_score,),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT * FROM leads WHERE status NOT IN {excluded} ORDER BY id DESC"
        ).fetchall()

    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([r[c] if c in r.keys() else "" for c in cols])
    return len(rows)


def export_html(conn, path: str, min_score: int, include_partnerships: bool = False) -> int:
    """Write a self-contained, filterable HTML dashboard of the leads."""
    import html as h
    import json as j

    excluded = "('gated_out', 'handled', 'partnership')" if not include_partnerships \
        else "('gated_out', 'handled')"
    if min_score > 0:
        rows = conn.execute(
            f"SELECT * FROM leads WHERE score >= ? AND status NOT IN {excluded} "
            "ORDER BY score DESC, id DESC", (min_score,)).fetchall()
    else:
        rows = conn.execute(
            f"SELECT * FROM leads WHERE status NOT IN {excluded} "
            "ORDER BY score IS NULL, score DESC, id DESC").fetchall()

    data = [{
        "id": r["id"], "score": r["score"], "source": r["source"],
        "category": r["category"] or "", "work_type": r["work_type"] or "",
        "summary": r["summary"] or "", "budget": r["budget"] or "",
        "url": r["url"], "posted": (r["posted_at"] or "")[:10],
        "text": (r["raw_text"] or "")[:600],
    } for r in rows]

    page = """<!DOCTYPE html><html dir="auto"><head><meta charset="utf-8">
<title>AgentLead - leads</title><style>
body{font-family:Segoe UI,Arial,sans-serif;margin:16px;background:#fafafa}
h1{font-size:20px} .bar{margin:10px 0}
input,select,button{padding:6px;font-size:14px;margin-right:8px}
table{border-collapse:collapse;width:100%;background:#fff}
th,td{border:1px solid #ddd;padding:8px;text-align:start;vertical-align:top;font-size:13px}
th{background:#2d3748;color:#fff;position:sticky;top:0}
tr:nth-child(even){background:#f4f6f8}
.s9,.s10{background:#c6f6d5!important}.s8{background:#e6ffed!important}
tr.done td{opacity:.45}
.badge{display:inline-block;padding:1px 7px;border-radius:9px;background:#2b6cb0;color:#fff;font-weight:700}
.txt{color:#555;max-width:600px}.src{white-space:nowrap}
.note{width:150px;font-size:12px;padding:3px}
a{color:#2b6cb0}</style></head><body>
<h1>AgentLead - lead browser & outreach tracker</h1>
<div class="bar">
 <input id="q" placeholder="filter text..." size="32">
 <select id="minscore"><option value="">any score</option>
  <option>6</option><option>7</option><option>8</option><option>9</option></select>
 <select id="src"><option value="">all sources</option></select>
 <select id="ct"><option value="">all</option><option value="todo">not contacted</option>
  <option value="done">contacted</option></select>
 <span id="count"></span></div>
<p style="color:#777;font-size:12px">✔ = contacted (saved in this browser via localStorage, survives re-exports). Notes save as you type.</p>
<table id="t"><thead><tr><th>✔</th><th>score</th><th>source</th><th>category</th><th>type</th>
<th>summary / text</th><th>budget</th><th>posted</th><th>link</th><th>my note</th></tr></thead>
<tbody></tbody></table>
<script>
const DATA = __DATA__;
const LS_KEY='agentlead_outreach';
let state={};try{state=JSON.parse(localStorage.getItem(LS_KEY)||'{}')}catch(e){}
function save(){localStorage.setItem(LS_KEY,JSON.stringify(state))}
const tb = document.querySelector('#t tbody');
const srcSel = document.getElementById('src');
[...new Set(DATA.map(d=>d.source.split('/')[0]))].sort().forEach(s=>{
  const o=document.createElement('option');o.textContent=s;srcSel.appendChild(o);});
function esc(x){const d=document.createElement('div');d.textContent=x||'';return d.innerHTML}
function render(){
  const q=document.getElementById('q').value.toLowerCase();
  const ms=document.getElementById('minscore').value;
  const src=srcSel.value;
  const ct=document.getElementById('ct').value;
  let n=0; tb.innerHTML='';
  for(const d of DATA){
    const st=state[d.id]||{};
    if(q && !(d.text+' '+d.summary+' '+d.source).toLowerCase().includes(q))continue;
    if(ms && (d.score==null || d.score < +ms))continue;
    if(src && d.source.split('/')[0]!==src)continue;
    if(ct==='todo' && st.done)continue;
    if(ct==='done' && !st.done)continue;
    n++;
    const tr=document.createElement('tr');
    tr.className=(d.score>=8?'s'+d.score+' ':'')+(st.done?'done':'');
    tr.innerHTML=`<td><input type=checkbox data-id="${d.id}" ${st.done?'checked':''}></td>
<td>${d.score!=null?'<span class=badge>'+d.score+'</span>':''}</td>
<td class=src>${esc(d.source)}</td><td>${esc(d.category)}</td><td>${esc(d.work_type)}</td>
<td class=txt dir=auto><b>${esc(d.summary)}</b>${d.summary?'<br>':''}${esc(d.text)}</td>
<td>${esc(d.budget)}</td><td>${esc(d.posted)}</td>
<td><a href="${d.url}" target=_blank>open</a></td>
<td><input class=note data-id="${d.id}" value="${esc(st.note||'')}" placeholder="..."></td>`;
    tb.appendChild(tr);
  }
  document.getElementById('count').textContent = n+' / '+DATA.length+' leads';
}
tb.addEventListener('change',e=>{
  const id=e.target.dataset.id; if(!id)return;
  state[id]=state[id]||{};
  if(e.target.type==='checkbox'){state[id].done=e.target.checked;save();render();}
});
tb.addEventListener('input',e=>{
  if(!e.target.classList.contains('note'))return;
  const id=e.target.dataset.id; state[id]=state[id]||{}; state[id].note=e.target.value; save();
});
['q','minscore','src','ct'].forEach(id=>document.getElementById(id).addEventListener('input',render));
render();
</script></body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(page.replace("__DATA__", j.dumps(data, ensure_ascii=False)))
    return len(rows)


def print_stats(conn) -> None:
    print("\n=== leads by status ===")
    for row in conn.execute(
        "SELECT status, COUNT(*) n FROM leads GROUP BY status ORDER BY n DESC"
    ):
        print(f"  {row['status']:16} {row['n']}")
    print("=== leads by source ===")
    for row in conn.execute(
        "SELECT source, COUNT(*) n FROM leads GROUP BY source ORDER BY n DESC"
    ):
        print(f"  {row['source']:20} {row['n']}")
    print("=== top scored ===")
    for row in conn.execute(
        "SELECT score, source, substr(replace(summary,char(10),' '),1,80) s, url "
        "FROM leads WHERE score IS NOT NULL ORDER BY score DESC, id DESC LIMIT 10"
    ):
        try:
            print(f"  [{row['score']}] {row['source']}: {row['s']}\n      {row['url']}")
        except UnicodeEncodeError:
            print(f"  [{row['score']}] {row['source']}: <non-ascii summary>\n      {row['url']}")


def main() -> None:
    setup_logging()
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--test-telegram", action="store_true")
    ap.add_argument("--score-test", metavar="TEXT")
    ap.add_argument("--digest-now", action="store_true")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--export-csv", nargs="?", const="leads.csv", metavar="PATH",
                    help="export leads to CSV (default leads.csv)")
    ap.add_argument("--export-html", nargs="?", const="leads.html", metavar="PATH",
                    help="export a filterable HTML lead browser (default leads.html)")
    ap.add_argument("--min-score", type=int, default=0,
                    help="with --export-csv/--export-html: only leads scoring >= N")
    ap.add_argument("--score-backlog", nargs="?", const=300, type=int, metavar="N",
                    help="score up to N stored-unscored leads (run after adding a Gemini key)")
    ap.add_argument("--replies", action="store_true",
                    help="list pending/failed/sent auto-replies")
    ap.add_argument("--approve-reply", metavar="IDS|all",
                    help="approve+send drafted replies, e.g. --approve-reply 3 or 'all'")
    ap.add_argument("--reply-test", type=int, metavar="LEAD_ID",
                    help="dry-run: draft a reply for one lead, print it, send nothing")
    ap.add_argument("--verify-links", nargs="?", const=60, type=int, metavar="N",
                    help="check the top N leads' URLs and gate the dead ones")
    ap.add_argument("--regate", action="store_true",
                    help="re-run the (stricter) keyword classifier over stored candidates")
    ap.add_argument("--include-partnerships", action="store_true",
                    help="with exports: include the low-priority partnership bucket")
    args = ap.parse_args()

    if args.test_telegram:
        ok = notifier.send_test()
        print("Telegram:", "OK" if ok else "not configured / failed (see agent.log)")
        return
    if args.score_test:
        import scorer
        from models import Lead
        s = scorer.score_lead(Lead(source="test", url="https://example.com", raw_text=args.score_test))
        print(s if s else "No LLM backend configured (set GEMINI_API_KEY or LLM_BACKEND=ollama)")
        return
    if args.digest_now:
        conn = db.connect()
        rows = db.digest_pending(conn)
        if notifier.send_digest(rows):
            for r in rows:
                db.set_status(conn, r["id"], "digested")
        print(f"digest sent: {len(rows)} leads")
        return
    if args.stats:
        print_stats(db.connect())
        return
    if args.export_csv:
        n = export_csv(db.connect(), args.export_csv, args.min_score,
                       args.include_partnerships)
        print(f"exported {n} leads -> {args.export_csv}")
        return
    if args.export_html:
        n = export_html(db.connect(), args.export_html, args.min_score,
                        args.include_partnerships)
        print(f"exported {n} leads -> {args.export_html}")
        return
    if args.verify_links is not None:
        import linkcheck
        print(linkcheck.verify(db.connect(), limit=args.verify_links))
        return
    if args.regate:
        regate(db.connect())
        return
    if args.score_backlog is not None:
        score_backlog(db.connect(), args.score_backlog)
        return
    if args.replies:
        print_replies(db.connect())
        return
    if args.approve_reply:
        approve_replies(db.connect(), args.approve_reply)
        return
    if args.reply_test:
        reply_test(db.connect(), args.reply_test)
        return
    if args.once:
        run_once()
        return
    run_forever()


if __name__ == "__main__":
    main()
