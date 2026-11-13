import { flushSync, mount, unmount } from "svelte";
import { describe, expect, it } from "vitest";
import App from "../App.svelte";
import { MARK, markLoaded } from "./mark";

describe("the bundle's mark", () => {
  it("marks the root it is given", () => {
    const el = document.createElement("html");
    markLoaded(el);
    expect(el.getAttribute(MARK)).toBe("svelte");
  });

  it("App marks the document and draws the frame's five regions, its two splitters and the doors' tab bar", () => {
    document.documentElement.removeAttribute(MARK);
    const target = document.createElement("div");
    const app = mount(App, { target });
    flushSync();
    expect(document.documentElement.getAttribute(MARK)).toBe("svelte");
    const frame = target.querySelector("#app") as HTMLElement;
    expect([...frame.children].map((e) => e.id)).toEqual(["top", "nav", "split-nav", "list", "split-detail", "detail", "bar", "tabbar"]);
    for (const id of ["rows", "dscroll", "term", "list-h", "scrim", "dlg", "pal"]) expect(target.querySelector("#" + id), id).not.toBeNull();
    expect(target.querySelector("#split-nav")?.getAttribute("role")).toBe("separator");
    unmount(app);
  });
});
