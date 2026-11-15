// The rows and the keys (rows.ts): j/k and the selection, groups, sections, enter, x, esc's order,
// the popover's keys, the row's menu (., a right-click, a long press) and the frame's clicks.
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { popNow, popover } from "../../ui/popover";
import { termUi } from "../../term/state.svelte";
import { render, routeNow } from "./route";
import { closeKey, initFrame, keyFirst, rowKey, rowNow, rowsNow, spy, stepping } from "./rows";
import { card, frame, h, tick, unframe } from "./testing";

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
  unframe();
});

/** a list of two groups: card rows (by their link) and Needs you rows (by their sel key) */
function rows(): HTMLElement[] {
  const box = document.getElementById("rows")!;
  box.append(h("div", { class: "wl" },
    h("ul", { class: "g1" },
      h("li", { class: "row lr", id: "r1" }, h("a", { class: "r-title", href: "#/ideas/1" }, "Card 1"), h("span", { class: "r-act" }, h("button", { class: "btn primary", id: "p1" }, "Write a post"))),
      h("li", { class: "row lr new", id: "r2" }, h("a", { class: "r-title", href: "#/ideas/2" }, "Card 2"))),
    h("ul", { class: "g2" },
      h("li", { class: "row lr", id: "r3", "data-sel": "p7" }, h("span", { class: "r-title" }, "Proposed sources"), h("span", { class: "r-act" }, h("button", { class: "btn", id: "b3", title: "Watch them" }, "Watch"))),
      h("li", { class: "row lr", id: "r4", "data-sel": "mx" }, h("span", { class: "r-title" }, "A message")))));
  return [...box.querySelectorAll<HTMLElement>("li.row")];
}
const IDEAS = { "/api/ideas?embedding=ref": { ideas: [card(1), card(2)] } };

describe("j and k", () => {
  it("move over the rows and the pane follows, replacing the history entry; walking leaves the cursor in the list", async () => {
    await frame({ hash: "#/needs" });
    render();
    rows();
    const seen: boolean[] = [];
    const replace = vi.spyOn(history, "replaceState");
    addEventListener("hashchange", () => seen.push(stepping()));
    expect(rowKey("next")).toBe(true);
    expect(rowNow()?.id).toBe("r1");
    expect(location.hash).toBe("#/needs?sel=i1");
    expect(replace).toHaveBeenCalled();
    rowKey("next");
    rowKey("next");
    expect(location.hash).toBe("#/needs?sel=p7"); // a row that is no object's own route: its sel key
    expect(document.querySelector("#rows .sel")?.id).toBe("r3");
    rowKey("prev");
    expect(rowNow()?.id).toBe("r2");
    expect(stepping()).toBe(false);
    expect(document.querySelectorAll("#rows .focus").length).toBe(1);
  });

  it("jump a group with ⇧j and ⇧k", async () => {
    await frame({ hash: "#/needs" });
    render();
    rows();
    rowKey("nextGroup");
    expect(rowNow()?.id).toBe("r1");
    rowKey("nextGroup");
    expect(rowNow()?.id).toBe("r3");
    rowKey("prevGroup");
    expect(rowNow()?.id).toBe("r1");
  });

  it("enter runs the focused row's primary; x ticks nothing (bulk grading went with)", async () => {
    await frame({ hash: "#/needs" });
    render();
    rows();
    const press = vi.fn();
    document.getElementById("p1")!.addEventListener("click", press);
    rowKey("next");
    expect(rowKey("primary")).toBe(true);
    expect(press).toHaveBeenCalled();
    expect(rowKey("tick")).toBe(false);
    expect(document.querySelector("#rows input.tick")).toBeNull();
  });

  it("o and tab put the cursor in the pane: at home as the object's own route, away from it as sel=", async () => {
    await frame({ hash: "#/ideas" });
    render();
    rows();
    rowKey("next");
    expect(location.hash).toBe("#/ideas/1"); // at home: the object's own route
    render();
    expect(rowKey("open")).toBe(true);
    expect(document.activeElement?.id).toBe("dscroll");
    history.replaceState(null, "", "#/needs");
    render();
    rowKey("next");
    expect(location.hash).toBe("#/needs?sel=i1");
    expect(rowKey("open")).toBe(true); // away from home: the cursor goes to the pane
    expect(document.activeElement?.id).toBe("dscroll");
    history.replaceState(null, "", "#/needs?sel=p7");
    render();
    expect(rowKey("pane")).toBe(true);
    expect(document.activeElement?.id).toBe("dscroll");
  });
});

