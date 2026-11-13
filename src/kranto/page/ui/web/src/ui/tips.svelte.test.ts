import { flushSync, mount, unmount } from "svelte";
import { afterEach, describe, expect, it } from "vitest";
import Tip from "./Tip.svelte";
import { closePop, menu, popNow } from "./popover";

function draw(props: { id: string | { text: string; docs?: string }; about?: string }) {
  const target = document.createElement("div");
  document.body.append(target);
  const app = mount(Tip, { target, props });
  flushSync();
  return { target, b: target.querySelector("button.tip") as HTMLButtonElement, done: () => { void unmount(app); target.remove(); } };
}
const box = () => document.querySelector(".pop.tipbox") as HTMLElement | null;
afterEach(() => closePop(false));

describe("the ? tip", () => {
  it("is a button that says what it is about, closed", () => {
    const { b, done } = draw({ id: "models.gate", about: "the gate" });
    expect(b.textContent).toBe("?");
    expect(b.getAttribute("type")).toBe("button");
    expect(b.dataset.tip).toBe("models.gate");
    expect(b.getAttribute("aria-label")).toBe("About the gate");
    expect(b.getAttribute("aria-expanded")).toBe("false");
    expect(b.hasAttribute("aria-describedby")).toBe(false);
    done();
  });

  it("opens on a click as a dialog with its words and its docs link, and a second click closes it", () => {
    const { b, done } = draw({ id: "models.gate" });
    b.click();
    flushSync();
    const el = box()!;
    expect(el.getAttribute("role")).toBe("dialog");
    expect(el.id).toBe("tip-models-gate");
    expect(el.getAttribute("aria-label")).toBe("About models.gate");
    expect(el.querySelector("p")?.textContent).toMatch(/^Items at or above this signal are kept/);
    const a = el.querySelector("a")!;
    expect([a.getAttribute("href"), a.target, a.rel, a.textContent]).toEqual(["help#models-gate", "_blank", "noopener", "More in the docs ↗"]);
    expect(b.getAttribute("aria-expanded")).toBe("true");
    expect(b.getAttribute("aria-describedby")).toBe("tip-models-gate");
    b.click();
    flushSync();
    expect(box()).toBeNull();
    expect(b.getAttribute("aria-expanded")).toBe("false");
    done();
  });

  it("opens on the focus as a tooltip, its own ? makes it a dialog, esc closes it", () => {
    const { b, done } = draw({ id: "signin", about: "signing in" });
    b.focus();
    flushSync();
    expect(box()?.getAttribute("role")).toBe("tooltip");
    expect(box()?.querySelector("a")?.getAttribute("href")).toBe("help#access"); // docs: a paragraph by name
    b.dispatchEvent(new KeyboardEvent("keydown", { key: "?", bubbles: true }));
    expect(box()?.getAttribute("role")).toBe("dialog");
    b.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    flushSync();
    expect(box()).toBeNull();
    done();
  });

  it("is the one popover: a menu opened after it closes it", () => {
    const { b, done } = draw({ id: "models.gate" });
    b.click();
    flushSync();
    expect(box()).not.toBeNull();
    menu(b, [{ label: "Pause", run: () => {} }]);
    expect(box()).toBeNull();
    expect(popNow()?.el.getAttribute("role")).toBe("menu");
    done();
  });

  it("takes words worked out from data, and draws nothing for an id it does not have", () => {
    const { b, done } = draw({ id: { text: "Kept for a week.", docs: "rollups" }, about: "retention" });
    expect(b.dataset.tip).toBe("rollups");
    b.click();
    flushSync();
    expect(box()?.querySelector("p")?.textContent).toBe("Kept for a week.");
    done();
    const none = draw({ id: "no.such.tip" });
    expect(none.target.querySelector("button")).toBeNull();
    none.done();
  });
});

describe("the menu", () => {
  it("draws its groups between rules, greys a verb that is not on with its why, and runs the others", () => {
    const anchor = document.createElement("button");
    document.body.append(anchor);
    const ran: string[] = [];
    const el = menu(anchor, [
      { label: "Open in new tab", group: "open", run: () => ran.push("open") },
      { label: "Publish", key: "p", id: "act-publish", run: () => ran.push("publish") },
      { label: "Retry", why: "Not while it runs", run: () => ran.push("retry") },
    ], "Row actions");
    expect(el.getAttribute("role")).toBe("menu");
    expect(el.getAttribute("aria-label")).toBe("Row actions");
    expect(el.querySelectorAll("hr").length).toBe(1);
    const bs = [...el.querySelectorAll<HTMLButtonElement>("button[role=menuitem]")];
    expect(bs.map((x) => x.textContent)).toEqual(["Open in new tab", "Publishp", "Retry (Not while it runs)"]);
    expect(bs[1]?.dataset.menu).toBe("act-publish");
    expect(bs[2]?.getAttribute("aria-disabled")).toBe("true");
    expect(document.activeElement).toBe(bs[0]);
    el.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown" }));
    expect(document.activeElement).toBe(bs[1]);
    bs[2]!.click();
    expect(ran).toEqual([]); // greyed: nothing runs, the menu stays
    expect(popNow()).not.toBeNull();
    bs[1]!.click();
    expect(ran).toEqual(["publish"]);
    expect(popNow()).toBeNull();
    anchor.remove();
  });
});
