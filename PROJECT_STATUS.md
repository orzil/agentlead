# AgentLead — Project Status & Session Log

*Last updated: 2026-07-16 (end of session)*

A zero-cost lead-generation agent that monitors freelance/contract opportunities
across the web, filters them to Or's niches (computer vision, OCR, image
processing, ML, algorithms, data visualization, AI automation, AI web/apps),
and will score + push + auto-reply once API keys are added.

---

## What was built (2026-07-04 → 2026-07-12)

### Sources (17 families, all free)
| Channel | Status |
|---|---|
| **Facebook public groups** — logged-out Playwright scraper | 🟢 **19 groups** (16 IL, 3 US); full "See more" expansion, stale-post filter, throttle auto-backoff, 3 runs/day cap |
| Facebook private groups | 13 identified → covered only if user joins + enables email notifications |
| **Freelancer.com** public API | 🟢 running — **⚠️ ON TRIAL: user verdict = too many bids, low rates. Re-evaluate ~2026-07-15; drop or demote if no wins** |
| Braintrust API | 🟢 100%-freelance marketplace, hourly USD rates — best rate quality |
| aijobs.net (HTML + CSRF POST filters: Computer-Vision + Middle-East views) | 🟢 |
| Telegram public channels (t.me/s/) | 🟢 11 channels (IL + global) |
| Reddit (**13** subs via RSS, no key needed) + **sitewide `search.rss`** (`title:(hiring OR task)` queries) | 🟢 |
| **LinkedIn** — job-alert emails (robust, needs 5-min user setup) + logged-out `jobs-guest` scraper (best-effort; guest filters unreliable) | 🟡 email path awaiting user setup |
| **WhatsApp** — discovery only (`discover_whatsapp_groups.py`); user joins by hand, never automated | 🟢 23 live groups found; 2–3 worth joining |
| HN "Who is hiring?" + revived "Freelancer? Seeking freelancer?" | 🟢 |
| X-Place, Secret Tel Aviv | 🟢 |
| RemoteOK, Remotive, We Work Remotely, Arbeitnow, Working Nomads, Himalayas, Jobspresso | 🟢 |
| Company career boards (Greenhouse/Comeet/Workable/Ashby — Israeli CV cos + AI cos) | 🟢 14 boards |
| Upwork/Wellfound | via saved-search email alerts (needs Gmail setup) |

### Filtering (precision gates, added after noise complaints)
Regex classifier runs before any LLM: kills **full-time** posts (incl. 35+ hrs/wk
— user rule), **job-seekers**, **unpaid community/volunteer/data-collection asks**,
**courses/admin noise**, **design/typing spam**; routes **equity/co-founder asks**
to a low-priority `partnership` bucket. Backlog cleaned 1,306 → ~670 candidates.
Gemini scorer rubric updated to match (FT=1-3, unpaid=1-2, equity-only cap 4).

### Outreach machinery (built, awaiting credentials)
- **Auto-reply**: Reddit DM/comment + Freelancer bids; LLM decides per
  `REPLY_DIRECTION`; approve-mode default, daily cap, one reply per lead.
- **Pitch drafts** in every Telegram push (score ≥8).
- **`leads.html`** dashboard: filters + contacted-checkbox + notes (localStorage).
- CLI: `--once`, `--score-backlog`, `--regate`, `--export-html/csv`, `--replies`,
  `--approve-reply`, `--reply-test`, `--stats`.

### Outreach done so far
- 20 CV-focused leads tabled → user messaged the relevant ones → marked `handled`.
- Decision tables delivered: Israeli leads, low-bid leads, fresh projects,
  high-pay part-time. Reddit DM draft ready for the UK AI-automation agency.

---

