// The claims test_topics_ui, test_click_levers, test_icon_nav and test_unified_ui read off the old
// source that the other tests here did not press yet: which pane a selection draws in, the
// toolbar's height under the group heads, the redraw that leaves the key field alone, a server
// form's notice, Connections' "needs you", j walking (STEPPING) and a row that selects a filter
// (data-go), the navigator as icons and Spend's pane with nothing selected.
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { Facts } from "./types";
import { register, shownPage } from "../pages.svelte";
import { navIcons, ui, type Layout, type LayoutState } from "../shell.svelte";
import Missing from "../../pages/Missing.svelte";
import Detail from "../../ui/Detail.svelte";
import { answering, draw, stub, where as at } from "../../pages/testing.svelte";
import SpendPane from "../../pages/settings/SpendPane.svelte";
import { WATCH } from "../../pages/settings/spend.svelte";
import { hostForm } from "./data";
import { refresh, render, tbHeight } from "./route";
import { rowKey, stepping } from "./rows";
import { frame, h, unframe } from "./testing";

// jsdom lays nothing out: a row is shown when it is in the page, and scrolling is a no-op
const real = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "offsetParent");
beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, "offsetParent", { configurable: true, get() { return this.isConnected ? this.parentElement : null; } });
  Element.prototype.scrollIntoView = () => {};
});
afterAll(() => {
  if (real) Object.defineProperty(HTMLElement.prototype, "offsetParent", real);
});
afterEach(() => {
  vi.restoreAllMocks();
  unframe();
});

// stand-ins for the pages, told apart by which one the pane shows: a topic's and Needs you's
register("topics", { pane: Missing as never });
register("topics/:id/evidence", { pane: Missing as never });
register("needs", { pane: Detail as never });

describe("the draw", () => {
  it("draws a Topics row in the list's own pane, a topic's proposals in Needs you's", async () => {
    await frame();
    for (const [hash, pane] of [["#/topics?sel=t1", Missing], ["#/topics/1/evidence?sel=p7", Detail]] as const) {
      history.replaceState(null, "", hash);
      render();
      expect(shownPage("pane"), hash).toBe(pane);
    }
  });

  it("keeps the group heads under a toolbar that wraps", async () => {
    await frame();
    const rows = document.getElementById("rows")!;
    rows.prepend(h("div", { class: "wl" }, h("div", { class: "tb" })));
    Object.defineProperty(rows.querySelector(".tb")!, "offsetHeight", { value: 58 });
    tbHeight();
    expect(rows.style.getPropertyValue("--tbh")).toBe("58px");
    rows.replaceChildren();
    tbHeight();
    expect(rows.style.getPropertyValue("--tbh")).toBe("0px"); // a list with no toolbar: at the top
  });

  it("leaves the page be while the key field holds something, and draws it again once it is empty", async () => {
    await frame({ hash: "#/settings/keys" });
    const key = Object.assign(document.createElement("input"), { id: "model-key", type: "password", value: "typed so far" });
    document.getElementById("rows")!.after(key);
    document.title = "as it was";
    await refresh();
    expect(document.title).toBe("as it was"); // not drawn again
    key.value = "";
    await refresh();
    expect(document.title).toBe("Not found · Kranto"); // drawn (no page is registered here)
  });
});

describe("the server's forms", () => {
  it("say the notice a form redirects with", async () => {
    const net = await frame();
    const r = new Response("<p>a page</p>", { status: 200 });
    Object.defineProperties(r, { redirected: { value: true }, url: { value: "http://kranto.test/?msg=Paused%20both%20halves." } });
    net.answer["/pause"] = r;
    await expect(hostForm("/pause", { reason: "x" })).resolves.toBe("Paused both halves.");
  });
});

describe("the navigator", () => {
  it("collapses to icons and back, kept in kranto.layout without the width it was dragged to", () => {
    let kept: LayoutState = { nav: 300, detail: 500 };
    const apply = vi.fn((l?: LayoutState) => {
      document.documentElement.classList.toggle("nav-icons", !!(l && l.icons));
      return { nav: 56, det: null, icons: !!(l && l.icons), wide: true, mid: false };
    });
    window.krantoLayout = { read: () => ({ ...kept }), save: (x: LayoutState) => { kept = x; }, apply,
      NAV: { min: 168, max: 400, icons: 56, def: 224 }, DET: { min: 360 }, LIST: 320, SPLIT: 6 } as Layout;
    try {
      navIcons(true);
      expect(kept).toEqual({ detail: 500, icons: true });
      expect(apply).toHaveBeenLastCalledWith({ detail: 500, icons: true });
      expect(ui.icons).toBe(true); // the frame drawn again
      navIcons(false);
      expect(kept).toEqual({ detail: 500 });
      expect(ui.icons).toBe(false);
    } finally {
      delete window.krantoLayout;
      document.documentElement.classList.remove("nav-icons");
    }
  });
});

describe("j and k", () => {
  const rows = (...lis: HTMLElement[]) => document.getElementById("rows")!.append(h("div", { class: "wl" }, h("ul", {}, ...lis)));
  const row = (attrs: Record<string, string>, title: string) => h("li", { class: "row lr", ...attrs }, h("span", { class: "r-title" }, title));

  it("step while the pane follows, so a form walked past leaves the cursor in the list", async () => {
    await frame({ hash: "#/needs" });
    render();
    rows(row({ "data-sel": "p7" }, "Proposed sources"));
    const seen: boolean[] = [];
    const replace = history.replaceState.bind(history);
    vi.spyOn(history, "replaceState").mockImplementation((...a: Parameters<History["replaceState"]>) => {
      seen.push(stepping());
      replace(...a);
    });
    rowKey("next");
    expect(location.hash).toBe("#/needs?sel=p7");
    expect(seen[0]).toBe(true); // the pane was drawn while stepping
    expect(stepping()).toBe(false);
  });

  it("walk the points of a map: a row whose selection is a filter of its list", async () => {
    await frame({ hash: "#/library/map" });
    render();
    rows(row({ "data-go": "#/library/map?p=11" }, "A point"), row({ "data-go": "#/library/map?p=12" }, "Another"));
    rowKey("next");
    expect(location.hash).toBe("#/library/map?p=11");
    document.querySelector("#rows li")!.setAttribute("data-cur", ""); // the list marks its current point (MapList)
    render();
    rowKey("next");
    expect(location.hash).toBe("#/library/map?p=12");
  });
});

describe("Settings › Spend", () => {
  it("opens with nothing selected on Totals: watching's month; every cap is a row of the list", async () => {
    stub({ host: { spend_this_month_usd: 2, budget_usd: 10 } });
    ui.facts = { header: { host: { paused: false } } } as unknown as Facts;
    answering({ [WATCH]: { spent_usd: 2, monthly_usd: 10, alarm: false, alarm_fraction: 0.8, config: "/h/kranto.yaml", deep_dive: { daily_usd: 0.05, enabled: true } } });
    const { target, done } = await draw(SpendPane, at("settings/spend"));
    expect(target.querySelector(".dt")?.textContent).toBe("Totals");
    expect([...target.querySelectorAll(".sec h3")].map((a) => a.textContent)).toEqual(["This month"]);
    expect(target.querySelector(".lede")?.textContent).toBe("Every cap is in the list, under Caps: select one to change it. Empty is no cap.");
    expect(target.querySelector("input")).toBeNull();
    done();
  });
});
