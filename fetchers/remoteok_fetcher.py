"""RemoteOK - free public JSON API, no auth.

GET https://remoteok.com/api?tags=<slug> returns recent remote jobs for a tag.
The first array element is a legal/metadata notice (has no 'id'), so we skip it.
We query a handful of on-domain tags and dedupe by job id. Many listings are
full-time, but RemoteOK carries plenty of contract/remote AI/ML work; the
keyword gate + LLM scorer down-rank the rest.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import config
from models import Lead

log = logging.getLogger("remoteok")

API = "https://remoteok.com/api"
TAGS = ["machine-learning", "artificial-intelligence", "computer-vision",
        "data-science", "algorithm", "python", "automation"]
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(html: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", html or "")).strip()


def fetch() -> list[Lead]:
    import httpx

    headers = {"User-Agent": config.USER_AGENT, "Accept": "application/json"}
    seen: set = set()
    leads: list[Lead] = []
    with httpx.Client(headers=headers, timeout=25, follow_redirects=True) as client:
        for tag in TAGS:
            try:
                r = client.get(API, params={"tags": tag})
                r.raise_for_status()
                for j in r.json():
                    jid = j.get("id")
                    if not jid or jid in seen:
                        continue
                    seen.add(jid)
                    url = j.get("url") or f"https://remoteok.com/remote-jobs/{j.get('slug','')}"
                    tags = ", ".join(j.get("tags", []) or [])
                    text = (f"{j.get('position','')} at {j.get('company','')}\n"
                            f"Tags: {tags}\n\n{_clean(j.get('description',''))}")
                    epoch = j.get("epoch")
                    posted = (datetime.fromtimestamp(epoch, tz=timezone.utc)
                              if isinstance(epoch, (int, float)) else None)
                    leads.append(Lead(
                        source="remoteok",
                        url=url,
                        raw_text=text[:4000],
                        author=j.get("company"),
                        posted_at=posted,
                    ))
            except Exception as e:
                log.error("remoteok tag=%s failed: %s", tag, e)
    log.info("RemoteOK: fetched %d jobs", len(leads))
    return leads