## User preferences (encoded in the system)
1. **Paid freelance / contract / part-time / hourly only.** No full-time (35+ hrs/wk counts as full-time). No unpaid/volunteer/community asks. Partnerships = separate bucket, browsable on demand.
0. **Based in Israel — remote or on-site-in-Israel only.** Roles locked to another country/region with no remote-from-Israel option (US-only, requires US work authorization/citizenship, LATAM-only, UK-only, on-site abroad) are NOT accessible → gated out (`gate_location`) and the LLM scorer down-ranks them to 1-3 with red_flag "location restricted". Israel / EMEA / worldwide / remote-anywhere are fine. (Added 2026-07-14 after the US-only Braintrust $175/hr false lead.)
2. **Low competition matters** — 20+ bids ≈ waste of time. Facebook/Telegram/Reddit DMs > marketplace bid wars.
3. **Freelancer.com skepticism** — bid floods + low budgets. Trial until ~July 15.
4. Zero cost forever. Never automate the user's Facebook account (logged-out scraping only).

## To activate full autopilot (~20 min of user's time, all free)
1. **Gemini key** (aistudio.google.com) → `GEMINI_API_KEY` → run `python -X utf8 main.py --score-backlog`
2. **Telegram bot** (@BotFather) → instant pushes with pitch drafts
3. **Gmail app password** → email pipeline (Upwork/Wellfound + private FB groups)
4. **Join 6 private FB groups** (AI Automation Experts, SaaS Founders, AI/ML JOBS, London Startups…) + enable "All posts" notifications
5. *(optional)* Reddit username/password → auto-DM; Freelancer OAuth token → auto-bids

## Session 2026-07-14 — Facebook IL/US/UK scan
- **Probed the 4 UK groups** → 3 PUBLIC (flipped to `public: True` in config):
  `UK.Software.Developers`, `ukstartupsgroup`, `devitjobsgroup`; `freelanceuk` = private.
  Public scraper pool is now **22 groups (16 IL, 3 US, 3 UK)**.
- **Scanned 17/22** across 3 runs (FB IP-throttle wall stopped each run early;
  ~7 min cooldown between runs cleared it). Unreached (next session): IL
  `279218118861800`, `webJobsIsrael`, `DevJobsJLM`, `aisrael`, `676381365752971`.
- **No Gemini key configured**, so candidates stored unscored; scored by hand this pass.
- **Yield — genuine freelance fits (IL app/dev groups; US+UK were all noise):**
  - lead 3324 — diary-app MVP (RN/Flutter + Firebase + AI text-summary API, 3–4 wk), fresh
  - lead 3329 — startup wants freelance dev, remote hourly, direct-to-dev (low-comp), fresh
  - lead 3259 — automation freelancer @100₪/hr — genuine but stale (Mar 6), low rate
  - borderline: 3323 (beauty-app co-founder = equity/partnership), 3313 (mktg+automation, weak)
- US/US-facing + UK groups yielded **0 fits**: dominated by service ads, course/affiliate
  promos, educational engagement-bait, funding requests, and spam. Low-signal for Or's niche.

## Session 2026-07-14 (cont.) — Telegram check
- **`t.me` is DNS-blocked on this network** (getaddrinfo fails; telegram.org resolves).
  Patched `telegram_fetcher.py` to detect this and resolve `t.me` via DNS-over-HTTPS
  (Google/Cloudflare) + a `getaddrinfo` shim — the daily loop's Telegram channels now work.
- **`t.me/freelancersIL` is a GROUP, not a channel** → no logged-out `t.me/s/` preview,
  so the scraper can't read it (same limitation as private FB groups). Would need to
  join + Telegram API, or forward its posts to the email pipeline.
- Probed ~40 candidate IL/US/UK handles; only `python_israel` (coding tips),
  `digital_freelancers` (RU freelancers self-advertising), `remotejobs`, `remoteok`,
  `ukjobs` served previews — none are good freelance-client sources.
- Ran the 11 configured channels (234 posts) → **0 genuine freelance leads**: all
  job-seekers, full-time/relocation roles (mostly RU market), or course/webinar ads.
  Telegram is structurally weak for Or's freelance niche, like FB groups.

