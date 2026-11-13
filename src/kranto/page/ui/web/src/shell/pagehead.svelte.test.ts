// The one head every page starts with: the crumb, the glyph, the title and a
// trust tag, at most one primary with ⋯ and ⚙, one facts line, the lede, the line, one flash, the
// subnav as underlined words. Watch's (WT, the owner's words of 2026-10-23): the subnav is Topics,
// then the scoped topic's name with its Sources, Evidence and Map; the crumb on one of its pages
// says "Watch › Robotics › Sources", the topic a switcher that keeps the page (another topic, or
// All topics). Classic: no crumb (the tree says it) but Watch's switcher.
import { flushSync, mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DoorFacts, Facts } from "../lib/app";
import { declareHead, type HeadDecl } from "../lib/app/heads";
import { connect, ui } from "../lib/shell.svelte";
import PageHead from "./PageHead.svelte";

const TOPICS = [{ id: "13", name: "Robotics" }, { id: "2", name: "AI developer tooling" }];
function watch(o: Partial<DoorFacts> & { page?: "" | "sources" | "evidence" | "map" | null; all?: boolean; topic?: string | null } = {}): DoorFacts {
  const all = o.all || false, topic = all ? null : o.topic === undefined ? "13" : o.topic, page = o.page === undefined ? "sources" : o.page;
  const at = (k: string) => (topic ? `watch/topic/${topic}/${k}` : `watch/${k}`);
  return {
    id: "watch", word: "Watch", classic: o.classic,
    items: [{ to: "watch", w: "Topics", n: null, tone: "", on: page === null }, ...(["sources", "evidence", "map"] as const).map((k) => ({ to: at(k), w: k[0]!.toUpperCase() + k.slice(1), n: k === "sources" ? 2 : null, tone: "wait", on: page === k, sub: true }))],
    scope: { topic, name: topic ? TOPICS.find((t) => t.id === topic)!.name : "All topics", all, page, to: topic ? `watch/topic/${topic}` : null, on: !!topic && page === "", topics: TOPICS },
  };
}
const IDEAS: DoorFacts = { id: "ideas", word: "Ideas", items: [{ to: "ideas", w: "Cards", n: 1, tone: "wait", on: true }, { to: "ideas/review", w: "Review", n: null, tone: "", on: false }] };
let undeclare: (() => void) | null = null;
function draw(place: DoorFacts | null, head: HeadDecl | null = null) {
  ui.facts = { place } as unknown as Facts;
  undeclare = head ? declareHead(head) : null;
  const target = document.createElement("div");
  const app = mount(PageHead, { target });
  flushSync();
  return { target, done: () => unmount(app) };
}
afterEach(() => {
  undeclare?.();
  ui.facts = null;
  connect(null);
});
const words = (t: HTMLElement, sel: string) => [...t.querySelectorAll(sel)].map((x) => x.textContent);

describe("the page's head", () => {
  it("is Home › the door, its glyph and name, the facts, one primary, ⋯ and ⚙, then the underlined words", () => {
    const more = vi.fn();
    const { target, done } = draw(IDEAS, { title: "Cards", facts: "12 ideas · 1 waiting", primary: { label: "Write a post", href: "#/post", id: "head-new" }, more: [{ label: "Something else", run: more }] });
    const h = target.querySelector("#page-head")!;
    expect(target.querySelectorAll("#page-head")).toHaveLength(1);
    expect(h.querySelector(".crumb")?.textContent).toBe("Home›Ideas");
    // a page that is one of its door's words is titled with the door's word: the subnav says which
    expect(h.querySelector("h1")?.textContent).toBe("◆Ideas");
    expect(h.querySelector("#page-facts")?.textContent).toBe("12 ideas · 1 waiting");
    expect(words(h as HTMLElement, ".verbs > *")).toEqual(["Write a post", "⋯", "⚙"]);
    expect(h.querySelectorAll(".verbs .primary")).toHaveLength(1);
    expect(h.querySelector("#page-gear")?.getAttribute("href")).toBe("#/settings/watching");
    expect(words(h as HTMLElement, ".doornav a")).toEqual(["Cards1", "Review"]);
    expect(h.querySelector(".doornav a[aria-current]")?.textContent).toBe("Cards1");
    done();
  });

  it("keeps a page's own title when it is not one of the door's words; the lede is its ?, the flash one quiet line", () => {
    const { target, done } = draw(IDEAS, { title: "Add source", lede: "Pick a kind.", flash: { kind: "amber", text: "Drafts only.", link: { href: "#/settings", w: "Settings ›" } } });
    expect(target.querySelector("h1 .pt")?.textContent).toBe("Add source");
    // the lede's sentence is help, behind the title's ?; a notice is a k-note, not a box
    expect(target.querySelector("#page-lede")).toBeNull();
    expect(target.querySelector(".trow button.tip")?.getAttribute("aria-label")).toBe("About Add source");
    expect(target.querySelectorAll(".flash")).toHaveLength(0);
    expect(target.querySelector("#page-flash")?.className).toBe("k-note amber");
    expect(target.querySelector("#page-flash")?.textContent).toBe("Drafts only. Settings ›");
    done();
  });

  it("runs the primary's verb with its button; Stop beside it", () => {
    const run = vi.fn(), stop = vi.fn();
    const { target, done } = draw(null, { title: "Digest", crumb: [{ to: "cubs", w: "Cubs" }, { to: "cub/digest", w: "Digest" }], trust: { w: "built-in", cls: "first-party" }, primary: { label: "Propose now", run }, stop: { label: "Stop", run: stop }, gear: "settings/digest" });
    expect(target.querySelector(".crumb")?.textContent).toBe("Home›Cubs›Digest");
    expect(target.querySelector(".htag")?.textContent).toBe("built-in");
    (target.querySelector(".verbs .primary") as HTMLButtonElement).click();
    (target.querySelector(".verbs .stop") as HTMLButtonElement).click();
    expect(run).toHaveBeenCalledTimes(1);
    expect(stop).toHaveBeenCalledTimes(1);
    expect(target.querySelector("#page-gear")?.getAttribute("href")).toBe("#/settings/digest");
    done();
  });

  it("draws nothing where no door is open and no page declares a head (the home)", () => {
    const { target, done } = draw(null);
    expect(target.querySelector("#page-head")).toBeNull();
    done();
  });

  it("in Classic has no crumb, the same title, verbs and words", () => {
    const { target, done } = draw({ ...IDEAS, classic: true }, { title: "Cards", primary: { label: "Write a post", href: "#/post" } });
    expect(target.querySelector(".crumb")).toBeNull();
    expect(target.querySelector("h1")?.textContent).toBe("◆Ideas");
    expect(words(target, ".doornav a")).toEqual(["Cards1", "Review"]);
    done();
  });

  it("goes when its page goes: the declaration is the page's", () => {
    const { target, done } = draw(IDEAS, { title: "Cards", facts: "3 ideas" });
    expect(target.querySelector("#page-facts")).not.toBeNull();
    undeclare!();
    flushSync();
    expect(target.querySelector("#page-facts")).toBeNull();
    expect(target.querySelector("h1")?.textContent).toBe("◆Ideas"); // the door's still
    done();
  });
});

