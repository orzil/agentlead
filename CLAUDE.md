# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**AgentLead** is a zero-cost lead-generation agent for a freelance AI engineer (Or) based in
Israel. It polls ~16 families of free sources for freelance/contract gigs in computer vision,
OCR, image processing, ML, algorithms, data viz, and AI-integrated web, filters noise with a
regex gate + free-tier LLM scoring (1–10), pushes strong leads to Telegram, and can auto-reply
on Reddit — the only remaining channel with a legitimate posting API.

It runs on **GitHub Actions** (repo `orzil/agentlead`, private): `leadagent.yml` 4×/day and
`fbgroups.yml` weekly. `leads.db` lives in the Actions cache, never in git. Anything that
touches Facebook or a search engine **must run in the cloud** — see the IP rules below.

**Hard constraint: everything must stay free-tier.** No paid APIs, no VPS, no Apify. Scoring is
Gemini free tier (or local Ollama); notifications are a Telegram bot; most sources are public
endpoints, RSS, or alert emails read over Gmail IMAP. Never introduce a paid dependency.

`README.md` is the user-facing setup guide. `PROJECT_STATUS.md` is the running session log and
open-items list — **read it at the start of a session and update it at the end** (it tracks
things like the Freelancer.com trial decision and the queue of unprobed Facebook groups).

## Commands

Always run with `python -X utf8` on Windows — Hebrew posts break the default console encoding.
`run.bat` already does this.

```
python -X utf8 main.py                       # run forever: poll loop + daily digest at 18:00
python -X utf8 main.py --once                # single pass of every fetcher, then print stats
python -X utf8 main.py --stats               # DB counts by status/source + top scored
python -X utf8 main.py --test-telegram       # verify Telegram credentials
python -X utf8 main.py --score-test "text"   # score one post and print the LeadScore
python -X utf8 main.py --score-backlog [N]   # score up to N (default 300) stored-unscored leads
python -X utf8 main.py --regate              # re-run the (stricter) keyword gate over candidates
python -X utf8 main.py --export-html leads.html --min-score 8   # filterable dashboard
python -X utf8 main.py --export-csv leads.csv --min-score 8     # UTF-8-BOM CSV (Excel Hebrew)
python -X utf8 main.py --reply-test 541      # dry-run a drafted reply for lead 541
python -X utf8 main.py --replies             # list pending/failed/sent auto-replies
python -X utf8 main.py --approve-reply 3     # approve+send one reply (or 'all')
python -X utf8 probe_fb_groups.py --write    # probe unresolved FB group slugs public/private
python -X utf8 discover_whatsapp_groups.py --search --write   # find joinable WhatsApp groups
python -X utf8 discover_fb_groups.py --write # FB group join list (add --search/--probe in CLOUD)
```

**Never run `--search` or `--probe` (Facebook or DuckDuckGo) from Or's machine.** A Facebook
throttle on his home IP surfaces as a login/checkpoint wall on *his account*, and DDG challenges
the IP (HTTP 202) after a handful of queries — both measured. Trigger the cloud instead:
`gh workflow run "Facebook group discovery" --repo orzil/agentlead`.

No test suite, linter, or build step exists — this is a script-run project. `pip install -r
requirements.txt` to set up (`rapidfuzz` and `praw` degrade gracefully if missing; `playwright`
only needed for the Facebook scraper).

## Architecture

**Pipeline (the spine).** Every fetched post is a `Lead` (`models.py`) and flows through
`pipeline.ingest()`:

```
dedup (URL hash + fuzzy text vs last 7 days)  →  prefilter.classify()  →  scorer.score_lead()  →  route
```

- **`db.py`** — SQLite (`leads.db`). `insert_lead()` does the dedup: exact `url_hash`, then
  `rapidfuzz` token-set similarity ≥ `DEDUP_SIMILARITY` (90) against recent rows; a fuzzy dup
  appends its URL to `extra_urls` instead of inserting. Also holds `seen_emails`, a `kv` cursor
  store (last-digest-date, per-job error throttle), and the `replies` queue.
- **`prefilter.py`** — cheap regex classifier that runs **before** any LLM call so obvious noise
  never costs a Gemini request. Returns a reason string (`pass`, `partnership`, or a `gate_*`
  kill reason stored in `reasoning` for tuning). **Order is deliberate**: poster identity
  (seeker) and the ask (community/noise) trump engagement model (full-time/partnership), which
  trumps topic. Per-source rules matter — see the source-behavior sets in `config.py`.