## Session 2026-07-14 (cont.) — creative source expansion
Scanned new free sources for freelance/contract/part-time only. Findings:
- **A.Team** (vetted invite-only senior-AI network) — live listing "Senior Independent
  AI Engineer / Architect", **contract, remote, explicitly Americas/Europe/ISRAEL**.
  Real production work (clients: Lyft, Google X, D-ID, Sightful). → **Or should apply to
  join the network**, not just this listing. Surfaced via Remotive domain search (already covered).
- **Jobicy** — NEW fetcher added (`fetchers/jobicy_fetcher.py`, wired into main.py JOBS,
  added to DOMAIN_REQUIRED_SOURCES). 142 jobs → gate kills 136 FT, surfaces part-time AI roles.
- **Mindrift / TripleTen** — project-based AI gig platforms (part-time SME / eval work); sign-up destinations, lower fit.
- **Talent networks to JOIN (proactive, push work to Or)**: A.Team, Braintrust, Toptal,
  Gun.io, Contra, Mindrift, Wellfound. Higher ROI than more scraping.
- **Tried & weak**: GitHub bounty search = spam-polluted (bot digests, fake-token bounties);
  genuine OCR/CV issues exist but are mostly *unpaid* OSS (portfolio value only). The Muse = all FT.
  Algora public API endpoint not found (real cash OSS bounties — worth a proper integration later).

## Best freelance leads so far (from the API/RSS broad scan, not FB/Telegram)
- HN Namecoach/Euphonia — Founding Voice AI Engineer, part-time/contract, remote, $30-120/hr
- Braintrust job 17549 — Applied AI Consultant, freelance $175/hr, 20h/wk (⚠️ "US only")
- Freelancer "Runway FOD AI Detection" — real CV project (⚠️ $250-750, 62 bids)

## Session 2026-07-16 — LinkedIn + Reddit expansion + WhatsApp discovery
Three new capabilities, all free-tier, no new dependencies.

**LinkedIn (new, 2 paths, source root `linkedin`)**
- `fetchers/linkedin_fetcher.py` — logged-out `jobs-guest` search + detail endpoints.
  9 queries/run (6 worldwide-remote + 3 Israel), ≤15 detail fetches/run, 3h cadence.
- **Key finding: LinkedIn's guest filters are unreliable AND non-deterministic.** `f_JT`/`f_WT`
  work sometimes (`f_JT=C` vs `f_JT=F` return disjoint sets) but the same query re-run minutes
  later silently ignores them — one probe of `f_JT=P,C,T&f_WT=2&f_TPR=r604800` returned *exactly*
  the 10 jobs an explicit full-time query returned. So the "Employment type" criteria line is
  folded into `raw_text` and `FT_RE` does the real filtering. First live run: 18 cards → 4
  detail-fetched → **all 4 correctly gated `gate_full_time`**. Expect low yield, correct output.
- URLs canonicalised to `linkedin.com/jobs/view/<id>` — cards use country subdomains + slugs
  (`at.linkedin.com/jobs/view/<slug>-<id>`), emails use `/comm/` links; canonical form is the
  shared dedup key across both paths.
- **LinkedIn job-alert emails** = the robust half (LinkedIn can bot-wall the scraper but not its
  own email). Needs ~5 min of user setup — see README §5. `EMAIL_SOURCES["linkedin.com"]`.
- Fixed a latent bug in `email_fetcher._parse_job_alert` that would have bitten LinkedIn: the URL
  was marked seen *before* the anchor-length check, so a job's logo anchor swallowed its title
  anchor and dropped the job. Also benefits Upwork/Wellfound.

