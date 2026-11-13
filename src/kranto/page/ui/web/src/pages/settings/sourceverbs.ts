// A source's quiet verbs (UI-v4.md 2.3;): Mute (7 days, 30 days, read less, or retire, a
// small menu in the one popover) and Retire / Watch again; every one says what it did, with Undo.
// By reach (the owner's O-1): Remove from <topic> is this topic only (the // unlink; Undo links it again); Mute, Read less and Retire act on every topic the source feeds,
// and say so when it feeds more than one ("everywhere: all 4 topics"). No confirm: each is
// reversible.
import type { TopicSourcesChange } from "../../api/afk.gen";
import { app } from "../../lib/shell.svelte";
import { closePop, popWith } from "../../ui/pop";
import MuteMenu from "./MuteMenu.svelte";
import { topicList } from "./sources.svelte";

export interface SourceRef {
  id: number;
  label: string;
  /** how many topics it feeds (the reach of an everywhere verb) */
  topics?: number;
}
export interface TopicLite {
  id: number;
  name: string;
}
const dayWord = (s: string | null | undefined): string => (s ? new Date(s).toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : "");
/** an everywhere verb's reach, said when it feeds more than one topic */
export const reachWords = (n: number | undefined): string | null => ((n || 0) > 1 ? `everywhere: all ${n} topics` : null);
const STALE = ["/api/sources", "/api/topics", "/api/today"];
/** Retire a source, or watch a retired one again, with Undo */
export function setSource(btn: HTMLElement | null, s: SourceRef, status: "retired" | "approved"): Promise<void> {
  const L = app();
  if (!L) return Promise.resolve();
  return L.act(btn, () => L.api(`/api/sources/${s.id}/status`, { status }), () => {
    L.afkStale(...STALE); void L.loadHost(); L.render();
    L.toast(status === "retired" ? ((s.topics || 0) > 1 ? `Retired ${s.label} from its ${s.topics} topics: no longer fetched. Its evidence stays.` : `${s.label} is retired: no longer fetched.`)
      : `${s.label} is watched again from the next run.`,
      () => void setSource(null, s, status === "retired" ? "approved" : "retired"));
  });
}
/** what Remove from <topic> says before the press: the reach (the other topics it keeps), or
 * that Kranto stops reading it when this is its only topic */
export function removeNote(others: TopicLite[] | { name: string; kind?: string }[]): string {
  return others.length ? `It keeps feeding ${topicList(others.map((x) => ({ name: x.name, kind: (x as { kind?: string }).kind || "user" })))}` : "It has no other topic: Kranto stops reading it (as Retire)";
}
/** Remove from <topic>: this topic only (an unlink row; its evidence stays). Left with no topic it
 * is retired, never read for everything. The toast names what it still feeds; Undo links it again */
export function removeFrom(btn: HTMLElement | null, s: SourceRef, t: TopicLite): Promise<void> {
  const L = app();
  if (!L) return Promise.resolve();
  return L.act(btn, () => L.api(`/api/topics/${t.id}/sources`, { remove: [s.id], origin: "ui" }), (r) => {
    const x = (r || {}) as Partial<TopicSourcesChange>;
    L.afkStale(...STALE); void L.loadHost(); L.render();
    const left = x.remaining?.[String(s.id)] || [];
    L.toast((x.retired || []).includes(s.id) ? `Removed ${s.label} from ${t.name}. It fed no other topic, so Kranto stops reading it; its evidence stays.`
      : `Removed ${s.label} from ${t.name}.` + (left.length ? ` It still feeds ${topicList(left)}.` : ""), () => void addTo(null, s, t, true));
  });
}
/** Add to <topic>: links it (and watches it again when it was retired); Undo removes it again */
export function addTo(btn: HTMLElement | null, s: SourceRef, t: TopicLite, undo = false): Promise<void> {
  const L = app();
  if (!L) return Promise.resolve();
  return L.act(btn, () => L.api(`/api/topics/${t.id}/sources`, { add: [s.id], origin: "ui" }), () => {
    L.afkStale(...STALE); void L.loadHost(); L.render();
    if (undo) L.toast(`${s.label} feeds ${t.name} again.`);
    else L.toast(`${s.label} feeds ${t.name} too, from the next run.`, () => void removeFrom(null, s, t));
  });
}
/** what you graded of a source's observations (the server's ``grades``, 90 days, CON L7) in
 * words: "1 useful · 3 not useful · 2 off topic"; null when none */
