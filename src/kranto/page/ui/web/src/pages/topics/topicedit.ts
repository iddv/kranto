// Edit a topic: one sheet, Edit on the topic's page and on its row, for its name and
// description, its sources (added from the library, removed from this topic only) and its own
// settings (News's brief; Paused); Save writes what changed and says
// so with one Undo that puts every part back. Archive takes the topic off your lists (not read;
// its evidence, themes and ideas stay readable) with Undo, never a confirm. Every write names the
// door it came through (origin ui); the server records it.
import type { TopicEdit, TopicSourcesChange, TopicStatusChange } from "../../api/afk.gen";
import { go, parse } from "../../lib/router";
import { app } from "../../lib/shell.svelte";
import { openDialog } from "../../ui/dialog.svelte";
import TopicEditSheet from "./TopicEdit.svelte";

/** what a topic's Save changes, from the sheet */
export interface TopicDraft {
  id: number;
  name: string;
  before: { name: string; description: string };
  words: { name: string; description: string };
  add: number[];
  remove: number[];
  /** a source's review before it was added (Undo sets it back when it was not approved) */
  was: Record<number, string>;
  status: { from: string; to: string } | null;
  news: { from: boolean; to: boolean } | null;
}

export const NEWS_TOGGLE = "/api/f/news/act/toggle";
const STALE = ["/api/topics", "/api/sources", "/api/today", "/api/catalog", "/api/f/"];

/** the sheet for topic id */
export function editTopic(id: number | string): void {
  app()?.afkDropPrefix(`/api/topics/${id}`); // the sheet fills from a fresh read
  openDialog(TopicEditSheet, { id: Number(id) }, { wide: true });
}

/** what a draft changes, in words ("its description, 1 source removed"); empty when nothing */
export function changeWords(d: TopicDraft): string[] {
  const out: string[] = [];
  const named = d.words.name !== d.before.name, said = d.words.description !== d.before.description;
  if (named) out.push(`renamed ${d.before.name} to ${d.words.name}`);
  if (said) out.push("its description");
  if (d.add.length) out.push(`${d.add.length} source${d.add.length === 1 ? "" : "s"} added`);
  if (d.remove.length) out.push(`${d.remove.length} source${d.remove.length === 1 ? "" : "s"} removed`);
  if (d.status) out.push(d.status.to === "paused" ? "paused" : "resumed");
  if (d.news) out.push(d.news.to ? "News on" : "News off");
  return out;
}

/** Save: each part that changed, in one press; then one line with Undo for all of it */
export async function saveTopic(btn: HTMLElement | null, d: TopicDraft, close: () => void): Promise<void> {
  const L = app();
  if (!L) return;
  const said = changeWords(d);
  if (!said.length) {
    close();
    return;
  }
  const done: { words?: TopicEdit; sources?: TopicSourcesChange } = {};
  await L.act(btn, async () => {
    const w: Record<string, string> = {};
    if (d.words.name !== d.before.name) w.name = d.words.name;
    if (d.words.description !== d.before.description) w.description = d.words.description;
    if (Object.keys(w).length) done.words = (await L.api(`/api/topics/${d.id}`, { ...w, origin: "ui" })) as TopicEdit;
    if (d.add.length || d.remove.length) done.sources = (await L.api(`/api/topics/${d.id}/sources`, { add: d.add, remove: d.remove, origin: "ui" })) as TopicSourcesChange;
    if (d.status) await L.api(`/api/topics/${d.id}/status`, { status: d.status.to, origin: "ui" });
    if (d.news) await L.api(NEWS_TOGGLE, { fields: { topic_id: d.id, on: d.news.to } });
  }, () => {
    close();
    L.afkStale(...STALE);
    void L.loadHost();
    L.render();
    const name = d.words.name;
    L.toast(`Saved ${name}: ${said.join(", ")}.` + (done.sources?.retired.length ? ` ${done.sources.retired.length === 1 ? "A source" : "Sources"} left with no topic ${done.sources.retired.length === 1 ? "is" : "are"} retired, not read.` : ""),
      () => void undoSave(d, done));
  });
}

/** Undo of a Save: each part back as it was (new rows in the server, never a delete) */
export async function undoSave(d: TopicDraft, done: { words?: TopicEdit; sources?: TopicSourcesChange }): Promise<void> {
  const L = app();
  if (!L) return;
  await L.act(null, async () => {
    if (done.words?.revision) await L.api(`/api/topics/${d.id}`, { ...done.words.revision.before, origin: "ui", note: "undo" });
    const s = done.sources;
    if (s && (s.added.length || s.removed.length)) {
      await L.api(`/api/topics/${d.id}/sources`, { add: s.removed, remove: s.added, origin: "ui" });
      for (const sid of s.approved) if (d.was[sid] && d.was[sid] !== "approved") await L.api(`/api/sources/${sid}/status`, { status: d.was[sid] });
    }
    if (d.status) await L.api(`/api/topics/${d.id}/status`, { status: d.status.from, origin: "ui" });
    if (d.news) await L.api(NEWS_TOGGLE, { fields: { topic_id: d.id, on: d.news.from } });
  }, () => {
    L.afkStale(...STALE);
    void L.loadHost();
    L.render();
    L.toast(`${d.before.name} is back as it was.`);
  });
}

/** Archive: off your lists and not read; its evidence, themes and ideas stay. Undo, no confirm */
export function archiveTopic(btn: HTMLElement | null, t: { id: number; name: string }, close?: () => void): Promise<void> {
  const L = app();
  if (!L) return Promise.resolve();
  return L.act(btn, () => L.api(`/api/topics/${t.id}/status`, { status: "archived", origin: "ui" }), (r) => {
    close?.();
    const was = (r as TopicStatusChange).was || "active";
    L.afkStale(...STALE);
    void L.loadHost();
    const at = parse().path.join("/");
    if (at === `topics/${t.id}` || at.startsWith(`topics/${t.id}/`) || at === `watch/topic/${t.id}` || at.startsWith(`watch/topic/${t.id}/`)) go("watch");
    else L.render();
    L.toast(`${t.name} is archived: not read, and off your lists. Its evidence and ideas stay; it is under Archived on Watch › Topics.`,
      () => void restoreTopic(null, t, was));
  });
}

/** Pause or Resume a topic: its sources are not read while it is paused; nothing is removed */
export function pauseTopic(btn: HTMLElement | null, x: { id: number; name: string; status: string }): void {
  const L = app();
  if (!L) return;
  const paused = x.status === "paused";
  void L.act(btn, async () => {
    const r = await L.api(`/api/topics/${x.id}/status`, { status: paused ? "active" : "paused" });
    L.afkDrop();
    return r;
  }, () => {
    void L.loadHost();
    L.say(paused ? `${x.name} is active again: its sources are read from the next run.` : `${x.name} is paused: its sources are not read until you resume it. Nothing is removed.`);
  });
}

/** Restore an archived topic (Undo of Archive, or Restore on its row under Archived) */
export function restoreTopic(btn: HTMLElement | null, t: { id: number; name: string }, to = "active"): Promise<void> {
  const L = app();
  if (!L) return Promise.resolve();
  return L.act(btn, () => L.api(`/api/topics/${t.id}/status`, { status: to, origin: "ui" }), () => {
    L.afkStale(...STALE);
    void L.loadHost();
    L.render();
    L.toast(to === "paused" ? `${t.name} is back, paused.` : `${t.name} is back: its sources are read from the next run.`,
      () => void archiveTopic(null, t));
  });
}
