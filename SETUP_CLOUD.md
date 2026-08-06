# AgentLead — Cloud setup (run it for you, a few times a day, for free)

This makes the agent run on **GitHub's servers** on a schedule, scoring leads and
pushing the strong ones (score ≥ 8) to your **Telegram**. Facebook scraping runs
on GitHub's IPs, so **your own account can never get rate-limited/locked again**.
Everything here is free.

## One-time setup (~20 min)

### 1. Get the free keys
| Secret | Where | Notes |
|---|---|---|
| `GEMINI_API_KEY` | https://aistudio.google.com/apikey | Free, no credit card. This is what scores leads 1–10. |
| `TELEGRAM_BOT_TOKEN` | Message **@BotFather** → `/newbot` | Copy the token it gives you. |
| `TELEGRAM_CHAT_ID` | Message your new bot once, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` | Copy the `"chat":{"id": ...}` number. |
| `IMAP_USER` | your Gmail address | For the email pipeline. |
| `IMAP_PASSWORD` | Google Account → Security → 2-Step Verification → **App passwords** | A 16-char app password, **not** your real password. |

### 2. Put the code on GitHub
From this folder:
```bash
git init
git add .
git commit -m "AgentLead"
```
Create a new **empty** repo on github.com, then:
```bash
git remote add origin https://github.com/<you>/<repo>.git
git branch -M main
git push -u origin main
```
> `.env` and `leads.db` are gitignored — secrets never leave your machine.

### 3. Add the secrets to GitHub
Repo → **Settings → Secrets and variables → Actions → New repository secret**.
Add all five from the table above (exact names).

### 4. Turn it on
Repo → **Actions** tab → enable workflows → open **“AgentLead cloud run”** →
**Run workflow** to test it now. After that it runs automatically 4×/day.
You should get a Telegram ping the first time a lead scores ≥ 8.

## Make Facebook groups feed in (the ban-proof way)

For **every group you care about** (IL, US, EU — public *or* private):

1. Join the group.
2. Group → **🔔 → All posts** (turn on notifications).
3. In Gmail, optionally make a filter: `from:facebookmail.com` → apply a label.

That's it. FB emails you every new post; the agent reads your inbox over IMAP and
scores them. **This scales to unlimited groups, updates in near real-time, and
carries zero ban risk** — it's the recommended backbone. The GitHub-Actions
scraper below is a bonus for public groups you'd rather not join.

## Add more groups to the scraper
Edit `FACEBOOK_GROUPS` in `config.py` (each entry has `slug`, `name`, `public`,
`region`). New slugs start `public: None` until probed. **Probe them safely** by
running `probe_fb_groups.py` from the cloud (or a non-personal network), never
from the IP you browse Facebook on.

## Tuning cadence / load (in `.github/workflows/leadagent.yml`)
- **How often:** edit the `cron:` lines (UTC).
- **How many groups per run:** `FB_GROUPS_PER_RUN` (rotates through the pool so
  all groups get covered over several runs).
- **Gentleness:** `FB_GROUP_GAP_SECONDS` (higher = safer). 90s is conservative.
- **Regions:** `FB_REGIONS=IL,US,EU`.

## Cost / limits
- **Public repo → unlimited** Actions minutes. Private repo → 2,000 min/month
  (plenty at 4 short runs/day). Lead data lives only in the Actions cache, never
  in git, so a public repo is safe.