- **`scorer.py`** — LLM scoring against a fixed `SYSTEM_PROMPT` rubric, returning a structured
  `LeadScore`. Gemini path self-throttles to 1 call / 6.5s (`_MIN_SECONDS_BETWEEN_CALLS`) to
  stay under the free-tier ~10 req/min, discovers an available model from
  `GEMINI_MODEL_PREFERENCE`, and retries 429/500/503. `generate()` is the generic Gemini helper
  reused by `replier.py`. Returns `None` when no backend is configured → lead is stored unscored
  for a later `--score-backlog` pass.
- **Routing thresholds** (`config.py`, env-overridable): score ≥ `PUSH_THRESHOLD` (8) → instant
  Telegram push (+ optional pitch draft + auto-reply consideration); ≥ `DIGEST_THRESHOLD` (6) →
  daily digest at `DIGEST_HOUR`; below → stored in DB only.

**Scheduler.** `main.py` `run_forever()` is a single-thread loop over the `JOBS` list (name,
interval seconds, fn) at the bottom of `main.py` — that list is where poll cadence lives. Each
job is wrapped in `run_job_safe()`, which logs exceptions and self-reports to Telegram (throttled
to one alert per job per 6h via the `kv` store). Add a new source by writing a fetcher and adding
one job tuple.

**Source gotchas worth knowing before you touch them:**
- **LinkedIn** (`linkedin_fetcher.py`) — logged-out `jobs-guest` endpoints. Its URL filters
  (`f_JT` job type, `f_WT` remote) are **unreliable and non-deterministic**: the same query can
  honour them one minute and silently serve full-time results the next (measured: one probe
  returned exactly the full-time result set). So the "Employment type" criteria line is folded
  into `raw_text` and `FT_RE` does the real filtering — expect most of every run to gate out as
  full-time, and never trust the filters. Cards lack the contract/hours text, so a job is only
  ingested after its description is detail-fetched (capped per run; the rest roll to the next
  run inside the 24h window). Every URL is canonicalised to `linkedin.com/jobs/view/<id>`
  (`canonical_job_url`) because cards use country subdomains + slugs and alert emails use
  `/comm/` links — that canonical form is the shared dedup key between the scraper and the
  email path. On a 999/403 bot-wall it sets a 6h cooldown in `kv` and stops; retrying extends
  the block. **The email-alert path is the robust half** — if the scraper dies, it keeps working.
  Verified 2026-08-06: those saved-search alerts are **already arriving daily** in Or's Gmail with
  on-target $100–150/hr CV leads. Only the Gmail app password is missing.
- **LinkedIn Easy Apply** — `f_AL=true` **is** honoured (measured: only 3/10 job ids overlapped the
  unfiltered baseline), unlike `f_JT`, which is ignored outright (10/10 identical, and every detail
  page said "Employment type: Full-time"). Easy Apply is **not detectable per-job** logged-out:
  every guest detail page carries the same `apply-link-offsite…contextual-sign-in-modal` markers,
  with no `applyUrl` and no "Easy Apply" string — that's sign-in chrome, not a job signal. So the
  flag comes from *which query found the job* (source label `linkedin/easyapply`), never from
  parsing the page. Expect most of this pass to gate out as full-time; that is correct.
- **Reddit sitewide search** (`reddit_fetcher.fetch_search`) — plain keyword queries rank
  semantically and return career-advice threads and seeker self-promos (measured: 14/20 passed
  the gate, 0 real). Queries anchor on `title:(hiring OR task)` instead. `search.rss` also mixes
  *subreddit* hits in with post hits, so `_parse_feed` keeps only `/comments/` permalinks.

**Fetchers (`fetchers/`).** Each module exposes a `fetch()` returning `list[Lead]` (a few take
`conn` for cursor/state). The `source` string convention is load-bearing: `prefilter` and
`notifier` split on `/` to get the root (`r/forhire` → `r`, `facebook/<group>` → `facebook`), and
several `config.py` sets key off it (`DOMAIN_REQUIRED_SOURCES`, `INTENT_REQUIRED_SOURCES`,
`FT_DEFAULT_SOURCES`, `GATE_BYPASS_SOURCES`). Keep source labels consistent with those sets when
adding or renaming a fetcher. Sources fall back gracefully (e.g. `reddit_fetcher` uses the public
RSS feed when no API creds are set).

