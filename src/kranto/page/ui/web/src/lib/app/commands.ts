// The command palette's items (⌘K, UI-v4.md 2.4; drawn by Palette.svelte). Ideas (the server's cards,
// /api/ideas) and topics are searched here; evidence and sources come from the server's /api/search
// (words and meaning), which the palette asks and passes in (srv). enter opens; ⌘enter runs the
// row's primary action.
import { go, href, parse } from "../router";
import { palScore, type PalItem } from "../palette";
import { cut, firstSentence } from "../format";
import { peek, read } from "../reads.svelte";
import { iconsNow, LAYOUT, layoutReset, navIcons } from "../shell.svelte";
import { baseWords, customNow, flipTo, isDark, lookChoices, lookNow, setLook, setTheme, themeNow } from "../theme";
import { afkJob } from "../job";
import { toast } from "../../ui/toast.svelte";
import { IDEA_GROUPS, ideaOf, ideaTitle } from "../../pages/ideas/ideas";
import { cardIdeas } from "../../pages/ideas/cards";
import { ideaItems } from "../../pages/ideas/verbs";
import { obsHref } from "../../pages/library/library";
import { TICKS } from "../../pages/topics/proposals";
import { act, afkDrop, afkPaused, api, flash, host, PAUSES, say, togglePause, updApply, updBusy, updNow } from "./data";
import { checkNow, versionNow } from "../../pages/settings/checkupdates";
import { navTree, SET } from "./chrome";
import { keySheet, pageHas, render, routeNow } from "./route";
import { DOOR_NAV, doorNav } from "./chrome";
import { WATCH_PAGES, watchPath } from "./watchscope";
import { frameNew, shellDoors } from "../../features/shell";
import { cubsOf, features } from "../../features/index";
import { ADVANCED_PAGES, doorsPage, DOORS_PAGES } from "../../pages/settings/doorpages";
import { openFeedback } from "../../ui/sendFeedback";
import { toggleConsole } from "../../term/console.svelte";
import type { Activity } from "../../api/types.gen";

/* With the doors on: the last three things opened, kept by this page only (it
   stores nothing but its look), first in the palette before anything is typed */
const RECENT: { title: string; go: string }[] = [];
export function noteRecent(title: string, go: string): void {
  if (!title) return;
  const i = RECENT.findIndex((x) => x.go === go || x.title === title);
  if (i >= 0) RECENT.splice(i, 1);
  RECENT.unshift({ title, go });
  RECENT.length = Math.min(RECENT.length, 3);
}
export const recentNow = (): readonly { title: string; go: string }[] => RECENT;
/** the doors' Go to: Home, Needs you, every door and each of its subnav's words, the cubs,
 * every Settings page (Advanced too) */
function doorsGo(): Item[] {
  const out: Item[] = [{ g: "Go to", title: "Home", go: "#/home", keys: "g h" }, { g: "Go to", title: "Needs you", go: "#/needs", keys: "g t" }];
  for (const id of Object.keys(DOOR_NAV)) {
    if (id === "needs" || id === "settings") continue;
    const d = doorNav(id);
    // Watch's Sources, Evidence and Map here are All topics' (a topic's own are listed by its name)
    for (const [to, w] of d.items) out.push({ g: "Go to", title: w === d.word ? d.word : id === "watch" && to !== "watch" ? `Watch › All topics › ${w}` : `${d.word} › ${w}`, go: "#/" + to });
  }
  // Post, the fourth door, and each posting cub's own page under it
  out.push({ g: "Go to", title: "Post", go: "#/post" });
  // the console, which is beside every page (B, Codex 21: "console" found game consoles)
  out.push({ g: "Go to", title: "Console", detail: "your Claude Code or Codex, beside every page", run: () => toggleConsole(), keys: "⌘J" });
  for (const x of cubsOf(features(!!host()))) out.push({ g: "Go to", title: "Post › " + x.title, go: "#/cub/" + x.id });
  out.push({ g: "Go to", title: "Settings", go: "#/settings", keys: "g s" });
  for (const k of [...DOORS_PAGES, ...ADVANCED_PAGES]) {
    const p = doorsPage(k);
    if (p) out.push({ g: "Go to", title: "Settings › " + p.title, detail: DOORS_PAGES.includes(k) ? null : "Advanced", go: "#/settings/" + k });
  }
  // every feature's and cub's own Settings page: "settings news" finds it
  for (const x of features(!!host())?.features || []) out.push({ g: "Go to", title: "Settings › " + x.title, detail: "Features", go: "#/settings/" + x.id });
  return out;
}
/** Settings by name or by its dotted key (every key reachable, ⌘K finds it) */
function settingsFound(q: string): Item[] {
  const out: Item[] = [];
  // a feature's and a cub's keys, on their Settings page, by their words or their key
  for (const x of features(!!host())?.features || []) {
    for (const r of x.settings || []) {
      const w = `${x.title} › ${r.words || r.key}`, s = palScore(q, w, r.key);
      if (s) out.push({ g: "Settings", title: w, detail: r.key, go: href("settings/" + x.id, { sel: "e" + r.key }), score: s });
    }
  }
  return out;
}

