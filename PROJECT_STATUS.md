# AgentLead — Project Status & Session Log

*Last updated: 2026-10-23*

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

## Session 2026-08-06 — went live: keys, cloud deploy, FB discovery, Easy Apply

**The agent had been dead for 11 days** (last run 2026-07-26) and was both blind and mute:
no Gemini key, no Telegram chat id. Both now configured and verified end-to-end.

**Live now**
- **Telegram**: chat id configured in `.env` (gitignored), `--test-telegram` delivered.
- **Gemini**: key works, 50 models, `gemini-flash-latest` selected; sample Hebrew-OCR gig scored 10/10.
- **Cloud**: repo `orzil/agentlead` (private), 3 secrets set, both workflows registered and running.
  `.gitignore` widened to `*.csv` + `rc.txt` — those held scraped posts with real posters' names.

**Freelancer.com dropped** (decision was 3 weeks overdue). Fetcher deleted, auto-bid path removed
from `replier.py`, config cleaned, `SUPPORTED` now Reddit-only. **482 unscored Freelancer leads
retired** — they were 35% of the backlog and would have eaten a third of the daily Gemini quota on
a dead source. Backlog 1,380 → 898.

**New: `discover_fb_groups.py`** (mirrors `discover_whatsapp_groups.py`; new `facebook_groups`
table). Public groups graduate into `FACEBOOK_GROUPS`; private ones become a ranked join list
(`facebook_groups.md`, **14 private groups**) + a Telegram ping. The agent never sends a join
request. New weekly workflow `.github/workflows/fbgroups.yml` runs discovery **and** probing in the
cloud — decided after measuring that both surfaces wall the home IP.

**LinkedIn Easy Apply pass** — `f_AL=true`, source label `linkedin/easyapply`, `⚡ Easy Apply` in
the push, sorted after Israel in the detail-fetch priority. 9 → 17 queries/run.

