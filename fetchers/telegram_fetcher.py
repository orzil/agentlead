"""Public Telegram CHANNELS via the free t.me/s/<handle> web preview.

No login, no API key: Telegram serves server-rendered HTML with the latest ~20
posts of any channel that has public previews enabled. (Groups and
preview-disabled channels return a join-stub with zero message blocks - the
fetcher just logs 0 for those.)

Channel list lives in config.TELEGRAM_CHANNELS. Verified working 2026-07-06.
"""
from __future__ import annotations

import html as htmllib
import logging
import re
import socket
from datetime import datetime

import config
from models import Lead

log = logging.getLogger("telegram")

# Some networks/ISPs block the short domain t.me at the DNS level (getaddrinfo
# fails) while telegram.org still resolves. t.me shares Telegram's IPs, so when
# normal resolution fails we resolve it once via DNS-over-HTTPS and install a
# tiny getaddrinfo shim so httpx (and everything else) can reach t.me.
_TME_HOSTS = {"t.me", "www.t.me"}


def _ensure_tme_resolvable() -> None:
    import httpx

    try:
        socket.getaddrinfo("t.me", 443)
        return  # resolves fine, nothing to do
    except socket.gaierror:
        pass
    ip = None
    for doh in ("https://dns.google/resolve?name=t.me&type=A",
                "https://cloudflare-dns.com/dns-query?name=t.me&type=A"):
        try:
            r = httpx.get(doh, headers={"accept": "application/dns-json"}, timeout=20)
            answers = [a["data"] for a in r.json().get("Answer", []) if a.get("type") == 1]
            if answers:
                ip = answers[0]
                break
        except Exception:
            continue
    if not ip:
        log.warning("telegram: t.me is DNS-blocked and DoH resolution failed")
        return
    _orig = socket.getaddrinfo

    def _shim(host, *a, **k):
        return _orig(ip if host in _TME_HOSTS else host, *a, **k)

    socket.getaddrinfo = _shim
    log.info("telegram: t.me DNS-blocked locally; resolved via DoH -> %s", ip)

# one message block: data-post="handle/1234" ... text div ... <time datetime="...">
_MSG_RE = re.compile(
    r'data-post="(?P<post>[^"]+)".*?'
    r'(?:<div class="tgme_widget_message_text[^"]*"[^>]*>(?P<text>.*?)</div>.*?)?'
    r'<time datetime="(?P<dt>[^"]+)"',
    re.S,
)
_TAG_RE = re.compile(r"<br/?>|</div>")
_ANYTAG_RE = re.compile(r"<[^>]+>")


def _clean(fragment: str) -> str:
    text = _TAG_RE.sub("\n", fragment)
    text = _ANYTAG_RE.sub(" ", text)
    text = htmllib.unescape(text)
    return re.sub(r"[ \t]+", " ", text).strip()


def fetch() -> list[Lead]:
    import httpx

    _ensure_tme_resolvable()
    headers = {"User-Agent": config.USER_AGENT}
    leads: list[Lead] = []
    with httpx.Client(headers=headers, timeout=25, follow_redirects=True) as client:
        for handle in config.TELEGRAM_CHANNELS:
            try:
                r = client.get(f"https://t.me/s/{handle}")
                r.raise_for_status()
                n = 0
                for m in _MSG_RE.finditer(r.text):
                    raw = m.group("text")
                    if not raw:
                        continue  # media-only post
                    text = _clean(raw)
                    if len(text) < 60:
                        continue
                    posted = None
                    try:
                        posted = datetime.fromisoformat(m.group("dt"))
                    except ValueError:
                        pass
                    leads.append(Lead(
                        source=f"telegram/{handle}",
                        url=f"https://t.me/{m.group('post')}",
                        raw_text=text[:4000],
                        posted_at=posted,
                    ))
                    n += 1
                log.info("telegram: %s -> %d posts", handle, n)
            except Exception as e:
                log.error("telegram %s failed: %s", handle, e)
    return leads
