// AgentLead bell reader - service worker.
// Keeps ONE pinned facebook.com/notifications tab open. Facebook pushes new bell
// entries into an open tab live (measured 2026-11-22: a new entry appeared 58 s in,
// no reload), so the content script's MutationObserver does the real work and
// costs no requests. The reload here is only a safety net in case that live
// connection drops: every 30-45 min (random), 07:00-23:30 local time, never while
// Or is looking at the tab. Any block/checkpoint sign stops it for 3 days.

const RECV = "http://127.0.0.1:8765/fb";
const BELL = "https://www.facebook.com/notifications";
const MIN_GAP = 30, MAX_GAP = 45;             // minutes between safety-net reloads
const DAY_START = 7 * 60, DAY_END = 23 * 60 + 30;
const KILL_MS = 3 * 24 * 3600 * 1000;

async function post(body) {
  try {
    await fetch(RECV, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-AgentLead-Bell": "1" },
      body: JSON.stringify({ ...body, at: Date.now() }),
    });
  } catch (e) { /* receiver down: nothing is lost that the next reload won't resend */ }
}

function schedule() {
  chrome.alarms.create("bell", { delayInMinutes: MIN_GAP + Math.random() * (MAX_GAP - MIN_GAP) });
}

async function killedUntil() {
  const { killedUntil = 0 } = await chrome.storage.local.get("killedUntil");
  return killedUntil;
}

async function ensureTab() {
  // returns the bell tab, opening it (pinned, in the background) when missing
  const tabs = await chrome.tabs.query({ url: BELL + "*" });
  if (tabs.length) return { tab: tabs[0], opened: false };
  const t = await chrome.tabs.create({ url: BELL, active: false, pinned: true });
  chrome.tabs.update(t.id, { autoDiscardable: false });
  return { tab: t, opened: true };
}

async function tick() {
  schedule();
  const until = await killedUntil();
  if (Date.now() < until) { post({ type: "heartbeat", state: "killed", until }); return; }
  const now = new Date();
  const mins = now.getHours() * 60 + now.getMinutes();
  if (mins < DAY_START || mins > DAY_END) { post({ type: "heartbeat", state: "night" }); return; }

  const { tab: t, opened } = await ensureTab();
  if (opened) { post({ type: "heartbeat", state: "opened_tab" }); return; }
  chrome.tabs.update(t.id, { autoDiscardable: false });
  const win = await chrome.windows.get(t.windowId);
  if (t.active && win.focused) { post({ type: "heartbeat", state: "user_on_tab" }); return; }
  chrome.tabs.reload(t.id);
  post({ type: "heartbeat", state: "reloaded" });
}

async function start(state) {
  schedule();
  if (Date.now() < (await killedUntil())) { post({ type: "heartbeat", state: "killed" }); return; }
  await ensureTab();
  post({ type: "heartbeat", state });
}

chrome.runtime.onInstalled.addListener(() => start("installed"));
chrome.runtime.onStartup.addListener(() => start("startup"));
chrome.alarms.onAlarm.addListener((a) => { if (a.name === "bell") tick(); });

chrome.runtime.onMessage.addListener(async (msg) => {
  if (msg.type === "entries") post({ type: "entries", via: msg.via, entries: msg.entries });
  if (msg.type === "blocked") {
    if (Date.now() < (await killedUntil())) return;   // already stopped: alert once, not per DOM change
    chrome.storage.local.set({ killedUntil: Date.now() + KILL_MS });
    post({ type: "blocked", reason: msg.reason, url: msg.url });
  }
});
