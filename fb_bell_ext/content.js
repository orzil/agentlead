// AgentLead bell reader - content script. READ-ONLY by design: it never clicks,
// scrolls, types or calls Facebook's APIs. It reads what the page already shows.
//
// On facebook.com/notifications each entry is an <a href="/groups/<g>/?multi_permalinks=<post>
// &notif_id=..&notif_t=group_activity"> whose text nodes are:
//   ["Unread"], ["Now in"], <b>group</b>, ': "first ~50 chars..."', "42m"
// (measured 2026-11-22). On any other facebook.com page it only runs the block check.

(() => {
  const BLOCK_PATH_RE = /^\/(checkpoint|login|two_step_verification|auth_platform)\b/i;
  const BLOCK_TEXT_RE = /temporarily blocked|going too fast|suspect(ed)? automated|automated behavior|confirm (it'?s|that it'?s) you|נחסמת|חסומ(ה|ים)? זמנית|התנהגות אוטומטית|פעילות אוטומטית/i;
  const AGO_RE = /^(just now|now|\d+\s*[smhdwy])$/i;

  function blockedReason() {
    if (BLOCK_PATH_RE.test(location.pathname)) return "url:" + location.pathname;
    // Facebook's warnings come as dialogs. The notifications list itself also sits
    // in a role=dialog, so skip any dialog that holds notification links.
    for (const d of document.querySelectorAll('[role="dialog"], [role="alertdialog"]')) {
      if (d.querySelector('a[href*="notif_id"]')) continue;
      // chat windows and composers are dialogs too: a message saying "blocked" must not stop us
      if (d.querySelector('[role="textbox"], [contenteditable="true"]')) continue;
      const m = (d.innerText || "").slice(0, 2000).match(BLOCK_TEXT_RE);
      if (m) return "dialog:" + m[0];
    }
    return "";
  }

  function readEntries() {
    const out = new Map();
    for (const a of document.querySelectorAll('a[href*="notif_id"]')) {
      let u;
      try { u = new URL(a.getAttribute("href"), location.href); } catch (e) { continue; }
      const id = u.searchParams.get("notif_id");
      if (!id || out.has(id)) continue;
      const texts = [];
      const w = document.createTreeWalker(a, NodeFilter.SHOW_TEXT);
      let n;
      while ((n = w.nextNode())) {
        const t = n.textContent.replace(/[‎‏‪-‮]/g, "").trim();
        if (t) texts.push({ t, tag: n.parentElement ? n.parentElement.tagName : "" });
      }
      if (!texts.length) continue;   // the avatar link of an entry: no text
      const bold = texts.find((x) => x.tag === "B");
      const last = texts[texts.length - 1].t;
      out.set(id, {
        notif_id: id,
        notif_t: u.searchParams.get("notif_t") || "",
        path: u.pathname,
        post: u.searchParams.get("multi_permalinks") || "",
        group: bold ? bold.t : "",
        ago: AGO_RE.test(last) ? last : "",
        unread: texts[0].t === "Unread",
        text: texts.map((x) => x.t).join(" "),
      });
    }
    return [...out.values()];
  }

  let lastSent = "";
  function send(via) {
    const reason = blockedReason();
    if (reason) {
      chrome.runtime.sendMessage({ type: "blocked", reason, url: location.href });
      return;
    }
    if (!location.pathname.startsWith("/notifications")) return;
    const entries = readEntries();
    const sig = entries.map((e) => e.notif_id).join(",");
    if (!entries.length || sig === lastSent) return;
    lastSent = sig;
    chrome.runtime.sendMessage({ type: "entries", via, entries });
  }

  // first read once the list has rendered, then on every DOM change (debounced):
  // if Facebook pushes new bell entries into the open tab, they arrive as 'live'.
  setTimeout(() => send("load"), 3000);
  let timer = null;
  new MutationObserver(() => {
    clearTimeout(timer);
    timer = setTimeout(() => send("live"), 2000);
  }).observe(document.documentElement, { childList: true, subtree: true });
})();
