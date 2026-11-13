import { afterEach, describe, expect, it, vi } from "vitest";
import AccessList from "../pages/settings/AccessList.svelte";
import Detail from "../ui/Detail.svelte";
import { dropPage, lazy, onPageLoaded, pageFor, register, showPage, shownPage, type Where } from "./pages.svelte";
import { ui } from "./shell.svelte";
import "../pages";

const w = (q: Record<string, string> = {}): Where => ({
  r: { path: ["settings", "access"], q, sel: null }, node: "settings/access", list: ["settings", "access"],
  object: null, obj: null, id: null, sel: false, stage: false, missing: false,
});
afterEach(() => {
  dropPage("list");
  ui.facts = null;
});

describe("the page seam", () => {
  it("finds a moved page by its route's node, and nothing for the others", () => {
    expect(pageFor("settings/privacy", "list")).toMatchObject({ load: expect.any(Function) });
    expect(pageFor("needs", "list")).toMatchObject({ load: expect.any(Function) }); // 
    expect(pageFor("today", "list")).toBeNull(); // no page: #/today redirects to Needs you
    expect(pageFor("builds", "list")).toBeNull(); // builds left: their addresses land on the home
    expect(pageFor(null, "pane")).toBeNull();
    register("test/only-a-pane", { pane: Detail as never });
    expect(pageFor("test/only-a-pane", "list")).toBeNull();
  });

  it("finds a page registered under a route's node for that node with its parameters filled in", () => {
    const one = pageFor("topics/5/evidence", "list");
    expect(one).toMatchObject({ load: expect.any(Function) });
    expect(pageFor("topics/7", "list")).toBe(one); // one list for a topic's pages
    expect(pageFor("topics/7", "pane")).toBe(pageFor("topics/5/evidence", "pane"));
    // a node registered itself is never a parameter's: Add topic is not a topic called "new"
    expect(pageFor("topics/new", "list")).not.toBe(one);
    expect(pageFor("topics/5/elsewhere", "list")).toBeNull();
    expect(pageFor("topics/5/evidence/more", "list")).toBeNull();
  });

  it("mounts once, keeps the same nodes on a redraw, and gives the pane back", () => {
    const box = document.createElement("div");
    document.body.append(box);
    box.append(document.createElement("p")); // what was drawn before
    showPage("list", box, AccessList, w());
    const first = box.firstElementChild;
    expect(first?.classList.contains("wl")).toBe(true);
    expect(box.querySelector("p.empty")?.textContent).toContain("kranto token list");
    showPage("list", box, AccessList, w({ q: "x" }));
    expect(box.firstElementChild).toBe(first); // updated in place: a field keeps what was typed
    expect(shownPage("list")).toBe(AccessList);
    dropPage("list");
    expect(box.childNodes.length).toBe(0);
    expect(shownPage("list")).toBeNull();
    box.remove();
  });

  it("loads a page the first time its route opens, says Loading… meanwhile, and draws again when it arrives", async () => {
    const arrived = vi.fn();
    onPageLoaded(arrived);
    let release: (m: { default: typeof AccessList }) => void = () => {};
    const part = lazy(() => new Promise((ok) => { release = ok; }));
    const box = document.createElement("div");
    showPage("list", box, part, w());
    showPage("list", box, part, w()); // one load, however many draws
    expect(box.textContent).toBe("Loading…");
    release({ default: AccessList });
    await new Promise((r) => setTimeout(r, 0));
    expect(arrived).toHaveBeenCalledTimes(1);
    showPage("list", box, part, w());
    expect(box.firstElementChild?.classList.contains("wl")).toBe(true);
  });
});
