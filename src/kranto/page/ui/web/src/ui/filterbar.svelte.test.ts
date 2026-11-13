// The list's search box (FilterBar.svelte) hands the keys back: after / + text + Enter the list has
// them (j moves the cursor, it does not type "j" into the box), and esc leaves the box without
// closing what is open (QA B5).
import { flushSync, mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import FilterBar from "./FilterBar.svelte";

afterEach(() => {
  document.body.replaceChildren();
  history.replaceState(null, "", "#/");
});

function bar(q: Record<string, string> = {}) {
  const rows = document.createElement("div");
  rows.id = "rows";
  rows.tabIndex = -1;
  document.body.append(rows);
  const c = mount(FilterBar, { target: rows, props: { r: { path: ["watch", "evidence"], q, sel: null }, base: "watch/evidence", placeholder: "Search", selects: [] } });
  flushSync();
  const input = rows.querySelector("#search") as HTMLInputElement;
  input.focus();
  return { input, done: () => void unmount(c) };
}
const press = (el: HTMLElement, key: string) => el.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));

describe("the list's search box", () => {
  it("applies on Enter and gives the keys back to the list", () => {
    const { input, done } = bar();
    input.value = "robot";
    press(input, "Enter");
    expect(location.hash).toBe("#/watch/evidence?q=robot");
    expect(document.activeElement?.id).toBe("rows"); // the list's keys: j moves the cursor
    done();
  });

  it("leaves the box on esc, without the esc closing the sheet; an emptied box clears the search", () => {
    const shell = vi.fn();
    addEventListener("keydown", shell);
    const { input, done } = bar({ q: "robot" });
    input.value = "";
    press(input, "Escape");
    expect(document.activeElement?.id).toBe("rows");
    expect(shell).not.toHaveBeenCalled();
    expect(location.hash).toBe("#/watch/evidence");
    removeEventListener("keydown", shell);
    done();
  });

  // 17 (Codex 22, Gemini 16): Ideas filtered only on Enter, with no hint
  it("filters as you type, a moment after the typing stops", () => {
    vi.useFakeTimers();
    try {
      const { input, done } = bar();
      input.value = "rob";
      input.dispatchEvent(new Event("input", { bubbles: true }));
      vi.advanceTimersByTime(100);
      expect(location.hash).toBe("#/");
      vi.advanceTimersByTime(400);
      expect(location.hash).toBe("#/watch/evidence?q=rob");
      done();
    } finally {
      vi.useRealTimers();
    }
  });
});
