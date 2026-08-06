"""Probe FACEBOOK_GROUPS marked public=None (unverified), logged-out, and report
whether each is PUBLIC (posts render), PRIVATE (login wall), or GONE (bare page /
wrong slug). Run this occasionally - especially after adding new groups - when
your IP is NOT rate-limited by Facebook (a bare "Facebook" title on a group you
know is real means you're throttled; wait and retry later).

Usage:  python -X utf8 probe_fb_groups.py           # report only
        python -X utf8 probe_fb_groups.py --write    # also print config-ready lines
"""
from __future__ import annotations

import re
import sys

import config

PRIV = re.compile(r"(this group is private|private group|join this group to see|"
                  r"קבוצה פרטית|הצטרפ)", re.I)


def main() -> None:
    from playwright.sync_api import sync_playwright

    targets = [g for g in config.FACEBOOK_GROUPS if g.get("public") is None]
    if not targets:
        print("No unverified (public=None) groups to probe.")
        return
    print(f"Probing {len(targets)} unverified groups (10s apart)...\n")

    results = []
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        ctx = b.new_context(user_agent=config.USER_AGENT, locale="en-US",
                            viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        for i, g in enumerate(targets):
            slug = g["slug"]
            status = "ERROR"
            try:
                page.goto(f"https://www.facebook.com/groups/{slug}/",
                          wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(3500)
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
                page.wait_for_timeout(1200)
                page.mouse.wheel(0, 1400)
                page.wait_for_timeout(2500)
                title = (page.title() or "").strip()
                arts = len(page.query_selector_all("div[role='article']"))
                body = page.inner_text("body")
                if title == "Facebook" and arts == 0:
                    status = "GONE/BLOCKED"
                elif arts >= 2 and not PRIV.search(body):
                    status = "PUBLIC"
                else:
                    status = "PRIVATE"
            except Exception as e:
                status = f"ERROR {str(e)[:30]}"
            results.append((status, g))
            print(f"  {status:12} {g['region']:3} {slug:28} | {g['name']}")
            if i < len(targets) - 1:
                # throttle kicks in around ~10 quick loads; slower pace lasts longer
                page.wait_for_timeout(20000)
        b.close()

    pub = [g for s, g in results if s == "PUBLIC"]
    print(f"\n{len(pub)} PUBLIC. "
          f"{sum(1 for s,_ in results if s=='PRIVATE')} private, "
          f"{sum(1 for s,_ in results if 'GONE' in s)} gone/blocked.")
    if "--write" in sys.argv and pub:
        print("\n# Flip these to public=True in config.FACEBOOK_GROUPS:")
        for g in pub:
            print(f'    {{"slug": "{g["slug"]}", "name": "{g["name"]}", '
                  f'"public": True, "region": "{g["region"]}"}},')


if __name__ == "__main__":
    main()
