import { afterEach, describe, expect, it, vi } from "vitest";
import type { Facts } from "../../lib/app";
import type { Where } from "../../lib/pages.svelte";
import { ui } from "../../lib/shell.svelte";
import { answering, draw, stub, where } from "../testing.svelte";
import { topicList, topicWords } from "../settings/sources.svelte";
import { TOPICS_API, topicApi } from "../topics/topics";
import Sources from "./Sources.svelte";

// The server's /api/topics (yours, the broad lane) and ?kind=project, trimmed to what the chips read
const T = (id: number, name: string, sources: number, kind = "user") => ({ id, name, kind, sources, status: "active" });
const MINE = { topics: [T(13, "Robotics", 19), T(2, "Local-first", 6)], archived: [], broad: [{ id: 9 }, { id: 10 }], all: { sources: 130 } };
const PROJ = { topics: [T(40, "Plotkeeper (project)", 3, "project")], archived: [], broad: [], all: { sources: 130 } };
const at = (path: string, q: Record<string, string> = {}): Where => ({ ...where(path), r: { path: path.split("/"), q, sel: null } });
afterEach(() => { ui.facts = null; });

describe("a source's topics in words", () => {
  const link = (id: number, name: string, kind = "user") => ({ id, name, kind });
  it("names yours first, then says how many more", () => {
    expect(topicList([link(1, "Robotics")])).toBe("Robotics");
    expect(topicList([link(5, "Receipts (project)", "project"), link(1, "AI developer tooling")])).toBe("AI developer tooling and Receipts (project)");
    expect(topicList([link(1, "AI developer tooling"), link(2, "LLM tooling"), link(5, "Receipts (project)", "project"), link(6, "Sidedoor (project)", "project")]))
      .toBe("AI developer tooling, LLM tooling and 2 more");
  });
  it("on a topic's rows says what else it feeds; elsewhere its topics, or that it has none", () => {
    const shared = { topics: [link(13, "Robotics"), link(2, "Local-first")], group: "approved", review: "approved" };
    expect(topicWords(shared, 13)).toBe("also feeds Local-first");
    expect(topicWords({ ...shared, topics: [link(13, "Robotics")] }, 13)).toBeNull();
    expect(topicWords(shared)).toBe("Robotics and Local-first");
    expect(topicWords({ topics: [], group: "broad", review: "approved" })).toBe("no topic: every item is judged");
    expect(topicWords({ topics: [], group: "proposed", review: "proposed" })).toBeNull();
  });
});

describe("Watch › Sources by topic", () => {
  it("draws the chips: All, each of your topics with its own number, No topic (Project topics left with projects, C3)", async () => {
    const L = stub();
    const menu = vi.fn();
    Object.assign(L, { menu, sigOf: (n: Element) => n.className, pageKey: vi.fn(), tip: () => null });
    ui.facts = { header: { host: { paused: false } } } as unknown as Facts;
    answering({ [TOPICS_API]: MINE, [TOPICS_API + "?kind=project"]: PROJ, [topicApi(13)]: { id: 13, name: "Robotics", sources: 19, source_rows: [], items_per_day: 0, kept_per_day: 0, tokens_month: null, prefilter: 0.3, status: "active" },
      "/api/sources": { sources: [], topics: [], reddit: { watched: 0, note: "" }, connections_need_you: 0, every_hours: 6, default_retention_days: 90 } });
    // on All topics' Sources (a choice); a topic's chip opens that topic's Sources page
    const { target, done } = await draw(Sources, at("watch/sources"));
    const chips = [...target.querySelectorAll("#src-chips .chip")] as HTMLElement[];
    expect(chips.map((c) => c.textContent)).toEqual(["All 130", "Robotics 19", "Local-first 6", "No topic 2"]);
    expect(chips.map((c) => c.getAttribute("href"))).toEqual(["#/watch/sources", "#/watch/topic/13/sources", "#/watch/topic/2/sources", "#/watch/sources?status=broad"]);
    expect(target.querySelector('#src-chips [aria-current="page"]')?.textContent).toBe("All 130");
    expect(target.querySelector("#topic-only")).toBeNull();
    expect(target.querySelector("#chip-projects")).toBeNull();
    expect(menu).not.toHaveBeenCalled();
    done();
  });
});
