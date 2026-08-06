# AgentLead — free lead-generation agent

Monitors freelance/AI communities, filters noise with a keyword gate + free-tier
LLM scoring (1–10), and pushes leads scoring ≥ 8 to your Telegram instantly.
**Every component is free** — no Apify, no VPS, no paid API.

> **Current state, session log and open items: see [PROJECT_STATUS.md](PROJECT_STATUS.md)**

## How each source works (all free)

| Source | Channel | Notes |
|---|---|---|
| Reddit (r/MachineLearningJobs, r/computervision, r/forhire, r/freelance_forhire) | Public RSS feeds (no key), or official API if you add creds | `[For Hire]` posts skipped; RSS path works out of the box with polite rate-limit back-off |
| **Freelancer.com** | Site's public JSON API (no auth) | genuine freelance *projects* with budgets — the best-fit source; queried on your domain keywords |
| **RemoteOK** | Public JSON API (browser UA required) | remote AI/ML/CV jobs by tag |
| **Remotive** | Public JSON API (no auth) | remote jobs with a clean `freelance/contract/full_time` flag; rate-limited ~4/day so polled infrequently |
| **We Work Remotely** | Public RSS feeds | quality remote programming roles |
| **Arbeitnow** | Public JSON API (no auth) | Europe-centric; explicit Freelance/Contract job types |
| **Working Nomads** | Public JSON API (no auth) | curated remote dev jobs |
| **Himalayas** | Public JSON API (no auth) | large remote pool with employment-type field |
| Hacker News "Who is hiring?" + "Freelancer? Seeking freelancer?" | Algolia public API | whole thread in 1 request; the freelancer thread is community-run again since Apr 2026 |
| **Braintrust** | Public JSON API (no auth) | 100%-freelance marketplace with hourly USD rates — top-quality source |
| **Telegram channels** (israjobs, hightechforolims, remote_ai_jobs, ...) | Public t.me/s/ previews (no login) | list in `config.TELEGRAM_CHANNELS`; only channels with public preview work |
| **Jobspresso** | Keyword-filtered RSS | ML/CV/AI keyword feeds |
| **aijobs.net** | Server-rendered HTML + CSRF POST filters (their old RSS/API is dead) | dedicated AI/ML board; we pull newest + Computer-Vision + Middle-East views |
| **Company career boards** (Lightricks, Aidoc, Trigo, Pixellot, Hailo, Cortica, Nanox, Scale, Hugging Face, Viz.ai, ...) | Greenhouse/Comeet/Workable/Ashby public JSON APIs | curated Israeli-CV + AI-data companies; list in `fetchers/companies_fetcher.py` |
| Facebook groups | **Logged-out scraper** (public groups) + **notification emails** (all groups) | scraper never logs in → account safe; email covers private groups |
| Upwork | **Saved-search alert emails → Gmail IMAP** | RSS was killed in 2024; scraping risks your account |
| Wellfound | **Job-alert emails → Gmail IMAP** | site is DataDome-protected; email is the free path |
| **LinkedIn** | **Job-alert emails → Gmail IMAP** *(robust)* + logged-out `jobs-guest` endpoints *(best-effort)* | no login either way. The guest filters are unreliable, so the full-time gate does the real filtering; see setup below |
| **Reddit sitewide search** | Public `search.rss` (no key) | `title:(hiring OR task)` queries catch gigs in subs we don't poll; list in `config.REDDIT_SEARCHES` |
| **WhatsApp groups** | **Discovery only** — `discover_whatsapp_groups.py` | finds joinable invite links; **you join by hand**, the account is never automated |
| X-Place | Site's own public JSON API | 25 newest projects per poll |
| Secret Tel Aviv jobs board | Plain HTML (WPJobBoard) | full description fetched for relevant titles |

Scoring: **Gemini API free tier** (~1,500 req/day, no credit card) or local
**Ollama** for a fully offline option. Notifications: **Telegram bot** (free).

## Setup (~20 minutes, all free)

```
pip install -r requirements.txt
copy .env.example .env     # then fill it in, step by step below
```