type Item = Omit<PalItem, "score"> & { score?: number };

function palCommands(): Item[] {
  const out: Item[] = [], goTo = (to: string, w: string, key?: string | null) => out.push({ g: "Commands", title: "Go to " + w, go: "#/" + to, keys: key || null });
  const t = navTree(parse()), H = host(), doors = shellDoors(!!H);
  if (doors) out.push(...doorsGo(), { g: "Commands", title: "Add topic", go: "#/topics/new" });
  // a topic's own Sources, Evidence and Map by the word ("sources" found ideas before
  // these; WT: Watch is topic-first, its pages a topic's), and All topics' (doorsGo: Watch › …)
  for (const tp of H ? H.topics : []) {
    for (const [k, w] of WATCH_PAGES) out.push({ g: doors ? "Go to" : "Commands", title: `${doors ? "" : "Go to "}${tp.name} › ${w}`, detail: k === "sources" ? "the sources this topic reads" : k === "evidence" ? "what this topic kept" : "this topic's themes",
      go: doors ? "#/" + watchPath(tp.id, k) : href(k === "map" ? `topics/${tp.id}/themes` : `topics/${tp.id}/${k}`) });
  }
  for (const x of doors ? [] : t.rows) {
    if (x.head) {
      if (x.to) goTo(x.to, x.head);
      if (x.add) out.push({ g: "Commands", title: "Add topic", go: "#/" + x.add });
    } else goTo(x.to, x.w, x.key);
  }
  // every Settings page, with its twisty closed too
  if (!doors) for (const [k, w] of SET) if (!out.some((o) => o.go === "#/settings/" + k)) goTo("settings/" + k, w);
  // the console, beside every page in either frame (doorsGo has it with the doors on)
  if (!doors) out.push({ g: "Commands", title: "Console", detail: "your Claude Code or Codex, beside every page", run: () => toggleConsole(), keys: "⌘J" });
  for (const tp of H ? H.topics : []) out.push({ g: "Commands", title: "Scout more for " + tp.name, detail: "about 30 s; proposals wait for you on its Sources",
    run: () => {
      say(`Scouting for ${tp.name}… its proposals show on its Sources when it finishes.`);
      return act(null, async () => afkJob(await api(`/api/topics/${tp.id}/scout`, {}), `/api/topics/${tp.id}/scout`), (r) => {
        const x = r as { message: string; proposals: { id: number; pretick?: boolean }[] };
        afkDrop();
        const tk = (TICKS[tp.id] = TICKS[tp.id] || new Set());
        for (const p of x.proposals) if (p.pretick) tk.add(p.id);
        flash(x.message + " Tick what to watch under Proposed.");
        go(`topics/${tp.id}/sources`);
      });
    } });
  // the selected idea's verbs: what ⋯ and its keys have, named "Persistent memory: Pass"
  const w = routeNow(), si = w && w.object === "idea" && w.id ? ideaOf(w.id) : null;
  if (si) for (const x of ideaItems(si)) {
    if (x.why) continue;
    out.push({ g: "Commands", title: `${ideaTitle(si)}: ${x.label}`, keys: x.key, run: x.run as never });
  }
  // what Kranto is doing: the page, each running run's trace and its Stop
  out.push({ g: "Commands", title: "What is Kranto doing?", detail: "Activity: what runs, what waits on you, what comes next", keys: "g a", go: "#/activity" });
  for (const x of (peek<Activity>("api/activity")?.data?.running || []).slice(0, 5)) {
    if (x.trace) out.push({ g: "Commands", title: `Trace of ${x.title}`, detail: x.words || "running now", go: x.trace + "?follow=1" });
    if (x.stoppable) out.push({ g: "Commands", title: `Stop ${x.title}`, detail: "at its next step; what it did so far stays", go: "#/activity" });
  }
  // Check for updates (the owner, 2026-10-22), and Update Kranto when a release is on offer
  const ver = versionNow();
  if (ver) {
    out.push({ g: "Commands", title: "Check for updates", detail: `Kranto ${ver}; the answer shows at the top of the page`,
      run: () => void checkNow().then((a) => say(a.text + (a.next && !a.next.restart ? ` · ${a.next.word}` : ""), a.tone === "red" ? "red" : undefined)) });
    const u = updNow();
    if (u && u.available && u.can_apply && !updBusy(u))
      out.push({ g: "Commands", title: "Update Kranto", detail: `${u.installed} → ${u.available}; restarts Kranto`, run: () => void updApply(null) });
  }
  const paused = afkPaused();
  if (H) out.push({ g: "Commands", title: paused ? "Resume" : "Pause", detail: PAUSES, run: () => togglePause(null, !paused) });
  const dark = isDark(), look = lookNow();
  const to = flipTo(); // Auto again when the other scheme is the device's (QA B18)
  out.push({ g: "Commands", title: dark ? "Switch to light" : "Switch to dark", detail: to === "auto" ? "back to Auto: follows your device" : themeNow() === "auto" ? "Auto is off until you choose it again (Settings › Appearance)" : "Settings › Appearance",
    run: () => { setTheme(to); render(); toast(baseWords(to)); } });
  for (const [id, lw, blurb] of lookChoices()) out.push({ g: "Commands", title: "Theme: " + lw, detail: id === look ? "in use" : blurb, run: () => { setLook(id); render(); } });
  if (!customNow()) out.push({ g: "Commands", title: "Theme: Custom", detail: "pick five colours of your own", go: href("settings/appearance", { sel: "ecustom" }) });
  const seen = pageHas("⇧a");
  if (seen) out.push({ g: "Commands", title: "Mark all seen", keys: "⇧a", run: seen });
  // the navigator's own commands, while it draws (without the server; hosted is one layout, New)
  if (!frameNew(!!H)) out.push({ g: "Commands", title: iconsNow() ? "Layout: expand the navigator" : "Layout: collapse the navigator", detail: iconsNow() ? "its words again" : "56 px icons with their counts", run: () => navIcons(!iconsNow()) });
  if (!frameNew(!!H) && Object.keys(LAYOUT.read()).length) out.push({ g: "Commands", title: "Layout: reset the column widths", detail: "the navigator and the detail pane", run: layoutReset });
  out.push({ g: "Commands", title: "Keyboard shortcuts", keys: "?", run: keySheet });
  out.push({ g: "Commands", title: "Send feedback", detail: "a bug, an idea or a question: an issue on Kranto's GitHub, from you", run: () => openFeedback() });
  return out;
}
export function palItems(q: string, srv: { query: string; results: unknown[] } | null): PalItem[] {
  const items: PalItem[] = [], H = host();
  if (!q.trim()) return [...(shellDoors(!!H) ? RECENT.map((x): Item => ({ g: "Recent", title: x.title, go: x.go })) : []), ...palCommands()].map((x) => ({ ...x, score: 1 }) as PalItem);
  const add = (x: Item, score: number) => {
    if (score) items.push({ ...x, score } as PalItem);
  };
  // Ideas' own cards and their state words (Waiting, Later, Posted, Passed)
  const ci = H ? cardIdeas() : null;
  if (ci) for (const x of ci.list) add({ g: "Ideas", title: x.title, detail: [`#${x.number}`, IDEA_GROUPS.find(([k]) => k === (x.state || "waiting"))?.[1]].filter(Boolean).join(" · "), go: href("ideas/" + x.number) },
    palScore(q, x.title, String(x.raw?.one_liner || ""), `#${x.number}`));
  for (const t of H ? H.topics : []) add({ g: "Topics", title: t.name, detail: "topic", go: href("topics/" + t.id) }, palScore(q, t.name, t.description));
  // an answer without results (an older the server, a fake one) finds nothing, never breaks the list
  const found = (srv && srv.query === q.trim() && Array.isArray(srv.results) ? srv.results : []) as { kind: string; id: number; title: string; detail: string; score?: number }[];
  for (const x of found) {
    // The server's search arrives later: it ranks half a step under a match of the page's own, so
    // the groups already shown do not jump
    if (x.kind === "observation") add({ g: "Evidence", title: x.title, detail: `#${x.id} · ${x.detail}`, go: obsHref(x.id) }, Math.max(1, palScore(q, x.title)) - 0.5 + (x.score || 0) / 10);
    else if (x.kind === "source") add({ g: "Sources", title: x.title, detail: x.detail, go: "#/settings/sources/" + x.id }, Math.max(1, palScore(q, x.title)) - 0.5);
  }
  if (shellDoors(!!H)) for (const x of settingsFound(q)) add(x, x.score || 0);
  for (const x of palCommands()) add(x, palScore(q, x.title, x.detail));
  return items;
}

/* Settings › Prompts' preview: the real items a prompt can be previewed against, by what it takes
   (PM-API.md, Preview): the server's cards, topics and observations */
export function previewSubjects(p: { id: string; subject?: string | null }): [string, string][] {
  const s = p.subject, H = host();
  if (!s || s === "none") return [];
  if (s === "idea") {
    const ci = H ? cardIdeas() : null;
    return ci ? ci.list.slice(0, 40).map((x) => [String(x.number), cut(`#${x.number} ${x.title}`, 80)]) : [];
  }
  if (s === "topic") return (H ? H.topics : []).map((t) => [String(t.id), t.name]);
  if (s === "observation") {
    const c = H ? read<{ results: { id: number; summary: string }[] }>("/api/observations?limit=20&sort=new", 60000) : null;
    return c && c.data ? c.data.results.map((o) => [String(o.id), cut(`#${o.id} ${firstSentence(o.summary)}`, 80)]) : [];
  }
  return [];
}