describe("Watch's head", () => {
  it("is Topics, then the topic's name and its own Sources, Evidence and Map", () => {
    const { target, done } = draw(watch());
    const nav = target.querySelector(".doornav")!;
    expect([...nav.querySelectorAll(":scope > a")].map((a) => [a.textContent, a.getAttribute("href"), a.getAttribute("aria-current")]))
      .toEqual([["Topics", "#/watch", null], ["Sources2", "#/watch/topic/13/sources", "page"], ["Evidence", "#/watch/topic/13/evidence", null], ["Map", "#/watch/topic/13/map", null]]);
    // the scope sits before its pages: "Topics · Robotics › Sources Evidence Map"
    const scope = nav.querySelector("#watch-scope")!;
    expect(scope.textContent).toBe("Robotics›");
    expect(scope.querySelector("a")?.getAttribute("href")).toBe("#/watch/topic/13");
    expect(scope.nextElementSibling?.textContent).toBe("Sources2");
    // the crumb: Watch › Robotics ▾ › Sources
    expect(target.querySelector(".crumb")?.textContent).toBe("Home›Watch›Robotics ▾›Sources");
    done();
  });

  it("switches the topic and keeps the page, or goes to All topics' page", () => {
    const menu = vi.fn();
    connect({ menu } as never);
    const { target, done } = draw(watch({ page: "map" }));
    (target.querySelector("#topic-switch") as HTMLButtonElement).click();
    const items = (menu.mock.calls[0] as unknown as [HTMLElement, { label: string; run: () => void }[]])[1];
    expect(items.map((x) => x.label)).toEqual(["Robotics ✓", "AI developer tooling", "All topics"]);
    items[1]!.run();
    expect(location.hash).toBe("#/watch/topic/2/map");
    items[2]!.run();
    expect(location.hash).toBe("#/watch/map");
    done();
  });

  it("titles All topics' pages so, the scope a word, not a link", () => {
    const { target, done } = draw(watch({ all: true, page: "evidence" }));
    expect(target.querySelector(".crumb")?.textContent).toBe("Home›Watch›All topics ▾›Evidence");
    expect(target.querySelector("#watch-scope a")).toBeNull();
    expect(target.querySelector("#watch-scope")?.textContent).toBe("All topics›");
    expect([...target.querySelectorAll(".doornav > a")].map((a) => a.getAttribute("href"))).toEqual(["#/watch", "#/watch/sources", "#/watch/evidence", "#/watch/map"]);
    done();
  });

  it("on Watch's Topics names no topic in the crumb; the subnav is still the last topic's; the ingest's line is the door's", () => {
    const { target, done } = draw(watch({ page: null }), { title: "Topics" });
    expect(target.querySelector(".crumb")?.textContent).toBe("Home›Watch");
    expect(target.querySelector("#topic-switch")).toBeNull();
    expect(target.querySelector(".doornav a[aria-current]")?.textContent).toBe("Topics");
    expect(target.querySelector("#watch-scope")?.textContent).toBe("Robotics›");
    expect(target.querySelector("h1")?.textContent).toBe("◉Watch");
    done();
  });

  it("in the classic frame keeps the crumb's switcher on Watch's topic pages, and no crumb on Topics", () => {
    const a = draw(watch({ classic: true }));
    expect(a.target.querySelector(".crumb")?.textContent).toBe("Home›Watch›Robotics ▾›Sources");
    expect(a.target.querySelector(".doornav")).not.toBeNull();
    a.done();
    const b = draw(watch({ classic: true, page: null }));
    expect(b.target.querySelector(".crumb")).toBeNull(); // Watch's Topics: the tree says where you are
    b.done();
  });
});
