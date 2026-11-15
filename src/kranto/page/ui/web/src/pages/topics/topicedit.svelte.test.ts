import { afterEach, describe, expect, it, vi } from "vitest";
import { flushSync } from "svelte";
import type { Facts } from "../../lib/app";
import { ui } from "../../lib/shell.svelte";
import { answering, draw, settle, stub, where } from "../testing.svelte";
import TopicsDigest from "../watch/Topics.svelte";
import TopicEdit from "./TopicEdit.svelte";
import { changeWords, type TopicDraft } from "./topicedit";
import { topicApi } from "./topics";

// Edit a topic: the sheet, its Save with one Undo, Archive with Undo, Restore under Archived
const NOW = new Date().toISOString();
const row = (id: number, label: string, topics: { id: number; name: string }[], review = "approved") => ({ id, kind: "rss", label, review, site_name: "Feeds", topics });
const PAGE = {
  id: 1, name: "Energy", description: "Solar and batteries in Africa.", kind: "user", ref: null, status: "active", created_at: NOW, sources: 2, proposed: 0,
  items_per_day: 2, kept_per_day: 1, observations: 10, themes: 0, rising: 0, spend_month_usd: 0, tokens_month: null, themes_list: [], rising_now: [], snapshot: null,
  prefilter: 0.3, every_hours: 6, budget_usd: null, progress: "", grade_labels: {}, grade_choices: [],
  history: [{ what: "edit", at: "2026-10-22T19:00:00Z", by: "ui", note: null, changed: ["name"], name: "Energy" }],
  source_rows: [row(1, "Energy Feed", [{ id: 1, name: "Energy" }]), row(2, "Shared", [{ id: 1, name: "Energy" }, { id: 3, name: "Storage" }])],
};
const SOURCES = { sources: [row(1, "Energy Feed", [{ id: 1, name: "Energy" }]), row(2, "Shared", [{ id: 1, name: "Energy" }]), row(9, "Battery Weekly", [], "retired")] };
const answers = () => answering({ [topicApi(1)]: PAGE, "/api/sources": SOURCES, "/api/features": { features: [], api: "", reads: [], request_kinds: [] } });
const hosted = () => { ui.facts = { header: { host: { paused: false } } } as unknown as Facts; };
afterEach(() => { ui.facts = null; });

function sheet() {
  const L = stub({ answer: { id: 1, changed: ["description"], revision: { id: 4, topic_id: 1, changed: ["description"], by: "ui", created_at: NOW,
    before: { name: "Energy", description: "Solar and batteries in Africa." }, after: { name: "Energy", description: "Off-grid solar." } } } });
  Object.assign(L, { pageKey: vi.fn(), menu: vi.fn() });
  hosted();
  answers();
  const close = vi.fn();
  return { L, close };
}
const field = (t: HTMLElement, sel: string, v: string) => {
  const el = t.querySelector(sel) as HTMLInputElement | HTMLTextAreaElement;
  el.value = v;
  el.dispatchEvent(new Event("input", { bubbles: true }));
  flushSync();
};

