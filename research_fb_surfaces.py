"""One-off experiment: which Facebook surfaces still serve public group posts?

Context: www.facebook.com via Playwright is walled on the FIRST request from a
GitHub runner (measured across many runs: 0 leads, every group, every time), so
Meta appears to block the IP range on reputation rather than rate-limiting our
behaviour. Before concluding cloud scraping is dead, test the other doors.

Run this IN THE CLOUD (workflow_dispatch). Never from Or's home IP.

What is deliberately NOT tried: impersonating Googlebot or any crawler UA. That
is cloaking - claiming to be someone we are not to get content we are otherwise
refused. Normal desktop and mobile user agents only.
"""
from __future__ import annotations

import json
import re
import sys

import httpx

DESKTOP = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
MOBILE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
          "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
ANDROID = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36")

# Two groups already verified public + one known-active Israeli one.
SLUGS = ["freelance.hightech", "1920854911477422", "MDLI1"]

HOSTS = [
    ("www", "https://www.facebook.com/groups/{s}/", DESKTOP),
    ("mbasic", "https://mbasic.facebook.com/groups/{s}", MOBILE),
    ("mbasic-android", "https://mbasic.facebook.com/groups/{s}", ANDROID),
    ("m", "https://m.facebook.com/groups/{s}", MOBILE),
    ("touch", "https://touch.facebook.com/groups/{s}", MOBILE),
    ("www-mobileUA", "https://www.facebook.com/groups/{s}/", MOBILE),
]

WALL = re.compile(r"(log in|log into facebook|you must log in|create new account"
                  r"|התחבר|הרשמה)", re.I)


def looks_like_content(text: str) -> tuple[bool, str]:
    """Did we get actual group content, or a login wall / empty shell?"""
    t = re.sub(r"\s+", " ", text)
    if len(t) < 400:
        return False, f"tiny body ({len(t)} chars)"
    # mbasic renders posts as plain <p>/<div> text; a wall is mostly a login form
    hits = len(re.findall(r"(?:·|ago|hours|minutes|days)\b", t[:8000]))
    if WALL.search(t[:2000]) and hits < 3:
        return False, "login wall"
    return hits >= 3, f"{hits} timestamp-ish tokens"


def main() -> None:
    out = []
    for slug in SLUGS[:2]:
        for name, tmpl, ua in HOSTS:
            url = tmpl.format(s=slug)
            row = {"surface": name, "slug": slug}
            try:
                r = httpx.get(url, headers={
                    "User-Agent": ua,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.9",
                }, timeout=25, follow_redirects=True)
                ok, why = looks_like_content(r.text)
                row.update(status=r.status_code, final=str(r.url)[:70],
                           bytes=len(r.text), content=ok, why=why)
            except Exception as e:
                row.update(status=0, why=f"{type(e).__name__}: {str(e)[:60]}",
                           content=False)
            out.append(row)
            print(f"{row['surface']:16} {row['slug'][:20]:20} "
                  f"HTTP {row.get('status'):>3} {row.get('bytes', 0):>7}b "
                  f"content={row.get('content')} {row.get('why', '')[:40]}")
            sys.stdout.flush()
    print()
    print(json.dumps({"results": out}, indent=1)[:400])
    winners = sorted({r["surface"] for r in out if r.get("content")})
    print("\nSURFACES THAT SERVED CONTENT:", winners or "NONE")


if __name__ == "__main__":
    main()