**Reddit expansion**
- SUBREDDITS 6 → 13: +PythonJobs (loose gate); +hiring, AI_Agents, n8n, automation, deeplearning,
  LocalLLaMA (INTENT_REQUIRED — full-string keyed, which is how per-sub gating works, since
  `DOMAIN_REQUIRED_SOURCES` is root-keyed and can't distinguish `r/x` from `r/y`). All 7 verified
  live. Interval 15 → 20 min (13 subs × 8s ≈ 2 min/run).
- **New: sitewide `search.rss`** (`fetch_search()`, source `r/search`, hourly, `t=week`).
  Plain keyword queries were a noise generator — **measured 14/20 passed the gate, 0 real leads**
  (career-advice threads, seeker self-promos, SEO listicles). Anchoring queries on
  `title:(hiring OR task)` surfaced real gigs instead (`[Hiring] AI camera app $8k–$15k`,
  `Cocos2d-x $50–120/hr contract`). `search.rss` also mixes *subreddit* hits with post hits →
  `_parse_feed` keeps only `/comments/` permalinks. `t=week` + URL dedup ⇒ each post scored once,
  so hourly polling is nearly free.
- **Strengthened `SEEKER_RE`** (helps every source): caught seekers were slipping past by
  inserting adjectives — "Looking for **Full-time & Freelance** Opportunities", "Open to
  **Freelance & Part-Time** Opportunities", "[Hiring Me]", "I need clients", "available for
  freelance work". Regression-tested: 5/5 seekers gated, 4/4 real leads still pass.

**WhatsApp discovery (`discover_whatsapp_groups.py`, new)**
- Discovery only, **never automated** — no logged-out read surface exists and WhatsApp Web
  automation risks the user's personal number. Output is a ranked joinable list; user joins by hand.
- Surfaces: `mine_db` (invite links inside already-fetched posts — zero network), `search_reddit`
  (keyless `search.rss`, the reliable one), `search_ddg` (captcha-detects and skips).
- Validation verified live: live invite → `og:title` = group name; revoked → HTTP 200 with
  **empty** `og:title`.
- **First run yield: 40 invite codes** → 23 live, 2 revoked, 15 queued behind the per-run cap
  (35 Reddit search, 4 mined from stored Telegram/FB posts, 1 DDG — DDG was only partly walled
  from this IP).
- **Surface quality (measured, differs from expectation):** *mining the DB was the best surface* —
  it produced the single genuinely useful hit, **`GCV - משרות פיתוח לבעלי ניסיון`** (Israeli
  dev-jobs group), with zero network calls. *Reddit search was high-volume but low-signal*:
  dominated by Indian student-cohort/internship groups ("IIT Guwahati M.Tech Data Science 2026",
  "Ediglobe Internship") that match the domain words but never carry client work — three of them
  initially scored high enough to trigger a Telegram ping. Added `WA_NOISE_RE` (cohort/course/
  internship patterns → relevance 0): now only 3 groups qualify to notify (2 IL jobs groups +
  "AI Jobs 26'"). **Implication: the daily mine-the-DB job is the valuable half; `--search` is a
  monthly-at-most manual chore.**
- New `whatsapp_groups` table + daily `whatsapp` job (mine + validate 10 + rescore + ping).
  Network *search* stays manual (`--search`). `rescore()` re-applies the keyword scoring on every
  run (free, no network), so tuning the regexes retroactively fixes the whole table.
- Fixed before it shipped: `notify_new` originally used a global "last notified" timestamp, which
  would have silently *never* notified any group validated on a later run than the one that found
  it (i.e. most of them, given the cap). Now a per-row `notified` flag + a small idempotent
  `_migrate()` in `db.connect()` (the first migration this project has needed).

**First full `--once` run with all 3 new capabilities (2026-07-16 16:48–17:09)**
- 166 new gate-passed candidates. **58 (35%) came from the new sources**: r/search 22, linkedin 12,
  r/AI_Agents 8, r/deeplearning 6, r/PythonJobs 5, r/n8n 4, r/automation 1. Expanded Reddit alone
  produced 37 candidates from 254 posts.
- Dedup confirmed working across runs: reddit_search 58/66 duplicates, linkedin 6 dupes via the
  canonical URL (scraper ↔ earlier run).
- **Reddit rate-limits hard when hammered** — the 13-sub pass took 12 min today (vs ~2 min
  expected) because testing had burned the budget. The 20-min interval still covers it, and the
  20s/40s backoff absorbed every 429 without losing a sub. Watch it; free PRAW creds are the
  escape hatch if it persists.
- **Fixed a real location-gate gap found in the results**: `LOCATION_BLOCK_RE` required "must be
  **a** US citizen", so US staffing ads phrased as an eligibility list — "( Must be US Citizen or
  Green Card )", "USC/GC only" — sailed through (lead 4065, an on-site St Louis role). Added the
  green-card/USC-GC forms; regression-tested that remote-worldwide/EMEA/Israel posts still pass.
  `--regate` over the backlog reclassified 1 existing lead to `gate_location`.
- **Observation, not fixed:** `hn/freelancer` is **19/20 "SEEKING WORK"** — i.e. competitors
  advertising themselves, not clients hiring. `SEEKER_RE` catches them via the thread's own
  marker; one post (4230) omitted the marker and slipped through. If that source keeps yielding
  ~0 clients, consider requiring "SEEKING FREELANCER" for `hn/freelancer` — that would gate the
  whole source today, which is arguably correct.

**Known weakness (pre-existing, now more visible):** `STRONG_DOMAIN_RE` includes bare `algorithm`,
so "the YouTube algorithm" rescues video-editing spam from `SPAM_RE`. Cross-posted spam collapses
via fuzzy dedup and the scorer rates it 1–2, so it costs ~1 Gemini call. Left alone — narrowing
`algorithm` risks losing real algorithm gigs (a core niche).

## Open items
- **User action (5 min, unlocks the reliable half of LinkedIn):** create the LinkedIn saved-search
  job alerts → README §5. Until then only the best-effort guest scraper runs.
- **User action:** review `whatsapp_groups.md` and join the 2–3 ranked groups (top hit is the
  Israeli dev-jobs group). Then re-run `--write` to refresh, or `--joined <code>` to mark them.
- 15 WhatsApp invites still `pending` (behind the per-run cap) — the daily job drains 10/day, or
  run `discover_whatsapp_groups.py --cap 25` once to clear them.
- Watch LinkedIn yield for a few days: guest filters are unreliable, so most of each run gates out
  as full-time. If yield stays ~0 while the email alerts deliver, demote the scraper to a longer
  interval (or drop it) and keep the email path.
- 18 FB groups still `public=None` (throttle allows ~9/session;
  run `python -X utf8 probe_fb_groups.py --write` on a fresh day BEFORE any scan)
- 5 IL public groups unreached in the 2026-07-14 scan (listed above) — scrape next fresh day
- Freelancer.com go/no-go decision (~July 15) — **now overdue**
- Idea parked: ingest Google-indexed FB post snippets (`site:facebook.com/groups/<slug>`) for public groups the scraper can't render
- Idea parked: local Ollama scoring if the user prefers not to use Gemini
- Idea parked: Reddit subs evaluated and rejected — r/slavelabour (low pay), r/INAT (unpaid
  revshare), r/freelance (bans job posts), r/WorkOnline (non-tech microtasks), r/remotework
  (articles); r/jobbit + r/gameDevClassifieds looked low-fit but were never measured

## Daily operation
```
run.bat                      # or: python -X utf8 main.py    (scheduler loop)
python -X utf8 main.py --export-html leads.html   # refresh the lead browser
python -X utf8 discover_whatsapp_groups.py --write   # refresh the joinable-groups table
```
DB: `leads.db` (~3,950 leads). Logs: `agent.log`. 20 scheduler jobs.