### 1. Telegram (2 min) — required for notifications
1. In Telegram, message **@BotFather** → `/newbot` → copy the token into `TELEGRAM_BOT_TOKEN`.
2. Send your new bot any message ("hi").
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser → copy the
   `"chat":{"id":...}` number into `TELEGRAM_CHAT_ID`.
4. Test: `python main.py --test-telegram`

### 2. Gemini API key (1 min) — required for scoring
1. Go to https://aistudio.google.com → **Get API key** (free, no credit card).
2. Put it in `GEMINI_API_KEY`.
3. Test: `python main.py --score-test "Looking for a freelancer to build an OCR pipeline for invoices, budget $3000"`

*(Fully offline alternative: install [Ollama](https://ollama.com), `ollama pull qwen2.5:7b`,
set `LLM_BACKEND=ollama`.)*

### 3. Reddit app (2 min)
1. https://www.reddit.com/prefs/apps → **create another app** → type **script**,
   redirect uri `http://localhost:8080`.
2. The string under the app name = `REDDIT_CLIENT_ID`; the secret = `REDDIT_CLIENT_SECRET`.

### 4. Gmail app password (2 min) — enables Facebook, Upwork, Wellfound
1. Google Account → **Security** → enable **2-Step Verification** (if not already).
2. Security → **App passwords** → create one for "Mail" → put the 16-char code
   in `IMAP_PASSWORD`, your Gmail address in `IMAP_USER`.

### 5b. (Optional) Enable the Facebook public-group scraper
Free and account-safe (it never logs in), covers the 10 verified public groups:
```
pip install playwright
playwright install chromium
```
Then set `FB_PUBLIC_ENABLED=1` in `.env`. It self-limits to 3 runs/day with
delays between groups. Leave it at `0` to rely purely on notification emails.
**Risk model:** logged-out scraping can't get your account banned — worst case
is a temporary IP block, after which the scraper backs off and the email channel
still covers those groups. Keep the defaults; don't raise `FB_MAX_RUNS_PER_DAY`.

### 5. Turn on the alert emails (5–10 min, one time)
- **Facebook**: open each group → *Joined* → *Manage notifications* → **All posts**.
  Groups to enable: freelance.hightech, the ML-jobs groups, and the rest of your list.
- **Upwork**: create saved searches (e.g. `computer vision`, `OCR`, `image processing`,
  `machine learning`) → enable **email alerts** for each.
- **Wellfound**: set up job alerts for contract/ML roles → email notifications on.
- **LinkedIn** (this is the *reliable* half of the LinkedIn integration — the
  logged-out scraper can be bot-walled at any time, but LinkedIn can't block its
  own emails):
  1. linkedin.com/jobs → search each keyword (`computer vision`, `OCR`,
     `machine learning`, `data visualization`).
  2. Filters: **Job type = Contract + Part-time + Temporary**, **Remote**.
     LinkedIn requires *a* location, so make one alert each for **Israel**,
     **United States** (+Remote) and **European Union**.
  3. Toggle **Set alert** → frequency **Daily** → delivery **Email**.
  4. In Gmail: filter `from:(jobalerts-noreply@linkedin.com)` → **Never send to
     Spam**. (The Updates tab is fine — IMAP reads all of INBOX.)

That's it — the agent reads those emails over IMAP and treats each post/job as a lead.

## WhatsApp groups (discovery only)

WhatsApp has no logged-out read surface — you can't see a group's messages
without joining, and driving WhatsApp Web from a script risks a ban on your
personal number. So the agent stops at **discovery**: it finds joinable groups
and ranks them; **you decide which to join, by hand**. Same rule as Facebook.

```
python -X utf8 discover_whatsapp_groups.py            # mine stored posts + validate
python -X utf8 discover_whatsapp_groups.py --search   # + Reddit/DuckDuckGo search
python -X utf8 discover_whatsapp_groups.py --write    # + whatsapp_groups.md (ranked table)
python -X utf8 discover_whatsapp_groups.py --joined <code>   # mark one as joined
```

Where the invite links come from, cheapest first:
- **Stored posts** (`mine_db`, zero network) — Telegram and Facebook posts share
  invite links constantly. **This is the best surface**: on the first run it found
  the Israeli dev-jobs group `GCV - משרות פיתוח לבעלי ניסיון` without a single
  request. It runs daily as part of the scheduler.
- **Reddit search** — keyless and reliable, but *high-volume and low-signal*: it
  mostly returns student-cohort and internship groups ("M.Tech Data Science 2026")
  that match the keywords but never carry client work. Worth running occasionally
  (`--search`), not daily.
- **DuckDuckGo** — captcha-walls datacenter IPs; it detects the challenge and
  skips rather than failing, and may work better from your home connection.

Each invite is validated logged-out: a live one exposes the group name via
`og:title`, a revoked one comes back empty. Results live in the `whatsapp_groups`
table, ranked by keyword hits in the group name (bilingual — Israeli groups name
themselves in Hebrew), with course/internship/cohort groups forced to the bottom.
The daily `whatsapp` job re-mines new posts and Telegram-pings you only about new
groups that actually look relevant.

**If you join groups that turn out to carry good leads**, don't automate reading
them — use the same trick as private Facebook groups: turn on notifications and
let the email pipeline ingest them.

## Facebook groups

The agent covers Facebook two ways: a **logged-out scraper** for *public* groups
(zero account risk — never logs in; see risk notes below) and **notification
emails** for any group you've joined (works for private groups too). The list
lives in `config.py` → `FACEBOOK_GROUPS`. Enable the scraper with
`FB_PUBLIC_ENABLED=1`.

**Verified public** (scraped, logged-out — probed 2026-07-04):

| Region | Group | slug/id |
|---|---|---|
| IL | פרילנסרים בהייטק | `freelance.hightech` |
| IL | משרות פרילאנסר/שכיר בRemote | `197859277728196` |
| IL | ML & Data Science Jobs Israel | `ml.jobs.il` |
| IL | דרושים מתכנתים ואנשי פיתוח | `1920854911477422` |
| IL | Machine & Deep Learning Israel (MDLI) | `MDLI1` |
| IL | Israel Freelance Developers | `367262456327` |
| IL | Freelancers Networking - Israel | `freelancersnetworkingIL` |
| IL | Fullstack Developers Israel | `fullstack.developers.israel` |
| IL | דרושים פרילנסרים וטאלנטים בדיגיטל | `1129872654348077` |
| US/global | Data Science / ML / AI Freelance Jobs | `2954760687901402` |

**Verified private** (email channel only — you must join + turn on notifications):

| Region | Group | slug/id |
|---|---|---|
| IL | מתכנתים פרילנסרים | `1502756793303704` |
| IL | Computer Vision Israel | `1831991027038183` |
| US | Remote Jobs & Projects for Developers | `539394463145974` |
| global | Referral - Data Science & Analytics Jobs | `datasciencejob` |

### Facebook groups — candidates to verify (2 min each, while logged in)

Research surfaced these but they returned a bare "Facebook" page when probed
logged-out (wrong slug, or not publicly viewable). Open each while logged in; if
it's a real, active, relevant group, add it to `FACEBOOK_GROUPS` in `config.py`
(`public: True` if you can see posts logged out, else `False`):

- **Israel** — משרות הייטק בין חברים (`israel.hightech`, ~60k, the big one — worth
  finding the correct URL), spillover group `2520202001380275`, Python Jobs Israel
  (`676381365752971`), דרושים - עבודות פרילנסרים (`458346604817578`)
- **USA/global** — Data Science/Machine Learning Jobs (`148870019838894`),
  Remote Tech Jobs (`remotestartupjobs`), WordPress Freelancers & Developers
  (`417156235300771`), IT Jobs Canada/USA/UK (`itiljobs`), Freelance Web
  Designers & Developers (`clicke`), Computer Vision and Image Processing
  (`computervisionandimageprocessing`) — mostly discussion, low gig volume
- **UK** — Freelancers Unite! UK / Freelance Heroes (`freelanceheroes`, private —
  join for the email channel), Software Developer Jobs London/UK
  (`devitjobsgroup`), UK Software Developers Group (`UK.Software.Developers`),
  Freelancers UK (`freelanceuk`)

To (re)check a slug quickly: open `https://www.facebook.com/groups/<slug>/` in a
private/incognito window. If you see posts → public; if it demands login → private.

## Running

```
python main.py --once     # single pass of all fetchers (good first test)
python main.py            # run forever (poll loop + daily digest at 18:00)
python main.py --stats    # what's in the database
python main.py --export-csv leads.csv                # export ALL leads to CSV
python main.py --export-csv strong.csv --min-score 8 # only leads scoring >= 8
python main.py --export-html leads.html              # filterable HTML lead browser
```

`--export-html` writes a self-contained page (open in any browser): live text
filter, min-score / source / contacted dropdowns, green highlighting for
score >= 8, plus an **outreach tracker** - a "contacted" checkbox and a notes
field per lead, saved in the browser (localStorage), surviving re-exports.

### After you add the Gemini key (one time)
```
python -X utf8 main.py --score-backlog        # scores up to 300 stored leads (~35 min, free tier)
python -X utf8 main.py --export-html leads.html
```
Backlog scoring pushes Telegram alerts only for score>=8 leads fetched in the
last 5 days (older gigs are likely filled); everything else lands in the DB and
exports. From then on the normal loop scores every new lead automatically.

Tip: on Windows always run with `python -X utf8` (Hebrew posts break the
default console encoding); `run.bat` already does this.

CSV is written with a UTF-8 BOM so Hebrew opens correctly in Excel. Columns:
score, source, category, work_type, summary, budget, red_flags, status,
posted_at, url, author, raw_text.

To keep it running in the background on Windows: Task Scheduler → Create Basic Task →
*At log on* → Start a program → `run.bat` in this folder. (Or just leave a
terminal open with `python main.py`.)

## Auto-reply (Reddit + Freelancer.com)

For the two channels with legitimate posting APIs, the agent can answer leads
for you. When a lead scores >= `REPLY_MIN_SCORE` (default 8), the LLM reads the
post against your standing `REPLY_DIRECTION` (which kinds of leads to answer,
what to skip), decides yes/no, and drafts a personalized reply in the post's
language. Facebook is deliberately excluded (automating your account risks a
ban); other sources have no posting API - for those you get the drafted pitch
in the Telegram push and send it yourself.

```
python main.py --reply-test 541       # dry-run: see what it would write for a lead
python main.py --replies              # list drafted replies waiting for approval
python main.py --approve-reply 3      # approve + send one (or: --approve-reply all)
```

- **Reddit**: DMs the poster by default (`REDDIT_REPLY_VIA=comment` to comment
  publicly instead). Needs your Reddit username+password in .env (script app).
- **Freelancer.com**: places a real bid (amount = budget midpoint, or `min`),
  with the drafted text as the proposal. Needs a free token from
  developers.freelancer.com. Bids consume your normal monthly bid quota.
- Safety: `REPLY_MODE=approve` by default (nothing sends without you),
  `REPLY_DAILY_CAP` sends/day, one reply per lead ever, all attempts logged.
  Set `REPLY_MODE=auto` only after you've reviewed a few batches of drafts.

## What you'll get

- **Score ≥ 8** → instant Telegram push: score, category, 2-sentence summary,
  budget if mentioned, red flags, direct link.
- **Score 6–7** → one daily digest message at 18:00.
- **Score ≤ 5** → stored in `leads.db` only (so you can audit misses and tune).

## Tuning

- Keywords / Hebrew terms: `config.py` (`_DOMAIN_*`, `_ENGAGE_*` lists).
- Scoring rubric: `scorer.py` (`SYSTEM_PROMPT`) — edit freely; it's plain text.
- Thresholds & digest hour: `.env` (`PUSH_THRESHOLD`, `DIGEST_THRESHOLD`, `DIGEST_HOUR`).
- Poll intervals: `JOBS` list at the bottom of `main.py`.

## Free-tier limits you're operating inside

- **Gemini free tier**: ~10 req/min, ~1,500/day ([limits](https://ai.google.dev/gemini-api/docs/rate-limits)).
  The scorer self-throttles to 1 call / 6.5 s; the keyword gate keeps daily volume
  in the low hundreds at most.
- **Reddit free tier**: ~60–100 req/min — this agent uses 4 per 15 minutes.
- **Telegram / HN Algolia / X-Place / IMAP**: no meaningful limits at this volume.
