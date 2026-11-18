import { afterEach, describe, expect, it, vi } from "vitest";
import type { Where } from "../../lib/pages.svelte";
import { QUEUE_KEYS } from "../../lib/keys";
import { ui } from "../../lib/shell.svelte";
import { GRADED } from "../../ui/grades.svelte";
import { answering, draw, settle, stub, where } from "../testing.svelte";
import ReviewList from "./ReviewList.svelte";
import ReviewPane from "./ReviewPane.svelte";
import { gradable, KINDWORD, REVIEW_API, reviewMinutes, type QueueItem } from "./review";
import { Q } from "./review.svelte";

const ITEMS: QueueItem[] = [
  // an older server may still send a build: the page drops it (a build is never graded)
  { target: "build", id: "i1a1b2c3d", slot: "build", topic: "Local-first" },
  { target: "idea", id: 116, slot: "card", title: "A memory daemon", line: "Repo-resident context.", facts: ["2 cited", "0 ask for it", "1 source"], topic: "Local-first" },
  { target: "idea", id: 117, slot: "card", title: "A credential broker", line: "Agents ask it for keys.", facts: ["3 cited", "1 asks for it", "2 sources"], topic: "AI tooling" },
  { target: "idea", id: 118, slot: "card", title: "An egress proxy", line: "", facts: ["1 cited", "0 ask for it", "1 source"], topic: "AI tooling" },
];
const PATH = "/api/review/queue";
const VOCAB = { chips: { idea: [{ key: "novel", label: "novel", letter: "a" }, { key: "vague", label: "vague", letter: "b" }],
  observation: [{ key: "off_topic", label: "off topic", letter: "a" }] } };

afterEach(() => { ui.facts = null; Q.path = null; location.hash = ""; for (const k of Object.keys(GRADED)) delete GRADED[k]; document.body.replaceChildren(); });

/** the old module, stubbed with what Review calls of it; the queue answers `queue` */
function old(o: { queue?: unknown; fail?: string; host?: boolean } = {}) {
  const L = stub({ host: o.host === false ? null : { topics: [] } });
  const keys: Record<string, () => void> = {};
  L.api.mockImplementation(async (path: string) => {
    if (path.startsWith("/api/review/queue")) { if (o.fail) throw new Error(o.fail); return structuredClone(o.queue ?? { items: ITEMS, week: "2026-W42" }); }
    return {};
  });
  const fns = { toast: vi.fn(), afkDropPrefix: vi.fn(), dialog: vi.fn(), pageKey: vi.fn((k: string, f: () => void) => { keys[k] = f; }) };
  Object.assign(L, fns);
  answering({ "/api/feedback/vocabulary": VOCAB });
  return { L, keys, ...fns };
}
const W: Where = where("review");
const rows = (t: HTMLElement): HTMLElement[] => [...t.querySelectorAll("li.row")] as HTMLElement[];
async function both() {
  const list = await draw(ReviewList, W);
  const pane = await draw(ReviewPane, W);
  return { list: list.target, pane: pane.target, done: () => { pane.done(); list.done(); } };
}
const key = async (keys: Record<string, () => void>, k: string) => { keys[k]!(); await settle(); };

