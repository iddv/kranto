// The draw's part in grading, Review and the decisions (route.ts, rows.ts, chrome.ts): the Grade
// keys (on cards and evidence only,), the queue's current row, its count in the navigator, c on a
// card's sheet and an object's pane away from its home.
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { REVIEW_API } from "../../pages/review/review";
import { termUi } from "../../term/state.svelte";
import { GRADED } from "../../ui/grades.svelte";
import { parse } from "../router";
import { navTree } from "./chrome";
import { pageKeys, render, routeNow, runPageKey } from "./route";
import { markSel, rowKey, rowNow } from "./rows";
import { card, frame, h, tick, unframe } from "./testing";
import "../../pages";

// jsdom lays nothing out: a row is shown when it is in the page
const real = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "offsetParent");
beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, "offsetParent", { configurable: true, get() { return this.isConnected ? this.parentElement : null; } });
  Element.prototype.scrollIntoView = () => {};
});
afterAll(() => {
  if (real) Object.defineProperty(HTMLElement.prototype, "offsetParent", real);
});
afterEach(() => {
  for (const k of Object.keys(GRADED)) delete GRADED[k];
  termUi.enabled = false;
  termUi.subject = null;
  unframe();
});
/** the draw, once the route's pages (each loaded the first time its route opens) have arrived:
 * up to 10 s, as a full parallel run can take seconds to load a page's module */
async function drawn(): Promise<void> {
  for (const end = Date.now() + 10_000; Date.now() < end; ) {
    render();
    if (![...document.querySelectorAll("#rows, #dscroll")].some((b) => b.textContent === "Loading…")) break;
    await new Promise((r) => setTimeout(r, 20));
  }
  await tick();
  render();
  await tick();
}
const IDEAS = "/api/ideas?embedding=ref";
const QUEUE = { items: [{ target: "idea", id: 1, slot: "card" }, { target: "observation", id: 2, slot: "control" }, { target: "idea", id: 3, slot: "card" }], week: "2026-W42" };

describe("grading in the draw", () => {
  it("gives every page that draws a grade the Grade keys: 1 grades the focused card", async () => {
    const net = await frame({ hash: "#/ideas", reads: { [IDEAS]: { ideas: [card(5, "waiting", { title: "Five" })] } } });
    net.answer["/api/feedback"] = {};
    await drawn();
    expect(pageKeys()).toEqual(expect.arrayContaining(["1", "2", "0"]));
    expect(pageKeys()).not.toContain("3");
    while (rowNow()?.querySelector(".grade") == null) expect(rowKey("next")).toBe(true);
    expect(rowNow()!.querySelector(".grade")?.getAttribute("data-grade")).toBe("idea:5");
    runPageKey("1");
    await tick();
    const post = net.calls.find(([url]) => url === "/api/feedback")!;
    expect(JSON.parse(post[1]!.body as string)).toMatchObject({ target: "idea", target_id: "5", value: "useful" });
    expect(rowNow()!.querySelector("button[data-v=useful]")?.getAttribute("aria-pressed")).toBe("true");
    // a page with no grade on it keeps 1 2 0 for nothing
    history.replaceState(null, "", "#/nope/route");
    render();
    expect(pageKeys()).not.toContain("1");
  });
});

describe("Review in the draw", () => {
  it("marks the queue's current item the selected row", async () => {
    await frame({ hash: "#/needs" });
    render();
    document.getElementById("rows")!.append(h("ul", {}, h("li", { class: "row", id: "q1" }), h("li", { class: "row", id: "q2", "data-cur": true }), h("li", { class: "row", id: "q3" })));
    markSel(routeNow()!);
    expect([...document.querySelectorAll("#rows .sel")].map((x) => x.id)).toEqual(["q2"]);
    expect(rowNow()?.id).toBe("q2");
  });

  it("counts the queue in the navigator and puts it on Needs you with Start, read from the same path", async () => {
    await frame({ hash: "#/needs", reads: { [REVIEW_API]: QUEUE } });
    navTree(parse());
    await tick();
    expect(navTree(parse()).rows.find((x) => x.to === "ideas/review" && !x.head)).toMatchObject({ w: "Review", n: 3 });
    await drawn();
    const row = document.querySelector('#rows li.row[data-sel="r"]')!;
    expect(row.querySelector(".r-title")?.textContent).toBe("3 waiting for a grade, a few seconds each");
    const start = row.querySelector(".r-act a.btn")!;   // a plain verb: the one thing has the primary
    expect([start.textContent, start.getAttribute("href")]).toEqual(["Start", "#/review"]);
  });
});

describe("the decisions in the draw", () => {
  it("c on a card's sheet opens Claude Code on the card", async () => {
    await frame({ hash: "#/ideas/1", reads: { [IDEAS]: { ideas: [card(1)] } } });
    await drawn();
    expect(pageKeys()).toContain("c");
    termUi.enabled = true;
    runPageKey("c");
    expect(termUi.subject).toMatchObject({ kind: "idea", id: "1" });
    expect(termUi.title).toBe("Card 1");
  });

  it("draws an observation or a card selected away from its home with its home's pane", async () => {
    await frame({ hash: "#/needs?sel=o9", reads: { [IDEAS]: { ideas: [card(1)] } } });
    await drawn();
    expect(document.querySelector("#dscroll .pane-in")?.getAttribute("data-title")).toBe("Observation");
    history.replaceState(null, "", "#/needs?sel=i1");
    await drawn();
    expect(document.querySelector("#dscroll .pane-in")?.getAttribute("data-title")).toBe("Card 1");
  });
});