**Two blockers hit and fixed late in the session**
- **GitHub refused runners for the private repo** — `"The job was not acquired by Runner of type
  hosted even after multiple attempts"` after 15 min. Not a queue delay: private-repo Actions need
  free minutes available on the account. **Repo flipped to public** (user's call) and a run picked
  up a runner within seconds. Before flipping, git history was scanned for secrets — the Telegram
  chat id had leaked into this file, so it was purged with `filter-branch` and force-pushed. `.env`,
  `leads.db`, `*.csv`, `*.log`, `rc.txt` were all confirmed absent from history.
- **Gemini free tier is far smaller than assumed.** The key died after **~20 scoring calls** with
  `GenerateRequestsPerDayPerProjectPerModel-FreeTier`, and then *every* model 429'd — including ones
  never called — so the daily cap behaves project-wide. `scorer.py` had claimed ~1,500/day.
  Two fixes: (1) a per-day 429 now short-circuits instead of retrying 3× with 20s/40s backoff
  (~70s wasted per lead, measured 12 cycles); (2) **hybrid scoring** — Gemini first for judgement,
  then automatic fallback to **local Ollama** (`qwen2.5:7b` on the RTX 4060), which has no quota.
  The fallback self-disables after one connection error so it no-ops on the Actions runner.
  Verified: a Hebrew CV post scored 8/10 in 8.8s locally, budget + work_type parsed correctly.
  Also dropped `gemini-2.5-flash` (now closed to new users) from the preference list.

## Session 2026-08-10/11 — speed, feedback, and the first accuracy number

**Speed.** `PUSH_THRESHOLD` 8 → **6**: at 8 a score-7 never reached the phone, and
the $100–150/hr Tel Aviv CV contract sat waiting for a digest. Polls tightened
(email 5 min, reddit 10, fbsearch 45, cloud_sync 20). The cloud now **scores and
pushes directly** — `OPENROUTER_API_KEY` reached its secrets, removing the ~2h
wait for `cloud_sync`.

**Feedback loop.** One-word Telegram replies (`good`/`fulltime`/`old`/`lowpay`/…,
plus `less`/`more` to retune volume) are recorded against the lead and appended
to `eval_cases.json`. `notifier._send_raw` returns a message_id now; the
`lead_messages` table maps replies back. Every accuracy fix until now came from
Or catching something and explaining it in chat, then being forgotten.

**`test_gate.py` — 15/15.** Every lead he rejected, plus the YOLO POC he liked,
which must still pass.

**Gate audit — the headline result.** 2,271 recent rejections re-scored blind:
`full_time` **0.0%** false negatives over 1,190 leads, `offtopic` **2.0%**,
everything else 0–4%. The gate is accurate; **`offtopic` is the only real
over-killer**, which matches it having missed YOLO/OpenCV until 2026-08-09.
**14 leads resurrected**, visible ≥6 went 15 → 29. Best recovery: an 8/10
EU/Ireland GenAI role killed as offtopic.

**Also fixed:** LinkedIn-alert enrichment crashed the whole email job with a
missing `timezone` import (the channel was dead for a day); X-Place moved its
endpoint under `/il/`; secrettlv's WAF 403s now skip the run instead of paging;
pitches rewritten (short, question-ending, Hebrew-or-English only, never an
invented credential) after the model emitted its own checklist to Or.

**Open for next session:** Reddit reply credentials (built, guarded, idle);
WhatsApp second number (built, dormant); `offtopic` keyword widening per the
audit; 🔔 All posts on the newly joined Facebook groups.

## Session 2026-08-13 — the cloud pass was being killed mid-run

**The finding: 2 of the last 3 scheduled cloud runs were cancelled at exactly
30:00** — `timeout-minutes: 30`, not a queue problem. `run_once` walks `JOBS`
in order, and on a GitHub IP the front of that list is far more expensive than
it is locally:

| job | cloud cost | why |
|---|---|---|
| `email` | ~2 min | |
| `reddit` | **13–17 min** | Reddit 429s nearly every sub from a datacenter IP, so the 20s/40s backoff fires ~11 of 13 times |
| `reddit_search` | 2–5 min | same |
| `linkedin` | 5–7 min | |
| everything else (~15 jobs) | **~7 min total** | cheap |

So the pass finished only when Reddit behaved. When it didn't, **every source
after `linkedin` was lost** — aijobs, companies, telegram, weworkremotely,
jobboards, jobicy, remotive, fbsearch, whatsapp, feedback, linkcheck. Not a
slow degradation; a clean cut at 30:00. The tail is the cheap part — the
variance is all upstream, which is why raising the ceiling fixes it rather
than trimming sources.

- **`timeout-minutes` 30 → 50.**
- **Night cadence**: full passes added at 23:17 / 01:17 / 03:17 UTC on top of
  the existing 21:17 → 00:17–06:17 Israel. US/CA clients post through their
  working day, which is Or's night; he's asleep for all of it, so this is the
  cheapest throughput on the board. Each pass blocks at most ~2 `fbnight`
  slots (shared concurrency group), which is a good trade: `fbnight` finds
  *groups*, the full pass finds *leads*.
- **`fbnight` extended to 04:45 UTC** (06:00–07:59 Israel). It is the only
  workflow that uploads `leads.db` as an artifact, so without a morning slot
  everything the 03:17 and 05:17 passes find sits in the Actions cache until
  the *next* night — `sync_cloud` would pull a snapshot from 02:45 UTC.
- **`morning.yml`** at 04:25 UTC (07:25 IL) → `--morning-report --notify`.

**`--morning-report [PATH] --hours N` (new)** — markdown table of everything
found in the window, score-ordered, unscored last (the cloud's LLM budget can
die mid-night and a gate-passed unscored lead is still worth an eyeball).
Also `--only`/`--skip` for `--once`, so a pass can be split across two
workflows if the timeout ever bites again.

**Delivery is Telegram only, and the report is gitignored.** The repo is
public and the table is lead data — summaries, budgets, permalinks to real
people's posts — the same reason `leads.html` and `*.csv` are already
excluded. `morning.yml` prints the report's line count and never its content,
because workflow logs on a public repo are public too.

**⚠️ Pre-existing exposure, flagged not fixed:** `fbnight.yml` uploads the
whole `leads.db` as a build artifact on a **public** repo, 3-day retention.
`sync_cloud._newest_artifact` is built on that artifact, so removing it breaks
the only path that brings cloud leads home — Or's call, not a silent change.

### The real ceiling is scoring, not finding (measured 2026-08-13)

Fixing the timeout exposed the next constraint. In the cloud, **all three
scoring backends were dead at once**: Ollama (no runner GPU, by design),
Gemini (daily free tier, ~20 calls), and OpenRouter. The OpenRouter headers
are unambiguous:

```
"Rate limit exceeded: free-models-per-day"
x-ratelimit-limit: 50   x-ratelimit-remaining: 0
x-ratelimit-reset: 1786665600000  -> 2026-08-14 00:00 UTC (03:00 IL)
```

**50 requests/day**, resetting at 00:00 UTC. Gemini's resets ~07:00 UTC. So the
21:17 and 23:17 UTC passes cannot score at all, and only the 01:17 / 03:17 ones
have budget. An unscored lead is **never pushed to Telegram**, so this — not
source coverage — is what caps how many leads actually reach Or's phone.

- **`_openai_chat` has no `_throttle()` call** (only the Gemini path does), so
  the provider chain fired 10 calls in 5s and 429'd on all of them. Looked like
  the bug; **it is not** — a probe with 8s of spacing still 429'd, and the
  header says the daily bucket is empty. Throttling would not have helped.
  Left alone deliberately: measured, not guessed.
- **New workflow step `--score-backlog 25`** after each pass. Nothing ever
  re-visited a lead once stored unscored, so a lead found while the quota was
  dead stayed unscored forever. Now the post-reset passes spend their fresh 50
  on the night's earlier finds. Capped at 25 so one pass can't eat the bucket.
- **`GROQ_API_KEY` / `CEREBRAS_API_KEY` are already wired** into `config.
  LLM_PROVIDERS` and into both workflow steps; `active_providers()` filters out
  empty keys, so they are inert until the secrets exist. **This is the highest-
  value 3-minute user action after the Gmail password** — Groq's free tier is
  ~14k requests/day against OpenRouter's 50, which would end cloud unscoring
  outright.

**Also seen, not acted on:** `r/freelance_forhire` 404s after its backoff
(dead or renamed — unverifiable from Or's IP, Reddit 403s it entirely); two
leads/run die on `scoring failed: Unterminated string` (truncated LLM JSON,
`status='error'`, 6 so far).

## Session 2026-08-08 (night) — worldwide client-side group discovery

**Why US/UK produced nothing** — answered, and it was our fault, not the market's. The 16 Israeli
groups are **"דרושים" groups where clients post work**; the 6 US/UK ones were **developer
communities**. All 10 good FB leads came from the former, 0 from 44 posts in the latter. The
variable was never the country — it is who posts.

- **Query set rewritten around buyers**: founders, SaaS/agency/business owners, "looking for a
  developer", "need an app built", across US/UK/CA/AU/NZ/IE/ZA/SG/UAE. 34 queries. Dev-community
  names moved to `FB_NOISE_RE`; client-side words score relevance. Hebrew set untouched.
- **The gap that made discovery pointless**: `facebook_public_fetcher` read only
  `config.FACEBOOK_GROUPS`, so a discovered group was never scraped. Pool is now config ∪ promoted.
- **`fbnight.yml`** — every 30 min, 20:00–05:00 Israel, ~19 runs. Many small runs on fresh IPs is
  the whole point; one long run gets walled in minutes. 2 DDG queries + 2 probes + 4 smoke-scrapes
  per run. Commits `discovered_groups.json` back to the repo, because the cloud's `leads.db` lives
  in the Actions cache and is a different database from the local one.
- **Promotion redesigned after the first live run.** Requiring a successful probe was a no-op —
  Facebook throttled the runner after 2 probes, so nothing reached `status='public'`. Promotion now
  rests on the name (relevance ≥2 from DDG titles, zero Facebook cost) and the smoke-scrape does
  the verifying: proves public, counts gate-passing posts, demotes after 2 zero-yield visits.
  It uses the **free regex gate, not the LLM** — cloud runners have no Ollama and the Gemini free
  tier dies after ~20 calls/day.
- **Measured after two verification runs:** 96 groups discovered, **15 promoted into the rotation**
  (`automationisrael`, `n8nil`, `ai.israel.official`, `israelaiorg`, `israel.hightech`, …).
- **Known limiter, not a bug:** Facebook throttles the runner within ~2 page loads, so probes and
  smoke-scrapes abort early most runs. The 3-consecutive-`gone` guard reports it rather than
  writing garbage. Realistic yield is tens of verified groups per night, not hundreds.

## Session 2026-08-08 — email path live, two real bugs found

- **Gmail IMAP connected** (app password added; the first attempt was the real Google password, the
  second had the 16 chars but kept its spaces). Inbox holds **236 LinkedIn job-alert emails**, 189
  facebookmail. First ingest of 30 days: 98 leads → **3 instant Telegram pushes**.
- **Backlog fully cleared**: 0 unscored, 1,123 scored, via the Ollama fallback. 60 leads ≥7, 7 ≥8.
- **BUG (fixed): alert-email subject leaked into every job.** LinkedIn names each alert after one
  promoted job (*"Computer Vision & ML Expert at Alignerr: up to $150/hour"*), and the subject is
  prepended to every job parsed from that email — deliberately, for the domain gate. Unfenced, the
  scorer billed **Mobileye and Wayve full-time roles as "$150/hour contract"**, putting three false
  8s at the top of the list. The subject is now fenced with an explicit "ignore any pay rate in
  this" marker. Re-scoring the 42 stored alert leads: 36 low, 4 digest, **2 genuine** pushes.
- **BUG (fixed): the FB prober wrote garbage when throttled.** A throttled IP and a dead slug share
  one signature (bare "Facebook" title, no articles). Run with `probe_cap=40`, a GitHub runner
  returned **40/40 "gone"** — including groups already verified real. Now 3 consecutive "gone"
  aborts the run, `gone` is re-probeable rather than final, and the default cap is 10.
- **Reddit search added as an FB-discovery surface** — DDG challenged the GitHub runner too
  (HTTP 202), so it was the only network surface left. From the cloud it found **47 new groups**
  (13 locally), which is now the main way the group list grows.

### Measured this session (all changed a decision)
- **`f_AL=true` IS honoured; `f_JT` is NOT.** Easy Apply returned only 3/10 overlap with the
  unfiltered baseline (real filtering), while `f_JT=C` returned 10/10 identical ids and 4/4 detail
  pages said "Employment type: Full-time". Confirms and sharpens the July finding.
- **Easy Apply cannot be detected per-job logged-out.** Every guest detail page carries the same
  `apply-link-offsite…contextual-sign-in-modal` markers — sign-in chrome, not a job signal. No
  `applyUrl`, no "Easy Apply" string. Hence the flag comes from *which query found the job*.
- **DuckDuckGo is the only search engine still serving organic results** (8 FB slugs, 4 new).
  Bing, Startpage, Mojeek captcha-walled; Brave 429'd. DDG then challenged this IP (HTTP 202)
  mid-session, POST and `/lite/` included → moved to cloud.
- **`mine_db` is useless for Facebook**: all 17 slugs in 6,794 stored posts were already in config,
  0 new. Opposite of WhatsApp, where DB-mining was the best surface — FB posts link their own group.
- **LinkedIn job alerts are ALREADY arriving in Gmail daily** (this doc previously said "awaiting
  user setup" — wrong). `jobalerts-noreply@linkedin.com` is delivering on-target leads right now:
  *"Computer Vision & ML Expert at Alignerr: up to $150/hour"* (recurring), *"Senior Computer Vision
  Engineer at ShipIn Systems"*, *"Data Engineer (5-month part-time contract) at Dragons Group"*.
  **The only missing piece is the Gmail app password.** This is now the highest-value user action.
- **Or's `facebookmail.com` mail carries no professional groups** — his joined groups are
  apartment/neighborhood groups (נווה אביבים, דירות בתל אביב), and no group has "All posts" on. So
  the FB email channel currently yields exactly zero. Only real find: the Hebrew group
  *"בינה מלאכותית בגובה העיניים | AI פרקטי"* (slug not yet resolved).

## Session 2026-09-06 — the email job was dying on a Hebrew charset

- **BUG (fixed): `unknown encoding: iso-8859-8-i` killed every email pass.**
  `_decode_header` decoded each MIME header with the charset the *sender* declared:
  `text.decode(enc, errors="replace")`. `iso-8859-8-i` is a mail charset, not a Python codec
  name — the `-i`/`-e` suffix is RFC 1556 bidi *directionality*, the same Hebrew bytes as
  `iso-8859-8`. `codecs.lookup()` therefore raises **`LookupError` before any byte is decoded**,
  which `errors="replace"` cannot catch. Nothing wrapped it, so it escaped `fetch()` and became
  the Telegram error alert.
- **It cost far more than the two alerts suggested.** The `From` header is decoded at
  `email_fetcher.py:261`, one line *before* `_source_for()` decides whether the mail is even a
  lead source — so a Hebrew college-helpdesk mail took the whole job down. And the loop runs
  newest-first (`reversed(ids[-300:])`), so every alert **older** than the offending mail was
  skipped and never marked seen, in every 5-minute run, until it aged out of
  `IMAP_LOOKBACK_DAYS`. The error alert is throttled to one per job per 6h, so "2 messages"
  meant ~12h of continuous failure.
- **Measured on the live inbox** (67 messages, 3-day window): header charsets were
  `utf-8` ×46, `windows-1255` ×2, **`iso-8859-8-i` ×8** — all 8 from one Hebrew
  university-helpdesk sender, i.e. a sender with nothing to do with leads.
- **Fix:** one `_decode_bytes(data, charset)` helper, used by both `_decode_header` and
  `_get_html_and_text`. It normalises known mail-charset aliases (`iso-8859-8-i/-e` →
  `iso-8859-8`, `unknown-8bit`/`x-unknown`/`default` → utf-8, `ks_c_5601-1987` → cp949) and on
  `LookupError` falls through utf-8 → cp1255 → **latin-1**, which maps every byte and so can
  never raise. Signatures and call sites unchanged.
- **Same root cause was also failing silently in the body path.** `_get_html_and_text` wrapped
  its decode in `except Exception: continue`, so a Hebrew-charset *body* was not a crash — it
  was an empty string, i.e. a lead quietly stripped of its text. Those bodies decode now. Worth
  remembering given that Hebrew "דרושים" groups produced all 10 good leads.
- **Verified end to end:** `--once --only email` → exit 0, **23 leads extracted, 23 enriched,
  1 Telegram push**, gate split `{full_time: 13, seeker: 2, stale: 2, duplicate: 4, low: 1}` —
  the full-time-heavy split is the expected LinkedIn shape. `test_gate.py` still 15/15.

## Session 2026-10-06 — pivot from "watch postings" to "reach out"

**Why:** ~9.5k posts stored, ~5 pushed, 20 handled; Or reported no replies and too low-paying or
full-time leads. Public postings are the most competitive channel. Plan is in
`~/.claude/plans/i-tired-to-get-cosmic-meadow.md` (A WhatsApp, B outbound, C conversion, D domains).

**Done**
- `config.py`: `_DOMAIN_EN`/`_DOMAIN_HE` widened (machine vision, inspection, medical imaging, LiDAR/SLAM,
  VLM, document AI/IDP, RPA/AI automation, dashboards, data annotation + Hebrew equivalents).
  `test_gate.py` 15/15. Re-run `audit_gate.py` once new traffic accumulates.
- **`outbound.py` (new, drafts only):** `pipeline.ingest` now calls `outbound.capture()` when the gate
  rejects a fresh full-time post that has a strong domain term and a feasible location -> `prospects`
  table (new in `db.SCHEMA`). `job_outbound` sends ONE Telegram batch/day (5 prospects) with a
  contract-capacity pitch. `--outbound-dry-run` previews. Or contacts them by hand.
  Stored full-time rows were all >14d old (backfill = 0), so the table fills from new traffic.
- **Security fix:** `scorer.generate` and model discovery logged httpx errors that embed
  `?key=<GEMINI_API_KEY>`; now redacted. `agent.log` already holds 6 earlier copies — **rotate the
  Gemini key if that file ever leaves this machine.**

**Still to do:** WhatsApp (waiting on Or's extra phone number; reader is read-only, local, allowlisted, polled
every 15 min); `feedback.py` verdicts for prospects (sent/replied/won) + day-3/7 follow-up reminders;
proof-assets page; funnel report; add `GROQ_API_KEY` GitHub secret; talent-network applications (A.Team,
Braintrust, Toptal, Gun.io, Contra, Alignerr/Mindrift).

## 2026-10-09 — WhatsApp night hunt (`wa_night.py`, `wanight.yml`)
Goal: 50 relevant WhatsApp invite links (HE+EN) by morning for Or to join by hand on the second phone.
- Cloud slices every 20 min 20:00-05:59 IL (UTC+3 until 25 Oct; shift crons an hour after), own `wa.db` cache +
  own concurrency group (`fbnight` every 15 min on `leadagent` would drop pending runs). Final run 05:50 IL
  (`--select --notify`) validates, LLM-rates names in batches, Telegrams the top 50, commits `whatsapp_top50.md`.
- Surfaces: Reddit search.rss, GitHub code search (runner token), public Telegram channels, DDG (+ directory pages it
  surfaces), stored leads.db. Verified: first cloud slice found 40+40+51 invites, validation works from GitHub IPs.
- Logs print counts only. Group list goes to Telegram. The agent never joins anything.
- Next: Or joins the links, gives me the second number, then `whatsapp_reader.py --pair/--groups`, set
  `WHATSAPP_GROUP_ALLOWLIST`, run `--listen`.

## 2026-10-09 night — fixing the hunt, WhatsApp ingestion, outbound v2
- **First hunt under-delivered**: only 4 of ~30 cron slices fired (GitHub throttles frequent crons), list = 15
  groups, 0 Hebrew, all student/regional. Fixes: `wanight.yml` is now **self-chaining** (each slice waits 7 min and
  dispatches the next; crons are an hourly backstop; ends with a select run after 02:45 UTC); `FOREIGN_RE` drops
  other-country/language names before the LLM; rating prompt now says Or is in Israel and wants HE/EN only;
  seeded directory crawl (asmarketing.co.il, wp-index.co.il, whatsgrouplink, Hive Index topic -> community pages);
  `wa_research_links.txt` holds links found by 3 research agents (20 links -> 12 live, 8 dead/wrong).
  `wa_night.py --add-links FILE --via manual|research` ingests extra links (manual = Or's own groups, tier A).
- **WhatsApp ingestion pre-built**: `INTENT_REQUIRED_ROOTS={"whatsapp"}` (domain AND hiring intent), Hebrew
  freelancer-for-hire patterns added to `SEEKER_RE`, stable message ids in `whatsapp_reader._to_lead`
  (`hash()` is salted per process), 4 new `test_gate.py` cases (19/19). Fake messages through reader -> gate ->
  scorer verified. Observation: the local model hallucinated "over a month old" on a same-day post.
- **Outbound v2**: `outbound_news.py` (TechCrunch AI + Geektime IL funding/launch news -> prospects), one Telegram
  message per prospect, `sent/replied/won/skip` verdicts via `feedback.py`, day-3/7 follow-ups, morning-only send
  window (04-09 UTC).
- Drafts (gitignored): `portfolio_draft.md`, `talent_networks.md`, `MORNING_PLAN.md`.

## 2026-10-18 — WhatsApp groups joined + read on the second phone (`wa_phone.py`)
- **Hardware:** second SIM in a Galaxy S9 (Android 9, Hebrew UI, old active account), USB to this PC,
  ADB authorized, screen lock set to None by Or. adb at `%USERPROFILE%\tools\platform-tools`.
- **No linked device.** Or ruled out WhatsApp Web; neonize/Baileys removed from `whatsapp_reader.py`
  (only `_to_lead` remains). `wa_phone.py` drives the official app via `am start` + `uiautomator dump` + taps.
- **Join:** targets = `whatsapp_top50.md` (pulled each pass), Or's order (freelance/AI first, general boards
  last), ≤1 join/pass, 09–21 IL, 6/day, 90-min gap. Get-rich sheets skipped (`SCAM_RE`; "AI Freelancers"
  was one). Admin-approval groups → `requested`, rechecked daily. Day 1: joined *Secret Machine Learning Jobs*.
- **Read:** chat list scrolled to top (WhatsApp keeps scroll position), allowlisted groups with an unread
  badge opened, screens dumped to the bottom. Verified ids: `message_text`, `caption`, `date`,
  `conversation_row_date_divider`, join sheet ids. **Unverified:** group sender ids (`name_in_group*`) -
  only admin-only groups to test on; kv `wa_bubble_ids` collects the real ids seen. Long "read more"
  messages are read truncated.
- **Questions as leads:** prefilter verdict `question` (WhatsApp: strong domain + question marker, not a
  learner ask) → `scorer.score_question` (Ollama first) → ❓ push with angle + `wa.me` link. `test_gate.py`
  24/24 incl. 5 new cases. End-to-end test pushed one ❓ and one 🎯 (both 8/10) to Telegram.
- **Schedule:** Task Scheduler is *access denied* for this account (even unsandboxed), so `wa_loop.py`
  (pythonw, Startup-folder shortcut "AgentLead WhatsApp", localhost-socket single instance) runs
  `main.py --wa-pass` every 2h. PC sleep set to never on AC. Daily "WhatsApp phone OK" Telegram heartbeat.
- **Known gap:** Telegram feedback words on WhatsApp pushes are lost when the cloud's `feedback` job polls
  first (separate offsets; the cloud DB has no WhatsApp leads). Pre-existing for cloud_sync too.

## 2026-10-19/20 — join-all burst, and why the first day read nothing
- **Join-all** (`wa_phone.py --join-all on`, Or's call): 3–8 min random gaps, 08–23 IL, 50/day, ≤60 min
  per pass; `wa_loop` re-runs every 5 min while it's on. Stops itself after 3 failed joins in a row.
  First evening: 14 joined, 21 requested (admin approval), 1 dead, 13 left for the morning.
- **0 leads on day 1 were three bugs, not quiet groups:** (1) the unread badge's count is in
  `content-desc` ("3 הודעות שלא נקראו"), its `text` is empty → `_unread` never fired; (2)
  `recheck_requested` → `_set_group(code)` with no columns built `SET , last_checked` → sqlite error
  *before* `read_pass` on every pass once a request was 24h old; (3) four passes died on
  "uiautomator dump failed" (now: pkill uiautomator + relaunch before the last retry). Stages now run
  independently (`_stage`); errors are raised only after ingest. Sender id confirmed: `name_in_group_tv`.
- **First real messages:** the "Secret … Jobs" groups are a secrethunter.io bot feed of full-time roles
  (gated out, correctly). Their shared template fuzz-matched as duplicates → `db._id_links`: two posts
  whose per-posting links differ are never dups. A `?utm_source=` made one a "question" → URLs are
  stripped before `QUESTION_RE`. `test_gate.py` 25/25.
- **More groups:** invite links pasted inside our groups are queued (`found_via='in_group'`, priority
  3000+) and vetted on the join sheet (`_on_topic`: jobs/dev/AI/client-side words, no cohorts/foreign).
  `whatsapp_tried.txt` (codes only) is pushed daily and `wa_night.select_top` skips those codes, so the
  morning list is new groups instead of the same 50.
- **Not built:** tapping "קרא עוד" — no truncated message existed yet to verify where the span sits (a
  wrong tap opens a link). kv `wa_truncated_seen` counts them; build it when that's > 0.
- **Heartbeat** now adds top 3 groups by pushed leads (7d) and the groups silent 7d+ (report only).
- **Or, 2026-10-20: "part time, contract, freelance - only relevant ones".** The lists were mostly
  full-time boards. `config.WA_FREELANCE_GROUP_RE`/`WA_BUYER_GROUP_RE` now rank first (phone join order
  + `wa_night._rank` +4), `WA_SKIP_GROUP_RE` (secrethunter "Secret X Jobs" feeds, career/job-seeker
  communities, DevOps/QA/cyber/marketing/SEO, senior/junior salary boards) is never joined or listed;
  10 gig/contract DDG queries added. A daytime burst of 8 cloud slices grew the pool only 1815 → 1818:
  **the public discovery surfaces are saturated** — new groups now come mostly from in-group links.
- **CV focus (`wanight.yml` input `focus=cv`, `wa_night.py --focus cv`):** 18 slices of CV-only queries
  (IL/US/EU, OpenCV/YOLO/image processing/machine vision/medical imaging) found ~22 invites, pool
  1818 → 1829 live, and only **one** CV-named group reached the list ("Computer Vision LLM"). Public
  WhatsApp CV groups barely exist; CV groups (`config.WA_CV_GROUP_RE`) now join first when found.
- **Cloud scoring was dead:** OpenRouter's nemotron-super provider 404s ("Function not found"), so with
  Gemini's quota gone cloud leads were stored unscored and never pushed. Primary is now
  `minimax/minimax-m3.1-flash:free` (backup: super). First pass after: backlog scored 25, pushed 1.

## 2026-10-20 evening: hunt where work is asked for, plus an outreach lane
**Why:** after day 1 the phone had read 27 messages from 30 groups, and all 27 were full-time
job-board posts (the secrethunter feeds, the LogOn board), correctly gated. Freelance work is asked
for in client communities, passed on between freelancers and dev shops, or latent in companies that
need it, which takes outreach. Or agreed to spend ~10 min a day sending drafted messages.

- **Never silent again:** `main.py --funnel [DAYS]` (counts only, also a `leadagent.yml` step) and a
  `scoring_watch` job that alerts when more than 30 leads from the last 24h are unscored. Unscored
  leads sit at `status='scored' AND score IS NULL`, not `new`.
- **Phone:**
  - It no longer opens joined groups matching `WA_SKIP_GROUP_RE` (Or: stay, stop reading). The
    secret… Freelance/Remote/Machine-learning feeds are still read.
  - The dump flake (12 failed passes, 17:48–18:06) is fixed by turning the phone's animations off.
  - "Waiting for this message" placeholders are skipped.
- **Gate:**
  - `WA_JOB_CARD_RE` makes a job card or salaried ad in WhatsApp `gate_full_time`, so an in-domain
    one becomes a prospect instead of a ❓.
  - Recommendation asks ("מישהו מכיר מפתח…", "can anyone recommend a … developer") count as ENGAGE.
  - `test_gate.py` 28/28.
- **Hunt:**
  - `wa_night --focus client` adds client/work-passing DDG/Reddit queries and community hubs
    (linktr.ee, meetup, lu.ma pages are crawled by `surf_dirs`). The night chain now keeps its focus.
  - `WA_BUYER_GROUP_RE` gains business-owner, automation and no-code words.
  - t.me handles seen anywhere become candidates. `validate_tg` (in `--select`) promotes live,
    gate-passing channels to `telegram_found.txt`. `telegram_fetcher` adds them to its pool and
    demotes after 3 zero-pass days.
- **Search:** 7 recommendation/subcontract FB search-index intents and 1 Reddit query
  (YOLO/video/extraction).
- **Outreach:**
  - `agencies_il.jsonl` (39 Israeli dev shops/AI consultancies, researched, gitignored) is dripped
    2 a day by `outbound.drip_agencies` with a subcontractor pitch (`AGENCY_PROMPT`).
  - The local phone pass now runs its own outbound batch (WhatsApp prospects + agencies). The cloud
    keeps news.
  - Globes tech and Globes English feeds were added. The CTech/NoCamels/Geektime-EN feeds 404.
  - Full-time prospects must name a core skill (`_CORE_RE`); a recruiting ad got in on "חשבוניות".
  - ❓ pushes carry a ready-to-paste answer (`leads.reply_draft`).
- **Scorecard:** every Sunday from 09:00 IL, per source and per outreach, from both the cloud and
  the phone PC.
- **Marketing kit** (`marketing_kit.md`, gitignored): LinkedIn post (HE/EN), weekly post ideas,
  profile blurbs, the group-answer playbook.

## 2026-10-21 night: leads that arrive by themselves (Or: no outreach for now)
- **Leak fixed:** `fbnight.yml` had been uploading `leads.db` in plain text as an artifact. On a
  public repo, any signed-in GitHub user can download those.
  - The upload is now `leads.db.enc`: AES-256 with `openssl -pbkdf2`, key `DB_EXPORT_KEY` (repo
    secret plus Or's `.env`). There is no plaintext fallback.
  - The 16 plaintext artifacts were deleted.
  - `sync_cloud.py` decrypts the artifact. The cloud→home sync works again, and 61,744 cloud
    leads were merged locally, so local analysis and the Ollama audit now run on real data.
- **60-day winners review** (54 leads ≥6, cloud DB, read locally):
  - The most frequent paid kind is AI-training/expert contracts: micro1, Mindrift, Alignerr,
    Mercor, $60–200/hr.
  - The best on-target finds are document-intelligence roles and Israeli FB "looking for an
    AI / invoice-automation developer" posts.
  - The scorer also passes some off-domain 6s (marketing ops, Japanese language lead).
- **Mercor fetcher** (`fetchers/mercor_fetcher.py`): public `listings-explore-page` JSON with
  rate, hours/week and eligible countries.
  - It keeps Israel-eligible listings only. The 35+ h/wk ones gate as full-time.
  - First dry run: 202 eligible → 1 pass (ML Expert, $150–200/hr, 20 h/wk).
- **arbeitnow** is in `STRONG_DOMAIN_SOURCES`: the strong term must be in the header
  (title/types/tags). Replayed over 30 days, passes drop from 2,565 to 95, and the
  Document-Intelligence winner is kept.
- **F5Bot** (`f5bot.com`, free): its Reddit/HN keyword-alert mails are parsed by
  `email_fetcher._parse_f5bot`.
  - Hits are labelled `r/<sub>` / `hn`, and only hits matching ENGAGE are kept.
  - **Waiting on Or to sign up**; account creation can't be automated. Keyword list below.
- **Queries:** 4 Hebrew/English FB intents copied from the winners, 6 FB groups that produced ≥5
  leads but were not in config, and 2 Reddit searches (document AI, AI-training contracts).
- **Phone:**
  - The USB link dropped around 22:05, and every pass since then has failed.
  - `wa_phone.py --wifi-setup` (cable plugged in) enables Wi-Fi adb as the fallback link
    (`.adb_wifi`, gitignored).
  - An empty dump now checks the link and reports "phone disconnected".
  - 22:20, after the replug: Wi-Fi adb set up (`192.168.x:5555`). Every dump then failed with
    `could not get idle state` (an error printed on stderr, which the code didn't read, so the
    message was empty). HOME + relaunch didn't clear it; `am force-stop` did. `dump()`'s last
    retry now force-stops WhatsApp, and the message includes stderr. A pass then read 9 messages
    (5 full-time, 3 dup, 1 offtopic) and joined 1 group.
  - The local DB had 17 cloud `error` leads (scoring quota). They were requeued and scored by
    Ollama: 5 pushed. Only the micro1 AI-training gig was real; 3 discussion posts got a 6.
- **Probed and rejected:**
  - freelancermap: the RSS is a 404 and the listings render in JS.
  - PeoplePerHour: listings are login-walled.
  - Ashby boards of Mercor/Surge/Handshake: staff roles, not gigs.

### F5Bot keywords (add after sign-up)
`hiring computer vision`, `need OCR`, `computer vision freelancer`, `YOLO developer`,
`opencv developer`, `document extraction`, `invoice OCR`, `hiring machine learning engineer
contract`, `looking for ML engineer`, `image processing freelance`, `defect detection`,
`video analytics developer`, `data extraction freelancer`, `AI automation developer`,
`document AI`.

## 2026-10-22: no full-time posts on Telegram, even as prospects

Or: "you still sending me full time". The gate was right (every WhatsApp job card was
`gate_full_time`), but `outbound.capture()` turned the in-domain ones into morning
"pitch contract capacity" prospects, so Railvision / Inspira / SmartShooter job posts
still reached Telegram. New flag `OUTBOUND_FULLTIME` (default **0**): `pipeline.ingest`
no longer captures them, `backfill()` is a no-op, and `outbound.pending()` hides the
full-time prospects already queued (2 left in the table, untouched). Agency and
funding-news prospects still go out.

## 2026-10-22: WhatsApp - more RELEVANT groups, not more groups

Measured first: the 38 joined groups had produced **0** passing leads (job boards are
all full-time; most communities never posted). So the fix was relevance, not volume.
Web research (3 agents; WebSearch + directory crawls) found ~60 new live invites where
work is handed out: GenAI Israel's **Jobs/Freelancers** groups (linktr.ee/llm.org.il),
Vibe Coders IL / Base44 IL (non-devs who need an engineer), automation-freelance groups,
Israeli founder/business-owner networks, and global founder / AI-builder groups.
- `wa_phone.py --add-targets FILE` queues them at priority -3000 (ahead of the hunt's
  tier-C list); Israeli first, global +100 after. All recorded in `wa_research_links.txt`.
- `wa_night.py`: `IL_DIR_SEEDS` (linktr.ee/llm.org.il, klicky index ~950 invites,
  igroupsil hi-tech/work categories, grouphub searches) for `all` and `client` focus.
- `--select --more N` (workflow input `more`) sends N extra groups not already on the list.
- Join-all is ON (cap 50/day); ~100 targets queued -> ~2-3 days to work through.
- Note: two agents checked invite pages from this machine's IP until chat.whatsapp.com
  rate-limited it (web previews only; not the phone app).

### 2026-10-23 - WhatsApp: the night hunt aims at work-passing groups, phone joins daily

Measured: 43 joined groups, 50 messages read, 38 gated full-time + 11 off-topic, **0 leads**;
94 joins still waiting for admin approval, 53 dead links.
- `wa_night.py --focus auto` (workflow default): slices rotate client/all/client/cv. New
  client queries (GenAI jobs/freelancers, vibe coding, Base44/Lovable, Claude Code/Cursor/MCP,
  AI agents, העברת עבודות). Hub pages (linktr.ee / lu.ma / meetup) seen in any page or stored
  post go to the front of `surf_dirs`' queue. Local dry run: 1,037 invites + 55 hub pages.
- Rubric v2 (`LLM_RUBRIC_VER`): full-time job boards = 0, builders/founders/freelance = 3;
  the pool is re-rated once. `select_top` keeps LLM >= 2 only (no padding with 1s).
- `wa_phone._sheet_ok` vets every target's join sheet (`WA_JOB_BOARD_TITLE_RE`,
  `WA_FT_ONLY_SHEET_RE`); 13 of the 43 joined titles would now be skipped.
- Join-all re-arms on each new night list (`WA_JOIN_ALL_AUTO`); invites pasted in
  work-passing groups queue at priority 500.
- Fixed `WA_BUYER_GROUP_RE`: `אוטומציות?` never matched the singular "אוטומציה".
- **Re-check on 2026-10-30:** heartbeat "best 7d" should show pushes from the new groups.

Same day, later:
- **Cloud LLM was dead.** OpenRouter's `minimax-m3.1-flash:free` left the free tier and
  `nemotron-3-super:free` still 404s, so the 05:50 select rated 0 groups and sent 12 job boards
  and student groups, and cloud leads were stored unscored. Now `nemotron-3.5-super-vl:free`
  (reasoning model: `min_tokens` 4000 in `LLM_PROVIDERS`, empty content = next provider), with
  `gemma-4-31b-it:free` as backup. `llm_pass` rates at most 12 × 30 names a night (a 60-name call
  takes ~200 s and the free tier is ~50 calls/day). Without an LLM rating, `select_top` needs a
  work-passing word in the name (`_name_ok_without_llm`). "מנהלי פרויקטים" / "project managers"
  no longer count as freelance. Student and course names are now noise.
- **2020 Facebook posts reached Telegram.** `facebook/search` gets no post date and DDG returns
  old posts. Now `df=m` (past month, `FBSEARCH_DATE_FILTER`), and nothing older than
  `PUSH_MAX_AGE_DAYS` (21) is pushed, whatever its score.
- **Phone unreachable alert** (`adb connect ... timed out`): a dead Wi-Fi link no longer
  crashes the pass; the alert says to plug USB in, and a USB pass re-arms Wi-Fi adb itself.
- **Cleanup / efficiency pass:**
  - Cloud scoring: `_openai_chat` retries a 5xx once, then parks that provider 10 min
    (the primary 502'd for a whole run and every lead paid for it). Third model added:
    `nemotron-3.5-lightning:free` (gemma's free endpoint is upstream-429 most of the day).
  - `JOBS`: linkedin/reddit/reddit_search moved after the cheap fetchers (cloud: ~26 min sooner).
  - `wa_loop`: no 5-min burst passes once the day's 50 joins are used (it ran a 107s screen-on
    pass every 7 min all evening). Restarted wa_loop to load it.
  - Fuzzy dedup reads only the 1,500-char prefix with a rapidfuzz cutoff: identical verdicts on
    300 real posts, ~18% faster. `agent.log` (5 MB x 2) and `wa_pass.log` (5 MB + .1) rotate.
  - Untracked 3 stray `scratch_*` files from the public repo; old local exports moved to
    the gitignored `archive/` (nothing deleted).
  - 2026-10-24: Gemini timed out on every call of a cloud run; the error escaped `score_lead`,
    so each lead cost ~2 min and was stored as `error`. Gemini now parks 10 min on a
    network/HTTP error and the lead goes to the OpenRouter chain.
- **Why WhatsApp gave 0 leads (2026-10-24): the reader barely read.** 2 reads today, 3 yesterday.
  (1) Each pass started mid-list (WhatsApp keeps the scroll position; scroll-to-top gave up after
  10 swipes or one look-alike dump) and only scrolled down, so groups with new messages - at the
  top - were skipped. Fix: force-stop WhatsApp before reading; a fresh process starts at the top.
  (2) 24 approved join requests (Base44 IL, TESTAIMND AI automation freelance, RiseHub, הרשת
  העסקית...) stayed 'requested' forever: once you are a member the invite opens the chat, not the
  sheet `recheck_requested` looks for. Now read_pass marks them joined when their name is in the list.
  Not handled yet: community sub-groups show under the community's name in the list.
- **New WhatsApp reader (same evening):** watermark diff per group, invite-link opening,
  notification harvest (`wa_notify.py`), senders + wa.me numbers (every earlier WhatsApp lead had
  lost them), deleted-message placeholders skipped, unreachable groups remembered 24h.
  Measured: pass 1 read 163 new messages from 50 groups (the old reader: ~2/day); pass 6 walked
  1 list page, opened 2 groups, 75s (was 12 pages / 46 groups / 882s). The gate is right about
  the chatter (sampled 40 off-topic: student Q&A, discounts, plugin talk), so the lever now is
  which groups we are in. Open: 11 groups (mostly community sub-groups with reset links) are not
  reachable; "קרא עוד" tap not built (0 seen; notification copies are whole).

## 2026-10-25: the join list ran dry - find relevant groups, join ~50/day at a human pace
- **Joins stopped (0 on 10-25):** the night list went 50 -> 12 -> 12 -> 8 -> 0. Pool 2,143 live,
  360 rated a night, 0 selected: the strong names were all tried, directory seeds were read once
  ever, and a name the LLM left out of its reply was stored as 0 forever. Since 10-20 every message
  that passed the gate came from founder / AI-builder / work-passing groups; general tech chats
  and job boards: 0 of ~200. **Or: relevant only, up to 50/day** (fewer on a thin day).
- **wa_night:** omitted names stay NULL (re-asked), 60-name LLM batches (~600/night), directory
  seeds re-crawled every 7 days (kv `wa_night_seed_at`), queue/done trims keep arrival order
  instead of alphabetical, +15 client-side queries.
- **wa_phone pace:** see CLAUDE.md (10-18 min gaps, breaks, 42-50 cap, <=12 sheets/h, throttle
  screen -> 24h stop + 2 half-cap days, post-join chat visit). Simulated: 45-50 joins 08:27-22:29,
  min gap 10 min. `wa_loop` now sleeps until `next_join_at()`. Join-all re-arms on any untried target.
- **Descriptions:** each joined group's description is read once (3/pass) for invite links.
- **Communities (probed, not built):** the Communities tab -> community header shows
  "קבוצות שזמינות להצטרפותך" rows (`name`, status "בקשת הצטרפות", no invite code). Our communities
  are off-target (IITM cohort, AgTech, Coding, Modiin Tech, משרות מהבית, ACM) - build the
  tap-to-request flow once a good one (e.g. GenAI Israel) is joined.
- **Hand research:** 3 web-research agents (work-passing IL, founders/business owners, AI
  builders/CV) -> `wa_phone.py --add-targets` (priority -3000), codes appended to
  `wa_research_links.txt`.

## 2026-10-26: join backlog 62 -> 193

- **The phone was unplugged 08:55-19:44**, so only 1 join happened that day. `wa_loop` retried every ~80 s while it was unreachable. That is harmless, but it is log noise.
- **Second research round:** 3 agents found 211 links, and 140 relevant ones were queued with `--add-targets`:
  - Israel business and founder groups, including the IT chamber's Data & AI, digital health and smart-industry groups;
  - AI and industry communities;
  - international founder and AI-builder groups (INSEAD AI, Data & AI Product London, AI Underground Dubai, Networx London and others).

  Dropped: running clubs, French/Spanish/Portuguese groups, course groups and event-only groups. The codes are in `wa_research_links.txt`. The names are in the gitignored `whatsapp_research_2026-10-26.txt`.
- **No public WhatsApp groups exist** for CV, medical imaging, drones, agritech, GIS or BI. Those communities are on Meetup, Discord and Facebook only.
- **New night surface `israelgroups`** (weekly): reads `israelgroups.com/data/groups.json`, keeps names with a work or AI word, and drops junk categories and teacher groups. Only about 7 of 2,746 WhatsApp groups pass today, so it exists to catch future additions. The research round had already taken the good ones.
- **Best research sources:**
  - Meetup group descriptions, via its GraphQL search;
  - Luma event descriptions and calendars;
  - linktr.ee pages;
  - the community pages of israel-it.org (the Israel Chamber of Information Technology).

## Open items
- **Phone:** reconnected and Wi-Fi adb is set (2026-10-21 22:20). Still to build:
  the night crawl (Community sister-groups + group-description invite links). It needs live screens
  for resource ids.
- **F5Bot sign-up (Or, 2 min):** f5bot.com with orzilber0@gmail.com, then add the keywords above.
- ~~25 Oct 2026 clock change~~ done 2026-10-24: `wanight.yml` crons, `MODE` (`'50 3 * * *'`) and
  the chain window moved +1h UTC. The other workflows' Israel times now run an hour earlier
  (morning report 06:25 IL); shift them back in late March if that matters.
- **WhatsApp "read more" tap** once `wa_phone.py --status` shows truncated > 0.
- **Nothing is blocked on the user.** Checked 2026-09-06: the two standing "user action" items
  (join FB / WhatsApp groups) were measured and demoted below — see the yield table reasoning.
  The pipeline runs unattended.

- **⭐ User action, highest value (3 min): Gmail app password** → `IMAP_USER`/`IMAP_PASSWORD` +
  the two GitHub secrets. LinkedIn job alerts are *already* arriving daily with on-target
  $100–150/hr CV leads; the agent simply can't read them. This also unlocks every private FB group
  and Upwork/Wellfound. Nothing else on this list comes close in value per minute.
- ~~**User action:** join the 14 private FB groups~~ → **demoted 2026-09-06, measured.** Over the
  last 30 days *all* Facebook surfaces combined produced **38 leads, 1 at ≥7**, while Reddit gave
  613/16 and LinkedIn 175/5 — and LinkedIn's number was suppressed the whole time by the
  `iso-8859-8-i` crash. 14 more private groups cannot plausibly beat that, and joining is the one
  action the agent must never take on Or's behalf. The list stays in `facebook_groups.md` as
  optional upside; nobody should feel behind for ignoring it. The no-join surface
  (`facebook/search`, via the search index) already covers the same ground at the same yield.
- ~~**User action:** join the 2–3 ranked WhatsApp groups~~ → **demoted 2026-09-06**, same reason.
  Discovery-only is a design rule, not a gap: driving WhatsApp Web would put Or's personal number
  at risk. `whatsapp_groups.md` keeps the 3 live ranked invites if he ever wants them.
- The LinkedIn **saved-search alerts are already set up** — this was previously listed as a pending
  user action and was wrong. Verified 2026-08-06 in Gmail.
- 15 WhatsApp invites still `pending` (behind the per-run cap) — the daily job drains 10/day, or
  run `discover_whatsapp_groups.py --cap 25` once to clear them.
- Watch LinkedIn yield for a few days: guest filters are unreliable, so most of each run gates out
  as full-time. If yield stays ~0 while the email alerts deliver, demote the scraper to a longer
  interval (or drop it) and keep the email path.
- 17 FB groups still unprobed — now handled by the weekly **cloud** `fbgroups.yml` run
  (12/run). Never probe from the home IP: a Facebook throttle there surfaces as a
  login/checkpoint wall on Or's own account.
- 5 IL public groups unreached in the 2026-07-14 scan (listed above) — the cloud scraper's
  rotation covers them now.
- Resolve the slug for *"בינה מלאכותית בגובה העיניים | AI פרקטי"* (found in Gmail, looks like a
  genuinely relevant Hebrew AI group) and add it to the discovery table.
- Watch the LinkedIn Easy Apply pass for a few days. Expect most of it to gate out as
  `gate_full_time` — that's correct. If yield stays ~0, drop the dimension rather than loosening
  `FT_RE`; no-full-time is a hard user rule.
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