describe("Review (this week's cards only: D-2)", () => {
  it("asks for this week's cards, never the builds; about 20 s an item", () => {
    expect(REVIEW_API).toBe(PATH);
    expect(gradable(ITEMS).map((x) => x.target)).toEqual(["idea", "idea", "idea"]);
    expect([1, 3, 4, 14].map(reviewMinutes)).toEqual([1, 1, 1, 5]);
    expect(KINDWORD.idea).toBe("card");
  });

  it("says it needs the server, which builds the queue, and reads nothing", async () => {
    const { L } = old({ host: false });
    const { target, done } = await draw(ReviewList, W);
    expect(target.querySelector(".wl")?.getAttribute("data-title")).toBe("Review");
    expect(target.querySelector(".lh .muted")?.textContent).toBe("this week's queue");
    expect(target.querySelector(".box strong")?.textContent).toBe("The review queue needs Kranto's server, which is not answering. ");
    expect(L.api).not.toHaveBeenCalled();
    done();
    old({ host: false });
    const p = await draw(ReviewPane, W);
    expect(p.target.querySelector(".pane-empty")?.textContent).toBe("Reading the queue…");
    p.done();
  });

  it("is the queue as a list, the progress bar its toolbar, the current item the selected row and the pane", async () => {
    const { L, keys } = old();
    const { list, pane, done } = await both();
    expect(L.api).toHaveBeenCalledWith(PATH);
    expect(list.querySelector(".tb .progress .mono")?.textContent).toBe("1 of 3");
    expect(list.querySelector(".tb .meter")?.getAttribute("aria-label")).toBe("0 of 3 done");
    expect(list.querySelector(".tb .progress > span:last-child")?.textContent).toBe("about 1 minute left");
    expect(list.querySelector("section.grp.queue .ghd .n")?.textContent).toBe("3");
    expect(list.querySelector("section.grp.queue .ghd .muted")?.textContent).toBe("2026-W42");
    const r = rows(list);
    expect(r.map((x) => x.querySelector(".r-title")?.textContent)).toEqual(["A memory daemon", "A credential broker", "An egress proxy"]);
    expect(r.map((x) => x.querySelector(".kindtag")?.textContent)).toEqual(["card", "card", "card"]);
    expect(r.map((x) => x.querySelector(".c-aside")?.textContent)).toEqual(["Local-first", "AI tooling", "AI tooling"]);
    expect(r[0]!.hasAttribute("data-cur")).toBe(true);
    expect(r[0]!.querySelector(".gl")?.getAttribute("aria-label")).toBe("Not graded yet");
    expect([...r[0]!.querySelectorAll('.c-end .grade[data-grade="idea:116"] button')].map((b) => b.textContent)).toEqual(["▲", "▼"]);
    expect(list.querySelector('[data-grade^="build:"]')).toBeNull();
    // the pane: the card, its own page (enter), its facts, the grade bar and Skip
    const card = pane.querySelector(".pane .pane-in[data-title=Review] section.qcard")!;
    expect(card.getAttribute("aria-label")).toBe("Item 1");
    expect(card.querySelector(".q-what")?.textContent).toBe(" card · 1 of 3 · Local-first");
    expect(card.querySelector("h2.dt a")?.getAttribute("href")).toBe("#/ideas/116");   // the card itself
    expect(card.querySelector("p.mono:not(.q-what)")?.textContent).toBe("2 cited · 0 ask for it · 1 source");
    expect(pane.querySelector("#s-so-far p")?.textContent).toBe("So far: 0 grades, 0 skips, 0 chips.");
    // every key of the queue is the page's own; 3 is not one of them
    expect(Object.keys(keys).sort()).toEqual(QUEUE_KEYS.map((m) => m.keys).sort());
    expect(Object.keys(keys)).not.toContain("3");
    done();
  });

  it("walks the queue by its keys: a grade posts and moves on, a chip goes on the item just graded, skip, enter, done", async () => {
    const { L, keys, toast, afkDropPrefix, dialog } = old();
    const { list, pane, done } = await both();
    // 1: graded useful, kept with the review's slot, and on to the next
    await key(keys, "1");
    expect(L.api).toHaveBeenCalledWith("/api/feedback", expect.objectContaining({ target: "idea", target_id: "116", value: "useful", origin: "review", context: expect.objectContaining({ slot: "card", position: 1 }) }));
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("Graded card #116 useful."), expect.any(Function), undefined);
    expect(L.render).toHaveBeenCalled();
    expect(afkDropPrefix).toHaveBeenCalledWith("/api/review/queue");
    expect(Q.at).toBe(1);
    expect(rows(list)[0]!.querySelector(".given")?.textContent).toBe("useful");
    expect(list.querySelector(".progress .mono")?.textContent).toBe("2 of 3");
    // the item just graded, with its chips and their letters; the current one, not graded, has none
    expect(pane.querySelector(".qlast .muted")?.textContent).toBe('Just graded card "A memory daemon" useful.');
    const chips = pane.querySelector('.qlast .chips.why[data-chips="idea:116"]')!;
    expect([...chips.querySelectorAll("button.chip")].map((b) => [b.textContent, (b as HTMLButtonElement).disabled])).toEqual([["anovel", false], ["bvague", false]]);
    expect(pane.querySelector("section.qcard .q-what")?.textContent).toBe(" card · 2 of 3 · AI tooling");
    expect(pane.querySelectorAll(".chips.why").length).toBe(1);
    // b: the chip on the card just graded
    await key(keys, "b");
    expect(L.api).toHaveBeenLastCalledWith("/api/feedback", expect.objectContaining({ target: "idea", target_id: "116", value: "useful", reasons: ["vague"], origin: "review" }));
    // n: a note on it
    await key(keys, "n");
    expect(dialog).toHaveBeenCalledWith("A note on card", expect.any(Array), "Keep note", expect.any(Function));
    // 0: skipped, back next week
    await key(keys, "0");
    expect(L.api).toHaveBeenLastCalledWith("/api/feedback", expect.objectContaining({ target: "idea", target_id: "117", value: "skip", origin: "review" }));
    expect(toast).toHaveBeenLastCalledWith("Skipped card #117: it comes back next week.");
    // enter: the card itself
    expect(pane.querySelector("section.qcard .q-what")?.textContent).toBe(" card · 3 of 3 · AI tooling");
    await key(keys, "enter");
    expect(location.hash).toBe("#/ideas/118");
    await key(keys, "2");
    // done: the tally and the ways on
    expect(Q.at).toBe(3);
    expect(list.querySelector(".progress > span:last-child")?.textContent).toBe("done");
    const fin = pane.querySelector("section.qcard")!;
    expect(fin.querySelector("h2.dt")?.textContent).toBe("Done.");
    expect(fin.querySelector(".lede")?.textContent).toBe("So far: 2 grades, 1 skip, 1 chip.");
    expect([...fin.querySelectorAll(".acts > *")].map((a) => a.textContent)).toEqual(["Back home", "Read the queue again"]);
    expect(fin.querySelector(".acts a")?.getAttribute("href")).toBe("#/home");
    (pane.querySelector("section.qcard .acts button") as HTMLButtonElement).click();
    await settle();
    expect(L.api.mock.calls.filter((c) => c[0] === PATH).length).toBe(2);
    expect(Q.at).toBe(0);
    done();
  });

  it("grades from a row too (a phone shows the list), and a pressed row is the current item", async () => {
    const { L } = old();
    const { list, done } = await both();
    (rows(list)[2]!.querySelector("button[data-v=not_useful]") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/feedback", expect.objectContaining({ target: "idea", target_id: "118", value: "not_useful", context: expect.objectContaining({ slot: "card", position: 3 }) }));
    expect(rows(list)[2]!.querySelector(".given")?.textContent).toBe("not useful");
    done();
  });

  it("says what went wrong, and an empty week with the way back", async () => {
    old({ fail: "the server is restarting" });
    const e = await draw(ReviewList, W);
    expect(e.target.querySelector("p.empty")?.textContent).toBe("Could not read the queue: the server is restarting");
    e.done();
    Q.path = null;
    const { keys } = old({ queue: { items: [], week: "2026-W42" } });
    const { list, pane, done } = await both();
    expect(list.querySelector(".mark-empty p")?.textContent).toBe("Nothing waits for a grade this week. The queue fills with the cards Kranto writes this week; it is rebuilt each week.");
    expect(list.querySelector(".mark-empty a.btn")?.getAttribute("href")).toBe("#/");
    expect(pane.querySelector(".pane-empty")?.textContent).toBe("The queue is empty this week.");
    expect(Object.keys(keys).length).toBe(QUEUE_KEYS.length);
    done();
  });
});
