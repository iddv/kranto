import { afterEach, describe, expect, it, vi } from "vitest";
import { KEYMAP } from "./keys";
import { doKey, onKeydown } from "./keyboard";
import { connect, ui } from "./shell.svelte";

/** the app, stubbed with what the keys call of it */
function stubbed(o: Record<string, unknown> = {}) {
  const L = {
    keyFirst: vi.fn(() => null), typing: vi.fn(() => false), rowsNow: vi.fn(() => [document.createElement("li")]), rowNow: vi.fn(() => null),
    pageKeys: vi.fn(() => ["b"]), runPageKey: vi.fn(), rowKey: vi.fn(() => true), closeKey: vi.fn(() => true), keySheet: vi.fn(),
    hasView: vi.fn((v: string) => v !== "nope"), topicAt: vi.fn((n: number) => (n === 1 ? { id: 7, name: "Clinics" } : null)), ...o,
  };
  connect(L as never);
  return L;
}
const press = (key: string, o: KeyboardEventInit = {}, target: EventTarget = document.body) => {
  const e = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...o });
  Object.defineProperty(e, "target", { value: target });
  onKeydown(e);
  return e;
};
afterEach(() => {
  connect(null);
  ui.chord = null;
  ui.palette = null;
  document.body.replaceChildren();
});

describe("a key's action, carried out", () => {
  it("has a case for every shell verb the map names, and hands the rows' verbs to the app", () => {
    const L = stubbed();
    for (const run of new Set(KEYMAP.filter((m) => m.run).map((m) => m.run as string))) {
      L.rowKey.mockClear();
      expect(doKey({ run } as never)).toBe(true);
    }
    expect(L.keySheet).toHaveBeenCalled(); // ?
    expect(L.closeKey).toHaveBeenCalledWith(false, expect.any(Function)); // esc
    expect(ui.palette).toEqual({ text: "" }); // ⌘K
    expect(doKey({ run: "nextSection" })).toBe(true);
    expect(L.rowKey).toHaveBeenLastCalledWith("nextSection");
  });

  it("goes to a page the app has and a topic by its number, runs a page's own verb, and finds the list's search", () => {
    const L = stubbed();
    expect(doKey({ go: "ideas" })).toBe(true);
    expect(location.hash).toBe("#/ideas");
    expect(doKey({ go: "nope" })).toBe(false);
    expect(doKey({ topic: 1 })).toBe(true);
    expect(location.hash).toBe("#/topics/7");
    expect(doKey({ topic: 2 })).toBe(false);
    doKey({ page: "b" });
    expect(L.runPageKey).toHaveBeenCalledWith("b");
    const rows = document.createElement("div");
    rows.id = "rows";
    const search = document.createElement("input");
    search.id = "search";
    rows.append(search);
    document.body.append(rows);
    expect(doKey({ run: "find" })).toBe(true);
    expect(document.activeElement?.id).toBe("search");
    rows.remove();
    doKey({ run: "find" }); // no search on this page: the palette
    expect(ui.palette).toEqual({ text: "" });
  });
});

describe("the listener", () => {
  it("leaves every key to the palette while it is open", () => {
    const L = stubbed();
    const pal = document.createElement("dialog");
    pal.id = "pal";
    pal.setAttribute("open", "");
    document.body.append(pal);
    press("j");
    expect(L.keyFirst).not.toHaveBeenCalled();
    expect(L.rowKey).not.toHaveBeenCalled();
  });

  it("lets a popover take its keys first", () => {
    const L = stubbed({ keyFirst: vi.fn(() => "prevent") });
    expect(press("Escape").defaultPrevented).toBe(true);
    expect(L.closeKey).not.toHaveBeenCalled();
  });

  it("does nothing while typing but ⌘K, in a field or a contenteditable", () => {
    const L = stubbed({ typing: vi.fn(() => true) });
    expect(press("j").defaultPrevented).toBe(false);
    expect(L.rowKey).not.toHaveBeenCalled();
    press("k", { metaKey: true });
    expect(ui.palette).toEqual({ text: "" });
    ui.palette = null;
    const M = stubbed();
    const div = document.createElement("div");
    div.contentEditable = "true";
    Object.defineProperty(div, "isContentEditable", { value: true });
    document.body.append(div);
    div.tabIndex = 0;
    div.focus();
    press("j", {}, div);
    expect(M.rowKey).not.toHaveBeenCalled();
  });

  it("runs enter only on a row focused with j or k while the focus is on the page, not on a link", () => {
    const L = stubbed({ rowNow: vi.fn(() => document.createElement("li")) });
    press("Enter");
    expect(L.rowKey).toHaveBeenCalledWith("primary");
    L.rowKey.mockClear();
    const a = document.createElement("a");
    a.href = "#/x";
    document.body.append(a);
    a.focus();
    press("Enter", {}, a);
    expect(L.rowKey).not.toHaveBeenCalled();
  });

  it("waits for a chord's second key for 1.5 s", () => {
    stubbed();
    expect(press("g").defaultPrevented).toBe(true);
    expect(ui.chord).toBe("g");
    press("i");
    expect(location.hash).toBe("#/ideas");
    expect(ui.chord).toBe(null);
  });
});