describe("Edit a topic", () => {
  it("shows its words, says what the description feeds, and saves a new description with Undo", async () => {
    const { L, close } = sheet();
    const { target, done } = await draw(TopicEdit as never, where("watch"), null, { id: 1, close });
    expect(target.querySelector("#dlg-t")?.textContent).toBe("Edit Energy");
    expect((target.querySelector("#te-name") as HTMLInputElement).value).toBe("Energy");
    expect(target.querySelector("#te-desc-says")?.textContent).toContain("the idea cards written from this topic read them");
    expect(target.querySelector("#te-says")?.textContent).toBe("Nothing changed yet.");
    expect(target.querySelector("#te-last")?.textContent).toBe("Last change: 2026-10-22 19:00, from this page.");
    field(target, "#te-desc", "Off-grid solar.");
    expect(target.querySelector("#te-says")?.textContent).toBe("Save: its description.");
    (target.querySelector("#dlg-ok") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/topics/1", { description: "Off-grid solar.", origin: "ui" });
    expect(close).toHaveBeenCalled();
    const [said, undo] = L.toast.mock.calls[0] as [string, () => void];
    expect(said).toBe("Saved Energy: its description.");
    undo();
    await settle();
    expect(L.api).toHaveBeenLastCalledWith("/api/topics/1", { name: "Energy", description: "Solar and batteries in Africa.", origin: "ui", note: "undo" });
    done();
  });

  it("draws the topic's own rows: Remove from this topic and Add from the library at once, each with Undo", async () => {
    const { L, close } = sheet();
    L.api.mockImplementation(async (path: string, body: { add?: number[]; remove?: number[] }) => (path.endsWith("/sources")
      ? { id: 1, added: body.add || [], removed: body.remove || [], retired: [], approved: [], remaining: body.remove ? { [String(body.remove[0])]: [{ id: 3, name: "Storage", kind: "user" }] } : {} } : {}));
    const { target, done } = await draw(TopicEdit as never, where("watch"), null, { id: 1, close });
    // the same rows as the topic's page and its Sources (TopicSourceRows), Remove visible on each
    const rows = [...target.querySelectorAll("#te-sources li.row")] as HTMLElement[];
    expect(rows.map((r) => r.querySelector(".r-title")?.textContent)).toEqual(["Energy Feed", "Shared"]);
    expect(rows[1]!.querySelector(".c-meta")?.textContent).toContain("also feeds Storage");
    (rows[1]!.querySelector("[data-act=te-remove]") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/topics/1/sources", { remove: [2], origin: "ui" });
    const [said, undo] = L.toast.mock.calls[0] as [string, () => void];
    expect(said).toBe("Removed Shared from Energy. It still feeds Storage.");
    undo();
    await settle();
    expect(L.api).toHaveBeenLastCalledWith("/api/topics/1/sources", { add: [2], origin: "ui" });
    // one from the library, at once; Save stays for the words and switches
    field(target, "#te-find", "battery");
    expect(target.querySelector("#te-found")?.textContent).toContain("Battery Weekly");
    (target.querySelector("#te-found [data-act=te-add]") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenLastCalledWith("/api/topics/1/sources", { add: [9], origin: "ui" });
    expect((L.toast.mock.calls.at(-1) as [string])[0]).toBe("Battery Weekly feeds Energy too, from the next run.");
    expect(target.querySelector("#te-says")?.textContent).toBe("Nothing changed yet.");
    expect(target.querySelector("#te-src-more a")?.getAttribute("href")).toBe("#/settings/sources/new?topic=1");
    expect(target.querySelector("#te-scout")?.textContent).toBe("Scout more");
    done();
  });

  it("needs a name and a description before Save", async () => {
    const { close } = sheet();
    const { target, done } = await draw(TopicEdit as never, where("watch"), null, { id: 1, close });
    field(target, "#te-desc", "  ");
    expect((target.querySelector("#dlg-ok") as HTMLButtonElement).disabled).toBe(true);
    expect(target.querySelector("#te-says")?.textContent).toBe("A topic needs a description: it is what items are compared with.");
    done();
  });

  it("archives with Undo, never a confirm", async () => {
    const { L, close } = sheet();
    L.api.mockImplementation(async () => ({ id: 1, status: "archived", was: "paused", changed: true }));
    const { target, done } = await draw(TopicEdit as never, where("watch"), null, { id: 1, close });
    (target.querySelector("#te-archive") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/topics/1/status", { status: "archived", origin: "ui" });
    expect(close).toHaveBeenCalled();
    const [said, undo] = L.toast.mock.calls[0] as [string, () => void];
    expect(said).toBe("Energy is archived: not read, and off your lists. Its evidence and ideas stay; it is under Archived on Watch › Topics.");
    undo();
    await settle();
    expect(L.api).toHaveBeenLastCalledWith("/api/topics/1/status", { status: "paused", origin: "ui" });
    done();
  });

  it("says each part a draft changes", () => {
    const d: TopicDraft = { id: 1, name: "A", before: { name: "A", description: "x" }, words: { name: "B", description: "x" }, add: [], remove: [2, 3], was: {},
      status: { from: "active", to: "paused" }, news: { from: false, to: true } };
    expect(changeWords(d)).toEqual(["renamed A to B", "2 sources removed", "paused", "News on"]);
  });
});

describe("Watch › Topics", () => {
  it("has Edit on each row and the archived topics under Archived, each with Restore", async () => {
    const L = stub({ answer: { id: 5, status: "active", was: "archived", changed: true } });
    Object.assign(L, { pageKey: vi.fn(), menu: vi.fn() });
    hosted();
    const t = (id: number, name: string, status: string) => ({ ...PAGE, id, name, status });
    answering({ "/api/topics": { topics: [t(1, "Energy", "active")], archived: [t(5, "Old", "archived")], broad: [],
      all: { observations: 10, sources: 2, themes: 0, items_per_day: 2, map: null }, progress: "", every_hours: 6, theme_min_share: 0.2 }, "/api/today": { topics: [] } });
    const { target, done } = await draw(TopicsDigest, where("watch"));
    // the row's other verbs are under its ⋯: Edit, Pause topic, Archive
    (target.querySelector("#tp")?.closest("section")?.querySelector(".row-more") as HTMLButtonElement).click();
    const items = (L as unknown as { menu: ReturnType<typeof vi.fn> }).menu.mock.calls[0]![1] as { label: string; run: () => void }[];
    expect(items.map((x) => x.label)).toEqual(["Edit", "Pause topic", "Archive"]);
    const arch = target.querySelector("#tp-archived")!.closest("section")!;
    expect(arch.querySelector(".r-title")?.textContent).toBe("Old");
    (arch.querySelector("[data-act=topic-restore]") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/topics/5/status", { status: "active", origin: "ui" });
    expect((L.toast.mock.calls[0] as [string])[0]).toBe("Old is back: its sources are read from the next run.");
    done();
  });
});
