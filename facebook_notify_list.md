# Facebook groups: turn on notifications (one-time, by hand)

Written 2026-11-16. Nothing reads Israeli Facebook groups in real time: logged-out
scraping is blocked from the cloud, and the search-index fallback is days late. The one
ban-safe real-time route is Facebook's own notification mail, which the agent already
reads from Gmail every 5 minutes. In 60 days the inbox received **zero** group-post
mails, so this has never been switched on.

## Step 1 — account setting (once)

Facebook → Settings & privacy → Settings → Notifications → **Email** →
choose **"All notifications, except the ones you unsubscribe from"**, and under
Notifications → **Groups** make sure **Email** is on.

Without this, per-group settings below only produce in-app notifications.

## Step 2 — per group

Open each link → (join if needed) → bell / "Manage notifications" → **All posts**.
Gmail files these under Social; that is fine, the agent reads the whole inbox.

### Tier A — clients post work here (do these first)

| # | Group | Link |
|---|---|---|
| 1 | the group you named (Claude / SaaS build requests) | https://www.facebook.com/groups/cladue |
| 2 | פרילנסרים בהייטק | https://www.facebook.com/groups/freelance.hightech |
| 3 | דרושים - עבודות פרילנסרים (private) | https://www.facebook.com/groups/458346604817578 |
| 4 | מתכנתים פרילנסרים (private) | https://www.facebook.com/groups/1502756793303704 |
| 5 | דרושים פרילנסרים וטאלנטים בדיגיטל | https://www.facebook.com/groups/1129872654348077 |
| 6 | זירת פרילנסרים | https://www.facebook.com/groups/279218118861800 |
| 7 | Israel Freelance Developers | https://www.facebook.com/groups/367262456327 |
| 8 | Freelancers Networking - Israel | https://www.facebook.com/groups/freelancersnetworkingIL |
| 9 | מתכנתים פוגשים סטארטאפים | https://www.facebook.com/groups/developersmeetstartups |
| 10 | AI Agents Israel - קלוד קוד וסוכני בינה מלאכותית | https://www.facebook.com/groups/1266824747259615 |
| 11 | הכול על אוטומציות בינה מלאכותית AI - IL | https://www.facebook.com/groups/automationisrael |
| 12 | N8n ישראל הקבוצה הרשמית | https://www.facebook.com/groups/n8nil |
| 13 | אופק עסקי - אוטומציה ובינה מלאכותית | https://www.facebook.com/groups/482067651607538 |
| 14 | Computer Vision Israel (private) | https://www.facebook.com/groups/1831991027038183 |
| 15 | עיבוד תמונה, ראיה ממוחשבת, למידת מכונה ולמידה עמוקה | https://www.facebook.com/groups/320942198348539 |
| 16 | Machine & Deep Learning Israel | https://www.facebook.com/groups/MDLI1 |
| 17 | דרוש מתכנת לעבודה לפי פרוייקטים | https://www.facebook.com/groups/262663949723327 |
| 18 | דרושים פרילנסרים קבלני משנה בכל התחומים | https://www.facebook.com/groups/557735016862777 |
| 19 | פרילנסרים ומשרות פרילנס Jobonline | https://www.facebook.com/groups/776851981391261 |
| 20 | דרושים להייטק & פרילנסרים | https://www.facebook.com/groups/jobsFor.High.tech |

### Tier B — founders and business owners (work shows up as "who can build…")

| # | Group | Link |
|---|---|---|
| 21 | קהילת יזמים/סטארטאפים (Apps) (private) | https://www.facebook.com/groups/appsentrepreneur |
| 22 | בינה מלאכותית ישראל - AI Israel - עסקים, יזמות | https://www.facebook.com/groups/ai.israel.official |
| 23 | ארגון ה-AI הישראלי - בינה מלאכותית לארגונים | https://www.facebook.com/groups/israelaiorg |
| 24 | Israeli entrepreneurs - יזמים ישראלים | https://www.facebook.com/groups/yazamutIsrael |
| 25 | קהילת היזמים של ישראל - Start A Startup | https://www.facebook.com/groups/506523693145809 |
| 26 | המשבשים: יזמים, משקיעים וסטארטאפים | https://www.facebook.com/groups/223303087850326 |
| 27 | אאוטסורסינג - מיקור חוץ | https://www.facebook.com/groups/7588730134550590 |
| 28 | דרושים מתכנתים ובוני אתרים | https://www.facebook.com/groups/drushimboneiatarim |
| 29 | משרות הייטק חלקיות בין חברים | https://www.facebook.com/groups/high.tech.part.time.jobs.israel |
| 30 | משרות פרילאנסר/שכיר ב-Remote | https://www.facebook.com/groups/197859277728196 |

Pure full-time "דרושים הייטק" boards are left out on purpose: their posts gate out as
full-time and would only fill the inbox.

## What happens next

Each mail becomes one lead per post, labelled `facebook/<group name>`, and goes through
the normal gate → score → Telegram push. The parser was built against synthetic mails
(no real one existed), so the first real notification is the test: if a group post you
saw does not reach Telegram within ~10 minutes, that mail's format needs a parser fix.
