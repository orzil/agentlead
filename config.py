"""Configuration: loads .env, defines keywords and source settings.

Everything in this project is free-tier only:
  - LLM scoring:  Google Gemini free tier (or local Ollama)
  - Notifications: Telegram bot API
  - Reddit:        official API free tier
  - HN:            Algolia public API
  - Facebook/Upwork/Wellfound: email alerts parsed over Gmail IMAP
  - X-Place / Secret Tel Aviv: public endpoints
"""
from __future__ import annotations

import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "leads.db"
LOG_PATH = BASE_DIR / "agent.log"


def _load_env(path: Path) -> None:
    """Minimal .env loader (no dependency). Lines: KEY=VALUE, # comments."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_env(BASE_DIR / ".env")


def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


# --- Telegram ---------------------------------------------------------------
TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = env("TELEGRAM_CHAT_ID")

# --- LLM backend ------------------------------------------------------------
# "gemini" (free API key from https://aistudio.google.com) | "ollama" | "none"
LLM_BACKEND = env("LLM_BACKEND", "gemini").lower()
GEMINI_API_KEY = env("GEMINI_API_KEY")
# Tried in order; first one available on the account wins.
GEMINI_MODEL_PREFERENCE = [
    m.strip()
    for m in env(
        "GEMINI_MODELS",
        # gemini-2.5-flash removed 2026-08-06: "no longer available to new users".
        # The *-latest aliases point at preview models whose free-tier daily
        # request budget is tiny, so the stable 2.0 models come first.
        "gemini-2.0-flash,gemini-2.0-flash-lite,gemini-flash-latest,gemini-3-flash",
    ).split(",")
    if m.strip()
]
OLLAMA_URL = env("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = env("OLLAMA_MODEL", "qwen2.5:7b")
# Hybrid scoring: use Gemini while its (small) free daily quota lasts, then fall
# back to local Ollama, which has no quota at all. Gemini gives the better
# judgement; Ollama gives unlimited volume - together they clear a backlog that
# neither could alone. No-ops harmlessly where Ollama isn't installed (e.g. the
# GitHub Actions runner), because the fallback swallows connection errors.
LLM_FALLBACK_OLLAMA = env("LLM_FALLBACK_OLLAMA", "1") in ("1", "true", "yes")

# --- Reddit -----------------------------------------------------------------
REDDIT_CLIENT_ID = env("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = env("REDDIT_CLIENT_SECRET")
REDDIT_USER_AGENT = env("REDDIT_USER_AGENT", "windows:lead-agent:v1.0 (personal lead monitor)")
# Needed only for AUTO-REPLY (posting). Script-app password grant; 2FA must be
# off on the account (or use an app-specific arrangement).
REDDIT_USERNAME = env("REDDIT_USERNAME")
REDDIT_PASSWORD = env("REDDIT_PASSWORD")
REDDIT_REPLY_VIA = env("REDDIT_REPLY_VIA", "dm")  # dm | comment
SUBREDDITS = ["MachineLearningJobs", "computervision", "forhire",
              "freelance_forhire", "DataScienceJobs", "BigDataJobs",
              # job subs -> loose default gate (a domain OR engage term passes)
              "PythonJobs",
              # discussion / firehose subs -> listed in INTENT_REQUIRED_SOURCES
              # below, so they need DOMAIN *and* ENGAGE to become candidates
              "hiring", "AI_Agents", "n8n", "automation", "deeplearning",
              "LocalLLaMA"]

# Sitewide Reddit search (search.rss, no key needed) - catches hiring posts in
# subs we don't poll.
#
# The `title:` field qualifier is what makes this usable: a plain keyword search
# ranks semantically and returns career-advice threads, seeker self-promos and
# SEO listicles (measured: 14/20 passed the gate, 0 were real leads). Anchoring
# on Reddit's title convention - [Hiring] = seeking someone, [Task] = paid task -
# surfaces actual gigs with budgets instead. r/search stays in
# INTENT_REQUIRED_SOURCES as the second line of defence.
REDDIT_SEARCHES = [
    'title:(hiring OR task) ("computer vision" OR OCR OR "image processing" OR "object detection")',
    'title:(hiring OR task) ("machine learning" OR "deep learning" OR "data science" OR "data visualization")',
    'title:(hiring OR task) (LLM OR RAG OR chatbot OR "AI agent" OR automation)',
]

# --- LinkedIn ---------------------------------------------------------------
# Logged-out "jobs-guest" endpoints; no account, no key. Searched with
# f_JT=P,C,T (part-time/contract/temporary) - but LinkedIn applies that filter
# loosely, so the FT gate still does the real work downstream.
LINKEDIN_QUERIES = ["computer vision", "OCR", "image processing",
                    "machine learning", "deep learning", "data visualization"]
# Israel searches run without the remote filter, so on-site IL gigs surface too
LINKEDIN_IL_QUERIES = ["machine learning", "computer vision", "algorithm"]
# Descriptions cost one request each; the rest roll over to the next run.
LINKEDIN_DETAIL_CAP = int(env("LINKEDIN_DETAIL_CAP", "15"))

# --- LinkedIn "Easy Apply" pass (f_AL=true) ----------------------------------
# Measured 2026-08-06 against the live guest endpoint: f_AL=true IS honoured
# (only 3/10 job ids overlapped the unfiltered baseline), unlike f_JT, which was
# ignored outright (10/10 identical to baseline, and every detail page said
# "Employment type: Full-time"). Easy Apply is therefore targetable at the QUERY
# level only - it cannot be detected per-job, because the logged-out detail page
# shows the same sign-in modal chrome
# ("apply-link-offsite...contextual-sign-in-modal") on every single job, with no
# applyUrl and no "Easy Apply" string. So the flag comes from which query found
# the job, never from parsing the page.
#
# Easy Apply skews heavily full-time, so expect most of this pass to gate out as
# gate_full_time - that is correct, not a bug. If the pass yields ~0 real leads
# over a few days, drop it rather than loosening FT_RE; no-full-time is a hard
# user rule. Volume is lower than the main pass, hence the 7-day window.
LINKEDIN_EASYAPPLY = env("LINKEDIN_EASYAPPLY", "1") in ("1", "true", "yes")
LINKEDIN_EASYAPPLY_QUERIES = ["computer vision", "machine learning",
                              "AI engineer", "data visualization"]
LINKEDIN_EASYAPPLY_TPR = env("LINKEDIN_EASYAPPLY_TPR", "r604800")  # 7 days

# --- Gmail IMAP (Facebook notifications, Upwork/Wellfound/LinkedIn alerts) ---
IMAP_HOST = env("IMAP_HOST", "imap.gmail.com")
IMAP_USER = env("IMAP_USER")            # your gmail address
IMAP_PASSWORD = env("IMAP_PASSWORD")    # Gmail *app password*, not your real one
IMAP_FOLDER = env("IMAP_FOLDER", "INBOX")
IMAP_LOOKBACK_DAYS = int(env("IMAP_LOOKBACK_DAYS", "3"))

# --- Facebook groups --------------------------------------------------------
# public=True  -> scraped logged-out by facebook_public_fetcher (zero account risk)
# public=False -> private/closed; covered ONLY via email notifications
# Enable the scraper with FB_PUBLIC_ENABLED=1 in .env (Playwright required).
# "public" flags were verified by probing each group logged-out on 2026-07-04;
# re-check occasionally, as groups can flip their privacy setting.
FACEBOOK_GROUPS = [
    # --- Israel (the 6 you provided) ---
    {"slug": "freelance.hightech",   "name": "פרילנסרים בהייטק",                       "public": True,  "region": "IL"},
    {"slug": "197859277728196",      "name": "משרות פרילאנסר/שכיר בRemote",            "public": True,  "region": "IL"},
    {"slug": "ml.jobs.il",           "name": "ML & Data Science Jobs Israel",         "public": True,  "region": "IL"},
    {"slug": "1920854911477422",     "name": "דרושים מתכנתים ואנשי פיתוח",             "public": True,  "region": "IL"},
    {"slug": "1502756793303704",     "name": "מתכנתים פרילנסרים",                       "public": False, "region": "IL"},
    {"slug": "1831991027038183",     "name": "Computer Vision Israel",                "public": False, "region": "IL"},

    # --- Additional groups found by research and PROBED logged-out on 2026-07-04 ---
    # Israel (public, scraper-eligible):
    {"slug": "MDLI1",                       "name": "Machine & Deep Learning Israel",       "public": True,  "region": "IL"},
    {"slug": "367262456327",                "name": "Israel Freelance Developers",          "public": True,  "region": "IL"},
    {"slug": "freelancersnetworkingIL",     "name": "Freelancers Networking - Israel",      "public": True,  "region": "IL"},
    {"slug": "fullstack.developers.israel", "name": "Fullstack Developers Israel",          "public": True,  "region": "IL"},
    {"slug": "1129872654348077",            "name": "דרושים פרילנסרים וטאלנטים בדיגיטל",     "public": True,  "region": "IL"},
    # Global / USA (public, scraper-eligible):
    {"slug": "2954760687901402",            "name": "Data Science / ML / AI Freelance Jobs","public": True,  "region": "US"},
    # Confirmed PRIVATE (leads only via email, and only if you join + enable notifications):
    {"slug": "539394463145974",             "name": "Remote Jobs & Projects for Developers","public": False, "region": "US"},
    {"slug": "datasciencejob",              "name": "Referral - Data Science Jobs Worldwide","public": False, "region": "US"},

    # --- Round 2 research, PROBED 2026-07-06 ---
    # Verified PUBLIC (scraped):
    {"slug": "590668817677341",          "name": "דרושים מפתחי אפליקציות",          "public": True,  "region": "IL"},
    {"slug": "983052298867811",          "name": "דרושים מפתחים ומתכנתים",          "public": True,  "region": "IL"},
    {"slug": "279218118861800",          "name": "זירת פרילנסרים",                  "public": True,  "region": "IL"},
    # Verified PRIVATE (email channel only - join + enable notifications):
    {"slug": "1644220639231386",         "name": "מפתחים בשביל אחוזים",             "public": False, "region": "IL"},
    {"slug": "458346604817578",          "name": "דרושים - עבודות פרילנסרים",       "public": False, "region": "IL"},
    {"slug": "appsentrepreneur",         "name": "קהילת יזמים/סטארטאפים (Apps)",    "public": False, "region": "IL"},
    {"slug": "aimlpljobs",               "name": "AI/ML/Data Mining/Chatbots JOBS", "public": False, "region": "US"},
    {"slug": "aiautomationexperts",      "name": "AI Automation Experts",          "public": False, "region": "US"},
    {"slug": "saasfoundersnetwork",      "name": "SaaS Founders",                  "public": False, "region": "US"},
    {"slug": "LDNstartups",              "name": "London Startups",                "public": False, "region": "UK"},
    # PROBED 2026-07-12 (round 3) - verified PUBLIC:
    {"slug": "webJobsIsrael",            "name": "משרות WEB",                       "public": True,  "region": "IL"},
    {"slug": "DevJobsJLM",               "name": "Jobs for Devs JLM (Jerusalem)",   "public": True,  "region": "IL"},
    {"slug": "aisrael",                  "name": "AI ISRAEL - בינה מלאכותית",       "public": True,  "region": "IL"},
    {"slug": "676381365752971",          "name": "Python Jobs (Israel)",           "public": True,  "region": "IL"},
    {"slug": "148870019838894",          "name": "Data Science/ML Jobs",           "public": True,  "region": "US"},
    {"slug": "aijobsgroup",              "name": "AI gigs - Jobs in AI",           "public": True,  "region": "US"},
    # verified PRIVATE (email channel only):
    {"slug": "Mobile.Developers.Israel", "name": "Mobile Developers Israel",        "public": False, "region": "IL"},
    {"slug": "111444215533299",          "name": "עבודה למפתחי אינטרנט (Web Devs IL)","public": False, "region": "IL"},
    # STILL UNRESOLVED (throttle hit mid-probe both rounds; probe these FIRST
    # next time, before any other group):
    {"slug": "developersmeetstartups",   "name": "מתכנתים פוגשים סטארטאפים",        "public": None, "region": "IL"},
    {"slug": "1271378943826323",         "name": "AI Agents Developer Community",   "public": None, "region": "US"},
    {"slug": "chatbotjobs",              "name": "Chatbot Jobs - Freelance",       "public": None, "region": "US"},
    {"slug": "makeautomation",           "name": "Make (Integromat) Automation",   "public": None, "region": "US"},
    {"slug": "nodemation",               "name": "n8n Automation Community",        "public": None, "region": "US"},
    {"slug": "2133987156657804",         "name": "Freelance Developers and Projects","public": None, "region": "US"},
    {"slug": "Founder.CEOs",             "name": "Founder & CEOs",                 "public": None, "region": "US"},
    {"slug": "foundersspace",            "name": "Founders Space",                 "public": None, "region": "US"},
    {"slug": "UK.Software.Developers",   "name": "UK Software Developers Group",    "public": True, "region": "UK"},  # probed 2026-07-14
    {"slug": "ukstartupsgroup",          "name": "UK Startups Group",              "public": True, "region": "UK"},  # probed 2026-07-14
    # Round 4 research (2026-07-12): slugs VERIFIED to exist (title-tag or
    # Google-indexed snippet at the exact URL). public=None until probed.
    # Skipped on purpose: generic "freelance jobs" volume groups (spam farms).
    {"slug": "aibusinesstools",          "name": "AI Agents | n8n | Automation",    "public": None, "region": "US"},  # indexed posts are literal client gigs
    {"slug": "aiautomationagency.aaa",   "name": "AI Automation Agency",           "public": None, "region": "US"},
    {"slug": "3501761776707095",         "name": "AI Automation Agency Entrepreneurs","public": None, "region": "US"},
    {"slug": "ComputerVisionGroup",      "name": "Computer Vision",                "public": None, "region": "US"},
    {"slug": "remotestartupjobs",        "name": "Remote Tech Jobs",               "public": None, "region": "US"},
    {"slug": "inventivehub",             "name": "Remote Jobs - Inventive Hub",    "public": None, "region": "US"},
    {"slug": "556739801135588",          "name": "Jobs for Front-End Developers",   "public": None, "region": "US"},
    {"slug": "361717460552082",          "name": "Freelance KDP & Web Developers",  "public": None, "region": "US"},
    {"slug": "findyourcofounder",        "name": "Find Your Co founder",           "public": None, "region": "US"},
    {"slug": "freelanceuk",              "name": "Freelancers UK",                 "public": False, "region": "UK"},  # probed 2026-07-14: private
    {"slug": "devitjobsgroup",           "name": "Software Developer Jobs London/UK","public": True, "region": "UK"},  # probed 2026-07-14
]

# --- Public Telegram channels (read logged-out via t.me/s/<handle>) ----------
# Only channels VERIFIED to serve a public preview (probed 2026-07-06).
# Preview-disabled channels return a join-stub and are not listed here.
TELEGRAM_CHANNELS = [
    "israjobs",          # HighTech Israel Jobs (12.9K, RU/EN, active)
    "hightechforolims",  # Israeli hi-tech for olim (5.9K, EN, active)
    "gocodejobs",        # GoCode משרות (Hebrew, freelance-style posts, semi-active)
    "remote_ai_jobs",    # Remote AI/ML/DS jobs (7.6K, structured posts, active)
    "remotejobss",       # Remote Jobs firehose (154K, all fields - domain gate filters)
    "datasciencej",      # Data Science Jobs (8.3K, medium noise)
    # round 2 (verified 2026-07-06):
    "jobswipe",          # ערוץ המשרות הגדול - big Israeli jobs feed (Hebrew, daily)
    "jobs_sql",          # Data analyst / SQL / BI jobs (EN)
    "datajob",           # DS/ML/AI vacancies (RU, tech terms in EN - gate still works)
    "datasciencejobs",   # DS/AI vacancies #ai (RU/EN mix)
    "geekjobs",          # IT&Digital jobs w/ ATS links (RU/EN mix)
]

# sender-domain -> source label
# linkedin.com also sends invitations/InMail; those carry no /jobs/view/ links,
# so they parse to zero leads and cost nothing.
EMAIL_SOURCES = {
    "facebookmail.com": "facebook",
    "upwork.com": "upwork",
    "wellfound.com": "wellfound",
    "hi.wellfound.com": "wellfound",
    "angel.co": "wellfound",
    "linkedin.com": "linkedin/alert",
}

# --- Facebook group DISCOVERY (discover_fb_groups.py) -------------------------
# Finds groups that aren't in FACEBOOK_GROUPS yet. Probed 2026-08-06: DuckDuckGo
# HTML is the ONLY search engine still returning organic results from this IP
# (Bing, Startpage, Mojeek captcha-walled; Brave 429'd), so it is the single
# network surface - it degrades gracefully when it walls.
#
# Hebrew queries are load-bearing, not a nicety: Israeli clients post work in
# Hebrew, and the English-only queries never surface those groups.
FB_DDG_QUERIES = [
    # --- Israel: client-side groups (business owners posting work) ---
    'site:facebook.com/groups פרילנסרים',
    'site:facebook.com/groups "דרוש מתכנת"',
    'site:facebook.com/groups "דרוש מפתח"',
    'site:facebook.com/groups "מחפש מפתח" פרויקט',
    'site:facebook.com/groups דרושים תוכנה ישראל',
    'site:facebook.com/groups סטארטאפים יזמים ישראל',
    'site:facebook.com/groups "בינה מלאכותית" ישראל',
    'site:facebook.com/groups אוטומציה עסקים ישראל',
    'site:facebook.com/groups "ראייה ממוחשבת" OR "עיבוד תמונה"',
    'site:facebook.com/groups משרות הייטק פרילנס',
    # --- ENGLISH-SPEAKING WORLD, CLIENT SIDE (rewritten 2026-08-08) ---
    #
    # The old US/UK queries asked for DEVELOPER COMMUNITIES and that is exactly
    # why they failed: 0 good leads from 44 posts, while the Israeli "דרושים"
    # (wanted) groups produced all 10. The difference was never the country - it
    # is WHO POSTS. Devs talking to devs is not a lead source; founders and
    # business owners looking for someone to build a thing is.
    #
    # So every query below targets the buyer's phrasing, not the builder's, and
    # names like "Developers Group" / "Programmers Community" are deliberately
    # absent. Or works remotely, so all English-speaking markets qualify.
    'site:facebook.com/groups "looking for a developer"',
    'site:facebook.com/groups "need a developer" project',
    'site:facebook.com/groups "need an app built"',
    'site:facebook.com/groups "hire a freelancer" business',
    'site:facebook.com/groups startup founders network',
    'site:facebook.com/groups "SaaS founders"',
    'site:facebook.com/groups "agency owners" automation',
    'site:facebook.com/groups "small business owners" automation AI',
    'site:facebook.com/groups ecommerce store owners help',
    'site:facebook.com/groups entrepreneurs need help building',
    'site:facebook.com/groups "no code" founders build',
    'site:facebook.com/groups "AI automation agency" clients',
    'site:facebook.com/groups n8n OR make.com automation business',
    'site:facebook.com/groups outsourcing software projects clients',
    'site:facebook.com/groups "computer vision" OR OCR project help',
    # market-specific, same client-side framing
    'site:facebook.com/groups startup founders UK',
    'site:facebook.com/groups small business owners UK tech help',
    'site:facebook.com/groups startup founders Canada',
    'site:facebook.com/groups Australia business owners tech help',
    'site:facebook.com/groups "New Zealand" business owners website app',
    'site:facebook.com/groups Ireland startups founders',
    'site:facebook.com/groups "South Africa" business owners tech',
    'site:facebook.com/groups Singapore startups founders',
    'site:facebook.com/groups Dubai OR UAE entrepreneurs tech',

    # === EXPANSION 2026-08-09, after Or joined the first shortlist ===========
    # Three axes, because a single phrasing only ever finds one shape of group:
    # (1) more Hebrew phrasings, (2) US verticals - a client identifies by their
    # INDUSTRY ("Shopify store owners"), not by the technology they need, and
    # (3) the AI-tooling communities where automation buyers now congregate.

    # --- Israel, more phrasings ---
    'site:facebook.com/groups "מחפש פרילנסר"',
    'site:facebook.com/groups "דרושים מתכנתים"',
    'site:facebook.com/groups "בעלי עסקים" ישראל טכנולוגיה',
    'site:facebook.com/groups "בעלי עסקים קטנים" ישראל',
    'site:facebook.com/groups יזמים דיגיטליים ישראל',
    'site:facebook.com/groups "חנויות אונליין" OR "מסחר אלקטרוני" ישראל',
    'site:facebook.com/groups שיווק דיגיטלי ישראל בעלי עסקים',
    'site:facebook.com/groups "פיתוח אפליקציות" ישראל',
    'site:facebook.com/groups נדל"ן טכנולוגיה ישראל יזמים',
    'site:facebook.com/groups "סטארטאפ ישראלי" מייסדים',
    'site:facebook.com/groups "מיקור חוץ" פיתוח ישראל',
    'site:facebook.com/groups קהילת יזמים ישראל',

    # --- US / worldwide verticals: the buyer names their industry ---
    'site:facebook.com/groups "Shopify store owners"',
    'site:facebook.com/groups "Amazon FBA" sellers',
    'site:facebook.com/groups "real estate investors" technology',
    'site:facebook.com/groups "insurance agency" owners automation',
    'site:facebook.com/groups "law firm" owners technology',
    'site:facebook.com/groups "medical practice" owners software',
    'site:facebook.com/groups "restaurant owners" technology',
    'site:facebook.com/groups "construction" business owners software',
    'site:facebook.com/groups "logistics" OR "trucking" business owners software',
    'site:facebook.com/groups "manufacturing" business owners automation',
    'site:facebook.com/groups "coaches" OR "consultants" automation clients',
    'site:facebook.com/groups "marketing agency owners"',
    'site:facebook.com/groups "digital agency" owners outsourcing',
    'site:facebook.com/groups "ecommerce entrepreneurs"',
    'site:facebook.com/groups "dropshipping" store owners help',

    # --- AI tooling communities: where automation buyers gather now ---
    'site:facebook.com/groups "n8n" community',
    'site:facebook.com/groups "make.com" OR integromat community',
    'site:facebook.com/groups zapier automation community',
    'site:facebook.com/groups "GPT" builders business',
    'site:facebook.com/groups "AI agents" business owners',
    'site:facebook.com/groups "ChatGPT for business"',
    'site:facebook.com/groups "AI tools" for entrepreneurs',
    'site:facebook.com/groups "prompt engineering" business',
    'site:facebook.com/groups "computer vision" OR "image recognition" business',
    'site:facebook.com/groups "document automation" OR "invoice automation"',

    # --- more English markets ---
    'site:facebook.com/groups "United States" small business owners tech',
    'site:facebook.com/groups Texas OR Florida business owners technology',
    'site:facebook.com/groups "New York" startups founders tech',
    'site:facebook.com/groups California startup founders',
    'site:facebook.com/groups Toronto OR Vancouver startups founders',
    'site:facebook.com/groups Sydney OR Melbourne business owners tech',
    'site:facebook.com/groups India startups founders outsourcing',
    'site:facebook.com/groups Europe remote startup founders',
    'site:facebook.com/groups "Middle East" entrepreneurs technology',
    'site:facebook.com/groups "remote work" entrepreneurs hiring',
]

# --- Facebook POST search (fbsearch_fetcher) ---------------------------------
# Finds individual posts through the search index instead of scraping Facebook,
# which is impossible from any datacenter IP (measured: every surface redirects
# to login.php, 0 leads across three cloud runs). Zero facebook.com requests.
#
# Intent phrasing, not topic phrasing: a client writes "looking for a developer",
# never "computer vision engineer wanted". Bilingual, because the Israeli half of
# the pipeline is where the measured yield is.
FB_POST_INTENT_QUERIES = [
    'site:facebook.com/groups "looking for a developer"',
    'site:facebook.com/groups "need a developer"',
    'site:facebook.com/groups "need an app built"',
    'site:facebook.com/groups "looking for a freelancer" project',
    'site:facebook.com/groups "anyone know a developer"',
    'site:facebook.com/groups "computer vision" freelance project',
    'site:facebook.com/groups OCR "extract data" project',
    'site:facebook.com/groups "AI automation" "looking for someone"',
    'site:facebook.com/groups "machine learning" consultant needed',
    'site:facebook.com/groups "דרוש מפתח"',
    'site:facebook.com/groups "מחפש מפתח" פרויקט',
    'site:facebook.com/groups "דרוש פרילנסר"',
    'site:facebook.com/groups "מחפשת מפתח" OR "מחפשים מפתח"',
    'site:facebook.com/groups "ראייה ממוחשבת" OR "עיבוד תמונה" פרויקט',
    'site:facebook.com/groups אוטומציה "מחפש מישהו"',
]

# Groups worth querying individually - the curated public ones the scraper can
# no longer read. Built at call time so newly promoted groups are included.
FB_POST_GROUP_QUERY_CAP = int(env("FB_POST_GROUP_QUERY_CAP", "12"))


def fb_post_queries() -> list[str]:
    """Intent queries interleaved with per-group queries.

    Interleaved rather than concatenated because DDG allows only ~2 queries per
    IP: a run must get a mix, not fifteen intent queries before the first group.
    """
    groups = [g["slug"] for g in FACEBOOK_GROUPS if g.get("public")][:FB_POST_GROUP_QUERY_CAP]
    per_group = [f"site:facebook.com/groups/{s}" for s in groups]
    out: list[str] = []
    for i in range(max(len(FB_POST_INTENT_QUERIES), len(per_group))):
        if i < len(FB_POST_INTENT_QUERIES):
            out.append(FB_POST_INTENT_QUERIES[i])
        if i < len(per_group):
            out.append(per_group[i])
    return out


# Reddit's search.rss is keyless and does not captcha - the same property that
# made it the reliable surface for WhatsApp discovery. Added 2026-08-08 after
# DuckDuckGo challenged BOTH the home IP and the GitHub runner (HTTP 202), which
# left the DDG surface effectively dead. People post FB group links in threads
# about finding freelance work, so the recall is real if narrower than a search
# engine's.
FB_REDDIT_QUERIES = [
    '"facebook.com/groups" freelance developer',
    '"facebook.com/groups" hiring developers',
    '"facebook.com/groups" "computer vision" OR "machine learning"',
    '"facebook.com/groups" AI automation clients',
    '"facebook.com/groups" israel developers',
    '"facebook.com/groups" remote work projects',
]

# Relevance = distinct keyword hits in the group NAME (same shape as the
# WhatsApp scorer). Bilingual on purpose.
FB_RELEVANT_RE = re.compile(
    r"(freelanc|פרילנס|הייטק|high[\s-]?tech|\bAI\b|בינה מלאכותית|machine learning"
    r"|למידת מכונה|deep learning|computer vision|ראייה ממוחשבת|עיבוד תמונה"
    r"|\bdata\b|דאטה|\bML\b|\bdev\b|developer|פיתוח|מתכנתים|מפתחים|jobs|משרות"
    r"|עבודה|דרושים|\bgig\b|startup|סטארטאפ|יזמים|python|תכנות|אלגוריתמ|algorithm"
    r"|automation|אוטומציה|project|פרויקט|outsourc|מיקור חוץ"
    # CLIENT-SIDE signals, added 2026-08-08. These are the words that appear in
    # the name of a group where someone BUYS work rather than performs it, which
    # is the distinction that separated Israel's 10 good leads from US/UK's 0.
    r"|founder|entrepreneur|\bowners?\b|\bSaaS\b|agency|ecommerce|e-commerce"
    r"|small business|\bclients?\b|hiring|\bneed a\b|looking for)", re.IGNORECASE)

# Groups that match the domain words but never carry client work. Same lesson as
# WA_NOISE_RE: on the WhatsApp run, student-cohort groups dominated the search
# surface and three of them scored high enough to trigger a Telegram ping.
# "buy/sell", "second hand" etc. catch the huge Israeli marketplace groups.
FB_NOISE_RE = re.compile(
    r"(internship|training\s+program|freshers?|batch\s*\d|cohort|semester|admission"
    r"|m\.?tech|b\.?tech|\bmba\b|\bmsc\b|\bbsc\b|placement|college|university|alumni"
    r"|meetup|\bevents?\b|webinar|\bcourse\b|קורס|bootcamp|סדנה"
    r"|יד שנייה|יד שניה|second\s*hand|buy\s*(and|&)\s*sell|קנייה ומכירה|מכירות"
    r"|dating|שידוכים|memes|בדיחות"
    # English DEV-COMMUNITY groups: devs talking to devs. Measured 0 good leads
    # from 44 posts. Hebrew "דרושים מפתחים" is the opposite - clients wanting
    # devs - so this stays English-only on purpose.
    r"|developers?\s+(group|community|club|forum|network|hub)"
    r"|programmers?\s+(group|community|club|forum)"
    r"|coding\s+(group|community|club|help)|code\s+newbies?"
    r"|learn\s+(to\s+)?(code|programming|python)|study\s+group"
    r"|interview\s+(prep|questions)|leetcode|hackathon)", re.IGNORECASE)

# --- WhatsApp group DISCOVERY (never automated - see discover_whatsapp_groups) -
# WhatsApp has no logged-out read surface, so the agent only finds joinable
# groups and the user joins them by hand. Reddit search is the reliable free
# surface; DDG frequently captcha-walls and is skipped when it does.
WHATSAPP_REDDIT_QUERIES = [
    '"chat.whatsapp.com" freelance',
    '"chat.whatsapp.com" "machine learning"',
    '"chat.whatsapp.com" "data science"',
    '"chat.whatsapp.com" AI developers',
    '"chat.whatsapp.com" hiring',
]
# Widened 2026-08-09. The first pass ran five generic strings and surfaced
# mostly student-cohort groups; nothing here targeted Or's actual niche. These
# add the CV/OCR/automation vocabulary and the Hebrew job-posting phrasings that
# Israeli groups name themselves with. WA_NOISE_RE still kills the cohort junk.
WHATSAPP_DDG_QUERIES = [
    # worldwide, English
    "site:chat.whatsapp.com freelance AI",
    'site:chat.whatsapp.com "computer vision"',
    "site:chat.whatsapp.com data science",
    'site:chat.whatsapp.com "deep learning" jobs',
    "site:chat.whatsapp.com OCR OR document AI",
    'site:chat.whatsapp.com "AI automation" n8n',
    'site:chat.whatsapp.com "remote developer" jobs',
    'site:chat.whatsapp.com "AI jobs"',
    # Israel / Hebrew
    "site:chat.whatsapp.com פרילנסרים",
    "site:chat.whatsapp.com הייטק",
    "site:chat.whatsapp.com בינה מלאכותית",
    "site:chat.whatsapp.com ראייה ממוחשבת",
    "site:chat.whatsapp.com דרושים מפתחים",
    "site:chat.whatsapp.com משרות הייטק ישראל",
    "site:chat.whatsapp.com אוטומציה עסקים",
]

# --- Night search rotation ----------------------------------------------------
# DuckDuckGo challenges an IP after ~1-2 queries, so the three query families
# cannot each keep their own budget - they share ONE. Weighted toward post
# search because that finds leads tonight, while group discovery only finds
# doors that still need Or to walk through them.
NIGHT_SEARCH_WEIGHTS = {"fbpost": 2, "fbgroup": 1, "wa": 1}
NIGHT_SEARCH_PER_RUN = int(env("NIGHT_SEARCH_PER_RUN", "2"))

# --- Auto-reply (Reddit only) -------------------------------------------------
# Freelancer.com was dropped 2026-08-06 after the trial: bid floods (20+ bids on
# every real project) and budgets far below Or's rate. Reddit is the only channel
# left with a legitimate posting API; Facebook stays manual by policy.
# Off by default. REPLY_MODE=approve queues drafts for your explicit approval
# (python main.py --replies / --approve-reply); "auto" sends immediately - only
# switch to auto after you've reviewed a batch of drafts and trust them.
REPLY_ENABLED = env("REPLY_ENABLED", "0") in ("1", "true", "yes")
REPLY_MODE = env("REPLY_MODE", "approve")          # approve | auto
REPLY_MIN_SCORE = int(env("REPLY_MIN_SCORE", "8"))  # only reply to strong leads
REPLY_DAILY_CAP = int(env("REPLY_DAILY_CAP", "8"))  # max sends/day across channels
# Your standing instructions to the LLM for choosing WHICH leads get a reply
# and what to emphasize. Edit freely in .env (single line).
REPLY_DIRECTION = env("REPLY_DIRECTION", (
    "Reply only to genuine freelance/contract/POC opportunities in computer vision, "
    "OCR/document intelligence, image processing, machine learning, algorithms, "
    "data visualization, or AI-integrated web/apps. Skip: full-time-only roles, "
    "agencies collecting CVs, vague posts with no real project, anything needing "
    "on-site presence outside Israel, budgets under $200."))

# --- Notification routing ---------------------------------------------------
PUSH_THRESHOLD = int(env("PUSH_THRESHOLD", "8"))      # >= this -> instant push
DIGEST_THRESHOLD = int(env("DIGEST_THRESHOLD", "6"))  # >= this -> daily digest
DIGEST_HOUR = int(env("DIGEST_HOUR", "18"))           # local time
# Draft a copy-paste first-contact reply for pushed leads (Gemini only; a few
# extra calls per day at most). Set PITCH_DRAFTS=0 to disable.
PITCH_DRAFTS = env("PITCH_DRAFTS", "1") in ("1", "true", "yes")

# --- HTTP -------------------------------------------------------------------
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# --- Keyword pre-gate (loose on purpose: recall > precision) -----------------
_DOMAIN_EN = [
    r"computer\s+vision", r"\bOCR\b", r"image\s+processing", r"object\s+detection",
    r"machine\s+learning", r"\bML\b", r"deep\s+learning", r"neural\s+net",
    r"data\s+vi[sz]", r"visuali[sz]ation", r"algorithm", r"segmentation",
    r"classification", r"\bLLM\b", r"\bGPT\b", r"\bRAG\b", r"chatbot",
    r"\bAI\b", r"artificial\s+intelligence", r"document\s+(processing|intelligence|extraction)",
    r"video\s+analytics", r"anomaly\s+detection", r"point\s*cloud", r"\b3D\s+reconstruction",
    # Practitioner vocabulary. Added 2026-08-08 after the user picked out a YOLO
    # defect-detection POC as the best lead of the batch - and it turned out to
    # have passed the gate only by incidentally containing "AI". None of the
    # words people ACTUALLY use for this work were in the list, so the whole
    # category was surviving on luck.
    r"\bYOLO\w*\b", r"opencv", r"roboflow", r"ultralytics", r"detectron",
    r"defect\s+detection", r"bounding\s+box", r"pose\s+estimation", r"keypoint",
    r"image\s+(classification|recognition|annotation|labell?ing)",
    r"tesseract", r"paddle\s*ocr", r"\bLayoutLM\b", r"handwrit",
    r"fine[\s-]?tun", r"\binference\b", r"embedding", r"vector\s+(db|database|search)",
    r"text\s+extraction", r"invoice\s+(parsing|extraction|processing)",
]
_DOMAIN_HE = [
    "ראייה ממוחשבת", "ראיה ממוחשבת", "עיבוד תמונה", "למידת מכונה",
    "בינה מלאכותית", "אלגוריתם", "זיהוי אובייקטים", "מודל שפה",
    "דאטה", "ויזואליזציה", "עיבוד וידאו", "זיהוי טקסט", "לגורתם",
]
_ENGAGE_EN = [
    r"freelanc", r"contract", r"\bPOC\b", r"proof\s+of\s+concept", r"part[\s-]?time",
    r"hourly", r"\bgig\b", r"project", r"consultant", r"looking\s+for", r"hiring",
    r"\[hiring\]", r"budget", r"outsourc",
]
_ENGAGE_HE = [
    "פרילנסר", "פרילנס", "מיקור חוץ", "פרויקט", "פרוייקט", "משרה חלקית",
    "מחפשים", "מחפש", "דרוש", "דרושה", "תקציב", "יועץ", "עבודה מהבית",
]

DOMAIN_RE = re.compile("|".join(_DOMAIN_EN + _DOMAIN_HE), re.IGNORECASE)
ENGAGE_RE = re.compile("|".join(_ENGAGE_EN + _ENGAGE_HE), re.IGNORECASE)

# STRONG domain terms = DOMAIN minus the weak catch-alls (\bAI\b matches "AI Art",
# "AI Video" etc. on gig boards). Used by the spam gate below.
_STRONG_EN = [
    r"computer\s+vision", r"\bOCR\b", r"image\s+processing", r"object\s+detection",
    r"machine\s+learning", r"deep\s+learning", r"neural\s+net", r"algorithm",
    r"segmentation", r"data\s+vi[sz]", r"visuali[sz]ation", r"\bLLM\b", r"\bRAG\b",
    r"face\s+recognition", r"video\s+analytics", r"anomaly\s+detection",
    r"document\s+(processing|intelligence|extraction)", r"point\s*cloud",
    r"automation\s+(agent|workflow|pipeline)", r"\bn8n\b", r"make\.com", r"zapier",
    # same additions as _DOMAIN_EN: these are strong enough to rescue a post from
    # SPAM_RE, since no design/typing gig says "YOLO" or "tesseract"
    r"\bYOLO\w*\b", r"opencv", r"roboflow", r"ultralytics", r"detectron",
    r"defect\s+detection", r"pose\s+estimation", r"tesseract", r"paddle\s*ocr",
    r"handwrit", r"invoice\s+(parsing|extraction|processing)",
]
STRONG_DOMAIN_RE = re.compile("|".join(_STRONG_EN + _DOMAIN_HE), re.IGNORECASE)

# Gig-board spam: pure design/typing/marketing/writing gigs that only matched the
# gate via a weak "AI ..." tag. Dropped unless a STRONG domain term also appears.
_SPAM = [
    r"logo\s+design", r"graphic\s+design", r"video\s+edit", r"video\s+production",
    r"copy\s*typing", r"data\s+entry", r"content\s+writ", r"article\s+writ",
    r"ghostwrit", r"social\s+media\s+(marketing|management|growth)",
    r"instagram|tiktok|youtube\s+shorts", r"\bSEO\b", r"link\s+building",
    r"voice\s*over", r"translat(e|ion|or)", r"proofread", r"resume|CV\s+writ",
    r"cold\s+call", r"telemarket", r"logo\b.*\bbrand", r"thumbnail",
]
SPAM_RE = re.compile("|".join(_SPAM), re.IGNORECASE)

# --- Precision gates (added 2026-07-11: keep FT jobs / seekers / volunteer asks
# / noise / partnerships out of the lead flow) ---------------------------------

# Full-time-only detector. FT_RE alone isn't enough - a post mentioning both
# "full-time" and "freelance" is flexible, so FLEX_RE acts as counter-signal.
FT_RE = re.compile(
    r"(משרה מלאה|היקף משרה:?\s*מלאה|full[\s-]?time|direct[\s_-]?hire"
    r"|Type:\s*full_time"
    # bulk-recruiting career ads (companies hiring for many salaried roles)
    r"|הזדמנויות קריירה|מגייס(ת|ים)? ל|we('|’)?re hiring|is hiring"
    r"|open (positions|roles)|הצטרפו לחברה)", re.IGNORECASE)
FLEX_RE = re.compile(
    r"(פרילנס|עצמאי|עצמאית|משרה חלקית|מיקור חוץ|לפרויקט|פרויקטלי"
    r"|freelanc|contract(or|\s+work|\s+role|\b)|part[\s-]?time|hourly|per\s+hour"
    r"|\bPOC\b|proof\s+of\s+concept|\bgig\b|one[\s-]off|Type:\s*(fixed|hourly)"
    r"|/hr\b|hrs?/w(ee)?k)", re.IGNORECASE)

# Job-seekers (people offering themselves, not hiring).
# The "open to ... opportunities" / "[Hiring Me]" / "I need clients" variants were
# added after Reddit-search results showed seekers slipping past the plain
# "looking for a job" phrasings by inserting adjectives ("Looking for Full-time &
# Freelance Opportunities", "Open to Freelance & Part-Time Opportunities").
SEEKER_RE = re.compile(
    r"(אני מחפשת? עבודה|מחפשת? את ההזדמנות הבאה|מחפשת? משרה|מעוניין להשתלב"
    r"|קורות החיים שלי|קו\"ח שלי"
    r"|seeking\s+work|looking\s+for\s+(a\s+)?(job|position|role|referral|internship|opportunit)"
    r"|looking\s+for\s+[\w\s&/,-]{0,40}opportunit"
    r"|open\s+(to|for)\s+[\w\s&/,-]{0,40}opportunit"
    r"|available\s+for\s+(hire|work|freelance|projects|contract)"
    r"|my\s+resume|review\s+my\s+(cv|resume)|hire\s+me\b|\[hiring\s+me\]"
    r"|i\s+need\s+clients|need\s+clients\b"
    r"|refer\s+me|am\s+i\s+.{0,20}ready|\[for\s+hire\]"
    # Added 2026-08-08: a self-promo slipped through titled "Python Developer
    # Available - Bots, Automation & Custom Scripts", body "I'm a Python
    # developer currently looking to take on freelance work. I can help with:".
    # None of the phrasings above matched - "available" was not followed by
    # "for", and "looking to take on" is not "looking for".
    r"|\b(developer|engineer|programmer|freelancer|consultant|designer)s?\s+"
    r"available\b"
    r"|\bcurrently\s+available\b|\bavailable\s+(now|immediately|to\s+start)\b"
    r"|looking\s+to\s+(take\s+on|work\s+on|help|collaborate|partner|join)"
    r"|i\s+can\s+help\s+(you\s+)?with"
    r"|i\s*(?:'m|’m|\s+am)\s+a\s+[\w\s]{0,25}(developer|engineer|programmer"
    r"|data\s+scientist|freelancer|consultant)\b"
    r"|my\s+(services|rates|portfolio|skills)\b|services\s+i\s+offer"
    r"|open\s+to\s+work\b|\bfor\s+hire\b"
    # Hebrew equivalents
    r"|אני\s+מפתח|אני\s+מתכנת|זמין\s+לעבודה|מציע\s+שירותי"
    # "שמי טל כהן, מהנדס תוכנה ויועץ פיתוח" - the Hebrew self-introduction, which
    # is how Israeli freelancers open a self-promo. Slipped through as a 7/10
    # lead on the first facebook/search run.
    r"|שמי\s+[֐-׿\s]{2,20}(מהנדס|מפתח|מתכנת|יועץ|פרילנסר)"
    r"|בעל\s+ניסיון\s+ב(פיתוח|תכנות)"
    r"|מחפש\s+פרויקטים|לקוחות\s+חדשים)", re.IGNORECASE)

# Unpaid community / volunteer / data-collection / survey asks
COMMUNITY_RE = re.compile(
    r"(מתנדב|בהתנדבות|תיוג קהילתי|איסוף ה?דאטה|נשמח לעזרה|אוספים תמונות"
    r"|volunteer|data\s+collection\s+(effort|project|initiative)"
    r"|fill\s+(out|in|up)\s+(this|the)\s+(survey|form|questionnaire)"
    r"|ענו על השאלון|שאלון קצר|open[\s-]source\s+contribut|contribute\s+to\s+our"
    r"|help\s+us\s+(collect|label|annotate|compare))", re.IGNORECASE)

# Group admin/welcome posts, courses, workshops, events, self-improvement ads
NOISE_RE = re.compile(
    r"(ברוכים הבאים|הצטרפו לקבוצ|קבוצת הטלגרם|בואו ללמוד|(?<![א-ת])קורס(?![א-ת])"
    r"|סדנה|סדנת|מכללה"
    r"|הרשמה ל|וובינר|מיטאפ|(?<![א-ת])כנס(?![א-ת])|מפגש קהילת"
    r"|masterclass|webinar|meetup|workshop\s+(on|for)|register\s+now|enroll"
    r"|free\s+course|bootcamp|interview\s+prep|career\s+guidance|coaching)",
    re.IGNORECASE)

# Partnership / co-founder / equity-only asks -> separate low-priority bucket
PARTNER_RE = re.compile(
    r"(שותפ(ה|ים)? טכנולוגי|מחפשת? שותפ|co[\s-]?founder|founding\s+partner"
    r"|equity[\s-]only|תמורת אחוזים|אחוזים מהמיזם|שותפות במיזם"
    r"|CTO\s*/|/\s*שותפ)", re.IGNORECASE)
# ...unless real money is on the table
BUDGET_SIGNAL_RE = re.compile(
    r"(₪|\$|€|£|תקציב|budget|\d+\s*(ש\"ח|שח|nis|usd|eur)|/hr\b|per\s+hour|שעתי)",
    re.IGNORECASE)

# --- Location gate: the engineer is in Israel and works remote or in Israel. A
# posting locked to a specific OTHER country/region (with no Israel / worldwide /
# remote-anywhere option) is not accessible, so it's gated out. LOCATION_OK_RE is
# a counter-signal: if the post also welcomes Israel / worldwide / EMEA / anywhere,
# it survives (e.g. A.Team's "Americas, Europe, or Israel"). ---
LOCATION_BLOCK_RE = re.compile(
    r"(United States only|U\.?S\.?A?\.? ?only|US[- ]only|US[- ]based only"
    r"|must be (located|based|residing) in (the )?(US|U\.S\.|USA|United States)"
    r"|authoriz(ed|ation) to work in (the )?(US|United States)"
    r"|US work authorization|must be (a\s+)?US citizen|US citizen(ship)? (required|only)"
    # US staffing ads phrase it as an eligibility list rather than a sentence:
    # "( Must be US Citizen or Green Card )", "USC/GC only", "no C2C, GC/USC"
    r"|(US )?citizens?(hip)? or green[\s-]?card|green[\s-]?card (holder|only)"
    r"|\bUSC\s*/\s*GC\b|\bGC\s*/\s*USC\b"
    r"|US residents? only|united_states_only"
    r"|(LATAM|Latin America) only|latam_only|based in LATAM"
    r"|(India|Canada|United Kingdom|U\.?K\.?|Germany|France|Poland|Ukraine|Brazil"
    r"|Mexico|Argentina|Australia|Singapore|Philippines) ?[- ]?only)", re.I)
LOCATION_OK_RE = re.compile(
    r"(israel|ישראל|\bIL\b|worldwide|world[- ]wide|anywhere|global(ly)?|any location"
    r"|remote.{0,25}(anywhere|worldwide|global)|\bEMEA\b|europe.{0,20}israel)", re.I)

# Sources whose listings are full-time by default (career boards) - a post there
# must show a FLEX signal to survive.
FT_DEFAULT_SOURCES = {"companies"}

# Sources whose content is already keyword-targeted upstream
# (Upwork/Wellfound alerts come from saved searches you defined).
GATE_BYPASS_SOURCES = {"upwork", "wellfound"}

# Broad job boards where every listing is a job: require a DOMAIN keyword match
# (not just an engagement word) so generic remote roles don't flood the pipeline.
# remoteok + himalayas dropped 2026-08-08: both gate applying behind a paid
# plan, so a lead there costs money to act on - same reasoning as Freelancer.com.
DOMAIN_REQUIRED_SOURCES = {"weworkremotely", "remotive",
                           "arbeitnow", "workingnomads", "aijobs",
                           "telegram", "braintrust", "jobspresso", "companies",
                           "jobicy", "linkedin"}

# Discussion communities (not job boards): every post matches DOMAIN, so also
# require hiring intent (an ENGAGE term) to become a candidate.
# NOTE: this set is matched on the FULL source label (unlike the root-keyed sets
# above), which is what lets us gate Reddit per-subreddit.
INTENT_REQUIRED_SOURCES = {"r/computervision", "r/MachineLearningJobs",
                           "r/DataScienceJobs", "r/BigDataJobs",
                           "r/hiring", "r/AI_Agents", "r/n8n", "r/automation",
                           "r/deeplearning", "r/LocalLLaMA", "r/search",
                           "facebook/Machine & Deep Learning Israel",
                           "facebook/ML & Data Science Jobs Israel"}

# Fuzzy-dedup: posts >= this similar (0-100) within 7 days are duplicates.
DEDUP_SIMILARITY = 90

# --- Budget floor -------------------------------------------------------------
# The user will not work for scraps. Two different floors, because the SAME
# number means opposite things: $50/hour is a fine rate, $50 for a whole project
# is not. Anything quoted in another currency is converted first - gig boards are
# full of INR/PHP postings whose numbers look large and are worth very little.
#
# A lead is only gated when a budget was actually found AND it is clearly below
# the floor. No budget mentioned => not gated; plenty of good direct-approach
# posts name no number at all.
MIN_BUDGET_USD = float(env("MIN_BUDGET_USD", "50"))    # fixed-price / total
MIN_HOURLY_USD = float(env("MIN_HOURLY_USD", "25"))    # per-hour rate
TARGET_HOURLY_USD = float(env("TARGET_HOURLY_USD", "80"))  # what "good" looks like

# Static rates to USD. Deliberately not a live FX API: this is a coarse
# threshold, the project must stay free, and a rate moving 10% never flips a
# $20 gig into an $80 one. Refresh occasionally if a currency drifts badly.
FX_TO_USD = {
    "usd": 1.0, "eur": 1.08, "gbp": 1.27, "ils": 0.27, "inr": 0.012,
    "aud": 0.65, "cad": 0.73, "php": 0.017, "pkr": 0.0036, "bdt": 0.0085,
    "brl": 0.18, "zar": 0.054, "mxn": 0.05, "rub": 0.011, "uah": 0.024,
    "try": 0.029, "pln": 0.25, "sek": 0.095, "nok": 0.093, "dkk": 0.145,
    "chf": 1.12, "jpy": 0.0067, "cny": 0.14, "sgd": 0.74, "aed": 0.27,
    "egp": 0.021, "ngn": 0.00065, "kes": 0.0077, "lkr": 0.0033, "vnd": 0.00004,
    "idr": 0.000062, "thb": 0.028, "myr": 0.22, "nzd": 0.60,
}

# Symbol / word -> currency code. Order matters when scanning: the longer,
# more specific tokens must be tried before bare symbols.
CURRENCY_TOKENS = [
    (r"₪|ש\"ח|שח|\bNIS\b|\bILS\b", "ils"),
    (r"₹|\bRs\.?\b|\bINR\b", "inr"),
    (r"\bAUD\b|\bA\$", "aud"), (r"\bCAD\b|\bC\$", "cad"),
    (r"\bNZD\b", "nzd"), (r"\bSGD\b", "sgd"), (r"\bAED\b", "aed"),
    (r"\bPHP\b|\b₱", "php"), (r"\bPKR\b", "pkr"), (r"\bBDT\b|\b৳", "bdt"),
    (r"\bBRL\b|\bR\$", "brl"), (r"\bZAR\b", "zar"), (r"\bMXN\b", "mxn"),
    (r"₽|\bRUB\b", "rub"), (r"\bUAH\b|₴", "uah"), (r"\bTRY\b|₺", "try"),
    (r"\bPLN\b|\bzł", "pln"), (r"\bSEK\b", "sek"), (r"\bCHF\b", "chf"),
    (r"¥|\bJPY\b|\bCNY\b|\bRMB\b", "jpy"),
    (r"€|\bEUR\b", "eur"), (r"£|\bGBP\b", "gbp"),
    (r"\$|\bUSD\b", "usd"),
]

# "per hour" in the languages this pipeline sees
HOURLY_RE = re.compile(
    r"(/\s*(hr|hour)\b|per\s+hour|hourly|an\s+hour|a[n]?\s*/\s*hr\b"
    r"|לשעה|בשעה|שעתי)", re.IGNORECASE)

# --- Staleness ---------------------------------------------------------------
# A filled gig is worth nothing, and the user rejected leads that were expired or
# closed. Two independent checks, because they catch different things:
#   * MAX_LEAD_AGE_DAYS   - the post is simply too old to still be open. Applied
#     when a real post date is known. 45 days is deliberately generous: Reddit
#     and Facebook posts stay live and answerable far longer than a job board ad.
#   * CLOSED_RE (email_fetcher) - the posting itself says it stopped accepting
#     applications, which age alone never reveals.
# A date written INSIDE the post body ("March 31, 2024" on a Facebook post) is
# parsed by STALE_DATE_RE, because Facebook gives the fetcher no post date at
# all - measured: a 2-year-old OCR gig scored 7 and reached the user's table.
MAX_LEAD_AGE_DAYS = int(env("MAX_LEAD_AGE_DAYS", "45"))
STALE_DATE_RE = re.compile(
    # Abbreviated forms matter: search-index results render Facebook dates as
    # "Mar 7, 2022", and a full-month-only pattern let a 2022 post through as
    # fresh (measured 2026-08-09 on a facebook/search lead).
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"(?:uary|ruary|ch|il|e|y|ust|tember|ober|ember)?\.?"
    r"\s+(\d{1,2}),?\s+(20\d{2})\b", re.I)