export function gradeWords(g: { useful: number; not_useful: number; wrong: number; reasons: Record<string, number> } | null | undefined): string | null {
  if (!g) return null;
  const chips = Object.entries(g.reasons || {}).sort((a, b) => b[1] - a[1]).map(([k, n]) => `${n} ${k.replace(/_/g, " ")}`);
  const out = [g.useful ? `${g.useful} useful` : null, g.not_useful ? `${g.not_useful} not useful` : null, g.wrong ? `${g.wrong} wrong` : null, ...chips].filter(Boolean);
  return out.length ? out.join(" · ") : null;
}
/** a day as the owner reads it: "28 Oct" */
const dayOf = (iso: string): string => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
/** the source rule's state in words (the server's ``removal``): "Kranto recommends
 * removing it: 4 of its 5 graded posts were not useful in 90 days", or "kept on 28 Oct, after 4 of
 * 5 graded posts were not useful"; null when there is nothing to say */
export function removalWords(r: { recommend: boolean; down: number; up: number; window_days: number; kept: { at: string; down: number; up: number } | null } | null | undefined): string | null {
  if (!r) return null;
  if (r.recommend) return `Kranto recommends removing it: ${r.down} of its ${r.down + r.up} graded posts were not useful in ${r.window_days} days`;
  if (r.kept) return `kept on ${dayOf(r.kept.at)}` + (r.kept.down ? `, after ${r.kept.down} of ${r.kept.down + r.kept.up} graded posts were not useful` : "");
  return null;
}
/** Mute on an observation's source or a source's pane */
/** Mute a source for some days, or read less: on every topic it feeds; the toast offers Undo */
export function muteSource(s: SourceRef, days: number | "less"): void {
  const L = app();
  if (!L) return;
  const done = () => { closePop(); L.afkStale("/api/sources", "/api/topics/", "/api/today"); L.render(); };
  const unmute = () => void L.act(null, () => L.api(`/api/sources/${s.id}/mute`, { days: null }), () => { done(); L.toast(`${s.label} is back to normal from the next run.`); });
  void L.act(null, () => L.api(`/api/sources/${s.id}/mute`, { days }), (r) => {
    done();
    L.toast(days === "less" ? `${s.label} reads half as many items a run, from the next run.`
      : `Muted ${s.label} until ${dayWord(((r || {}) as { muted_until?: string | null }).muted_until)}: it is not read until then.`, unmute);
  });
}
export function muteMenu(btn: HTMLElement, s: SourceRef): void {
  const el = popWith(btn, "Mute " + s.label, MuteMenu, { label: s.label, reach: reachWords(s.topics), pick: (what: string) => {
    if (what === "7") muteSource(s, 7);
    else if (what === "30") muteSource(s, 30);
    else if (what === "less") muteSource(s, "less");
    else { closePop(); void setSource(null, s, "retired"); }
  } }, "menu");
  (el?.querySelector("button") as HTMLElement | null)?.focus();
}
/** a row's ⋯ on a topic's rows: Remove from <topic> first (this topic only), then the
 * everywhere verbs, each saying its reach */
export function rowMenu(anchor: HTMLElement, s: SourceRef & { others: TopicLite[] }, here: TopicLite): void {
  const reach = reachWords(s.topics);
  app()?.menu(anchor, [
    { label: `Remove from ${here.name}`, id: "src-remove", note: removeNote(s.others), run: () => void removeFrom(null, s, here) },
    { label: "Mute for 7 days", id: "src-mute", group: "everywhere", note: reach, run: () => muteSource(s, 7) },
    { label: "Read less", id: "src-less", group: "everywhere", note: reach, run: () => muteSource(s, "less") },
    { label: "Retire", id: "src-retire", group: "everywhere", note: reach, run: () => void setSource(null, s, "retired") }]);
}
