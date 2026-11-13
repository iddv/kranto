import { describe, expect, it } from "vitest";
import { action, hint, keyName, KEYMAP, queueAction, type KeyState } from "./keys";

const press = (key: string, o: Partial<KeyboardEvent> = {}) =>
  keyName({ key, altKey: false, metaKey: false, ctrlKey: false, shiftKey: false, ...o });
const state = (o: Partial<KeyState> = {}): KeyState => ({
  typing: false, chord: null, rows: true, focused: true, pageKeys: new Set(), ...o,
});

describe("the key map", () => {
  it("names a keydown as the map does", () => {
    expect(press("k", { ctrlKey: true })).toBe("⌘K");
    expect(press("K", { metaKey: true })).toBe("⌘K");
    expect(press("a", { metaKey: true })).toBe("⌘a");
    expect(press("Enter", { metaKey: true })).toBe("⌘enter");
    expect(press("x", { metaKey: true })).toBeNull();
    expect(press("J", { shiftKey: true })).toBe("⇧j");
    expect(press("Escape")).toBe("esc");
    expect(press("ArrowLeft")).toBeNull();         // the queue's pairs went
    expect(press("Tab")).toBe("tab");
    expect(press("Tab", { shiftKey: true })).toBeNull();
    expect(press("j", { altKey: true })).toBeNull();
    expect(press("?")).toBe("?");
  });

  it("does nothing while typing but ⌘K", () => {
    expect(action("⌘K", state({ typing: true }))).toEqual({ run: "palette" });
    for (const k of ["j", "g", "?", "esc", "1"]) expect(action(k, state({ typing: true }))).toBeNull();
  });

  it("goes with g then a letter or a topic's number", () => {
    expect(action("g", state())).toEqual({ chord: "g" });
    expect(action("t", state({ chord: "g" }))).toEqual({ go: "needs" });
    expect(action("b", state({ chord: "g" }))).toBeNull(); // builds left with the factory
    expect(action("p", state({ chord: "g" }))).toBeNull();
    expect(action("l", state({ chord: "g" }))).toEqual({ go: "library" });
    expect(action("3", state({ chord: "g" }))).toEqual({ topic: 3 });
    expect(action("q", state({ chord: "g" }))).toBeNull();
  });

  it("lets the page's verb win, and moves rows only where there are rows", () => {
    expect(action("x", state({ pageKeys: new Set(["x"]) }))).toEqual({ page: "x" });
    expect(action("j", state())).toEqual({ run: "next" });
    expect(action("j", state({ rows: false }))).toBeNull();
    expect(action("enter", state({ focused: false }))).toBeNull(); // enter on a link is the link's
    expect(action("enter", state())).toEqual({ run: "primary" });
    expect(action("b", state())).toBeNull(); // a page verb on a page without it
    expect(action("?", state({ rows: false }))).toEqual({ run: "sheet" });
  });

  it("o opens in full, tab puts the cursor in the pane only from a focused row (D5)", () => {
    expect(action("o", state())).toEqual({ run: "open" });
    expect(action("tab", state())).toEqual({ run: "pane" });
    expect(action("tab", state({ focused: false }))).toBeNull(); // the browser's tab
  });

  it("puts each route's keys in its tooltip", () => {
    expect(hint("needs")).toBe("g t");
    expect(hint("builds")).toBeNull();
    expect(hint("nowhere")).toBeNull();
    expect(KEYMAP.filter((m) => m.keys === "g t")).toHaveLength(1);
  });

  it("answers the review queue's keys", () => {
    expect(queueAction("1", {})).toEqual({ do: "grade", value: "useful" });
    expect(queueAction("←", {})).toBeNull();            // the queue has no pairs
    expect(queueAction("b", { chipTarget: {}, chips: 3 })).toEqual({ do: "chip", at: 1 });
    expect(queueAction("f", { chipTarget: {}, chips: 3 })).toBeNull();
    expect(queueAction("j", { done: true })).toBeNull();
    expect(queueAction("k", { done: true })).toEqual({ do: "prev" });
  });
});

describe("the keys sheet's words", () => {
  it("name today's places, never one retired with the doors (QA B11: Needs you (Today), Evidence (the Library))", () => {
    const retired = /\bToday\b|\bLibrary\b|\bDesk\b|Home and feed|Settings › Publishing › Maintenance|\b[Bb]uilds?\b|Projects|Publish/;
    for (const k of KEYMAP) expect([k.keys, k.does]).not.toEqual([k.keys, expect.stringMatching(retired)]);
  });
});