**Discovery scripts (not fetchers).** `probe_fb_groups.py` (re-probes slugs already in config),
`discover_fb_groups.py` (finds groups *not* in config → `facebook_groups` table +
`facebook_groups.md`), and `discover_whatsapp_groups.py` (joinable WhatsApp invite links →
`whatsapp_groups` table + `whatsapp_groups.md`) produce lists for the *user* to act on; they never
enter the lead pipeline. `discover_fb_groups.py` splits its output by privacy: **public** groups
graduate into `FACEBOOK_GROUPS` and get scraped logged-out; **private** ones become a ranked join
list the user acts on by hand — the agent never sends a join request. Two surfaces, both measured
2026-08-06: DB-mining is free but yields **0** for Facebook (all 17 slugs in 6,794 stored posts
were already known — the opposite of WhatsApp, where invite links get shared constantly), and
DuckDuckGo is the **only** engine still returning organic results (Bing/Startpage/Mojeek
captcha-walled, Brave 429). WhatsApp is discovery-only **by design** — there is no logged-out read surface, and
driving WhatsApp Web would risk the user's personal number, so the agent finds the doors and the
user walks through them. If a joined group proves valuable, cover it via notification emails
(the private-Facebook-group trick), never by automation.

**Outreach (`replier.py` + `notifier.py`).** Auto-reply is **Reddit only** — Facebook and LinkedIn
are deliberately excluded because automating the user's account risks a ban, and Freelancer.com was
dropped 2026-08-06 (bid floods, budgets below rate). Safety rails are load-bearing:
`REPLY_MODE=approve` by default (nothing sends without `--approve-reply`), one reply per lead ever
(UNIQUE on `replies.lead_id`), `REPLY_DAILY_CAP`/day, senders no-op when credentials are missing. `notifier.py` falls back to `outbox.log` when Telegram is unconfigured
so nothing is lost.

## config.py — the tuning surface

Nearly all behavior is data in `config.py`, loaded from `.env` via a minimal built-in loader
(`_load_env`, no python-dotenv dependency; env vars win over `.env`). Key regions:

- **Keyword gate regexes** — `_DOMAIN_*`/`_ENGAGE_*` (loose, recall-first), `STRONG_DOMAIN_RE`
  and `SPAM_RE` (kill design/typing/marketing gigs that only matched a weak `AI` tag), and the
  precision gates `FT_RE`/`FLEX_RE` (full-time detection with a flexibility counter-signal),
  `SEEKER_RE`, `COMMUNITY_RE`, `NOISE_RE`, `PARTNER_RE`/`BUDGET_SIGNAL_RE`. All are bilingual
  (English + Hebrew) — keep both languages in sync when editing.
- **Source-behavior sets** — which sources bypass the gate, require a domain match, require
  hiring intent, or are full-time by default. This is how one gate serves job boards, discussion
  communities, and pre-filtered email alerts differently.
- **`FACEBOOK_GROUPS`** — list of `{slug, name, public, region}`. `public` was verified by
  probing logged-out; `public: None` means unprobed (queue in `PROJECT_STATUS.md`). Public groups
  are scraped logged-out; private ones are covered only via notification emails.
- **`TELEGRAM_CHANNELS`**, **`EMAIL_SOURCES`** (sender-domain → source label), scoring rubric
  lives in `scorer.py::SYSTEM_PROMPT`.

## User preferences (encoded throughout — respect them)

1. **Paid freelance / contract / part-time / hourly only.** No full-time (35+ hrs/wk counts as
   full-time even when labeled otherwise). No unpaid/volunteer/community/data-collection asks.
   Equity/co-founder asks go to a separate low-priority `partnership` bucket, not the lead flow.
2. **Low competition matters** — marketplace bid-wars (20+ bids) are near-worthless; direct
   channels (Facebook/Telegram/Reddit DMs) are preferred. Freelancer.com is on trial/skepticism.
3. **Zero cost forever, and never automate the user's Facebook account** (logged-out scraping
   only; email covers the rest).
4. **Based in Israel — remote or on-site-in-Israel only.** Roles locked to another
   country/region with no remote-from-Israel option (US-only, US work authorization/citizenship
   required, LATAM-only, UK-only, on-site abroad) are gated out as `gate_location`; the LLM
   scorer also down-ranks them. Israel / EMEA / worldwide / remote-anywhere survive. Tune via
   `LOCATION_BLOCK_RE` / `LOCATION_OK_RE` in `config.py`.