describe("esc", () => {
  it("closes the terminal's panel, then the drawer, then the pane, then the focus", async () => {
    await frame({ hash: "#/ideas/1" });
    render();
    termUi.subject = { kind: "idea", id: "1" } as never;
    const nav = vi.fn();
    expect(closeKey(true, nav)).toBe(true);
    expect(termUi.subject).toBe(null);
    expect(closeKey(true, nav)).toBe(true);
    expect(nav).toHaveBeenCalled();
    expect(closeKey(false, nav)).toBe(true);
    expect(location.hash).toBe("#/ideas"); // the pane: back to the list
    history.replaceState(null, "", "#/needs");
    render();
    rows();
    rowKey("next");
    history.replaceState(null, "", "#/needs");
    render();
    expect(routeNow()?.object).toBe(null);
    expect(closeKey(false, nav)).toBe(true);
    expect(document.querySelectorAll("#rows .focus").length).toBe(0);
    expect(closeKey(false, nav)).toBe(false);
  });

  it("closes the popover first; a–f press a why chip while one is open", async () => {
    await frame();
    const b = document.createElement("button");
    document.body.append(b);
    const chip = document.createElement("button");
    chip.className = "chip";
    const press = vi.fn();
    chip.addEventListener("click", press);
    popover(b, "Why?", [chip], { why: true });
    expect(keyFirst("a")).toBe("prevent");
    expect(press).toHaveBeenCalled();
    expect(keyFirst("f")).toBe("stop"); // no sixth chip: the page's own f is not run either
    expect(keyFirst("esc")).toBe("prevent");
    expect(popNow()).toBe(null);
    expect(keyFirst("esc")).toBe(null);
  });
});

describe("the row's menu", () => {
  it("opens on . with Open in new tab first, then the card's verbs", async () => {
    await frame({ hash: "#/needs", reads: IDEAS });
    render();
    rows();
    rowKey("next");
    await tick();
    expect(rowKey("menu")).toBe(true);
    const items = [...popNow()!.el.querySelectorAll("button[role=menuitem]")].map((x) => x.textContent);
    expect(items[0]).toBe("Open in new tab");
    expect(items).toContain("Open in Claude Codec");
    expect(popNow()!.el.getAttribute("aria-label")).toBe("Row actions");
  });

  it("takes a row's own buttons where its object has no verbs of its own, and keeps the browser's menu on a bare link", async () => {
    await frame({ hash: "#/needs" });
    render();
    rows();
    initFrame();
    const r3 = document.getElementById("r3")!;
    const e = new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 10, clientY: 20 });
    r3.dispatchEvent(e);
    expect(e.defaultPrevented).toBe(true);
    expect([...popNow()!.el.querySelectorAll("button[role=menuitem]")].map((x) => [x.textContent, x.getAttribute("title")])).toEqual([["Watch", "Watch them"]]);
    const r4 = document.getElementById("r4")!;
    const e4 = new MouseEvent("contextmenu", { bubbles: true, cancelable: true });
    r4.dispatchEvent(e4);
    expect(e4.defaultPrevented).toBe(false);
  });

  it("opens on a long press, and the action's own click does not select the row", async () => {
    vi.useFakeTimers();
    try {
      await frame({ hash: "#/needs" });
      render();
      rows();
      initFrame();
      const r3 = document.getElementById("r3")!;
      r3.dispatchEvent(Object.assign(new MouseEvent("pointerdown", { bubbles: true, clientX: 5, clientY: 5 }), { pointerType: "touch" }));
      vi.advanceTimersByTime(499);
      expect(popNow()).toBe(null);
      vi.advanceTimersByTime(1);
      expect(popNow()?.el.getAttribute("role")).toBe("menu");
      const click = new MouseEvent("click", { bubbles: true, cancelable: true });
      r3.querySelector(".r-title")!.dispatchEvent(click);
      expect(click.defaultPrevented).toBe(true);
      expect(location.hash).toBe("#/needs");
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("the frame's clicks", () => {
  it("selects a row clicked outside its buttons, and opens a list's link in the pane", async () => {
    await frame({ hash: "#/needs" });
    render();
    rows();
    initFrame();
    (document.querySelector("#r3 .r-title") as HTMLElement).click();
    expect(location.hash).toBe("#/needs?sel=p7");
    const a = document.querySelector("#r2 a") as HTMLAnchorElement;
    const e = new MouseEvent("click", { bubbles: true, cancelable: true });
    a.dispatchEvent(e);
    expect(e.defaultPrevented).toBe(true);
    expect(location.hash).toBe("#/needs?sel=i2");
  });

  it("marks the outline's section the pane is scrolled to", async () => {
    await frame({ hash: "#/needs" });
    render();
    const d = document.getElementById("dscroll")!;
    d.replaceChildren(h("nav", { class: "toc" }, h("a", { href: "#s-a" }, "A"), h("a", { href: "#s-b" }, "B")), h("section", { class: "sec", id: "s-a" }), h("section", { class: "sec", id: "s-b" }));
    const top = (id: string, y: number) => vi.spyOn(document.getElementById(id)!, "getBoundingClientRect").mockReturnValue({ top: y } as DOMRect);
    top("s-a", -50);
    top("s-b", 5);
    spy();
    expect([...d.querySelectorAll(".toc a")].map((a) => a.getAttribute("aria-current"))).toEqual([null, "true"]);
  });
});

it("finds the rows that are shown, not the empty line", async () => {
  await frame({ hash: "#/needs" });
  render();
  rows();
  document.getElementById("rows")!.append(h("p", { class: "row empty", "data-row": true }, "Nothing here."));
  expect(rowsNow().map((x) => x.id)).toEqual(["r1", "r2", "r3", "r4"]);
});
