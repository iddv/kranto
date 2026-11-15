import { flushSync, mount, unmount, type Component } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Facts } from "../lib/app";
import { ui } from "../lib/shell.svelte";
import { answering, settle, stub } from "../pages/testing.svelte";
import Grade from "./Grade.svelte";
import GradeHead from "./GradeHead.svelte";
import { GRADED, gkey, gradeEffect, paintGrade } from "./grades.svelte";

const VOCAB = { chips: { observation: [{ key: "off_topic", label: "off topic", letter: "a" }, { key: "duplicate", label: "duplicate", letter: "b" }] } };
const hosted = () => { ui.facts = { header: { host: { paused: false } } } as unknown as Facts; };
afterEach(() => { ui.facts = null; for (const k of Object.keys(GRADED)) delete GRADED[k]; document.body.replaceChildren(); });

/** the app, stubbed with what grading calls of it: api, toast, the popover */
function old(o: { fail?: boolean } = {}) {
  const L = stub({ host: { topics: [] } });
  L.api.mockImplementation(async () => { if (o.fail) throw new Error("the server is restarting"); return {}; });
  const toast = vi.fn(), closePop = vi.fn(), dialog = vi.fn();
  const popover = vi.fn((_a: HTMLElement, _l: string, kids: Node[], _o?: { why?: boolean }) => { const el = document.createElement("div"); el.className = "pop"; el.append(...kids); document.body.append(el); return el; });
  Object.assign(L, { toast, popover, closePop, dialog });
  hosted();
  return { L, toast, popover, closePop, dialog };
}
async function put(C: Component<never>, props: Record<string, unknown>) {
  const target = document.createElement("div");
  document.body.append(target);
  const app = mount(C as Component<Record<string, unknown>>, { target, props });
  await settle();
  return { target, done: () => { void unmount(app); target.remove(); } };
}
const press = async (el: Element | null) => { (el as HTMLButtonElement).click(); await settle(); };

describe("grading", () => {
  it("draws nothing without the server, which keeps the grades", async () => {
    stub();
    const { target, done } = await put(Grade, { target: "observation", id: 3, what: "#3" });
    expect(target.querySelector(".grade")).toBeNull();
    done();
  });

  it("presses a glyph in place: one post, the toast with Undo, a second press clears it", async () => {
    const { L, toast } = old();
    const { target, done } = await put(Grade, { target: "observation", id: 3, current: null, what: "#3", context: { position: 2 } });
    const g = target.querySelector(".grade")!;
    expect(g.getAttribute("role")).toBe("group");
    expect(g.getAttribute("aria-label")).toBe("Grade #3");
    expect(g.getAttribute("data-grade")).toBe("observation:3");
    expect([...g.querySelectorAll("button")].map((b) => [b.className, b.dataset.v, b.textContent, b.title])).toEqual([
      ["up", "useful", "▲", "Useful (1)"], ["dn", "not_useful", "▼", "Not useful (2)"]]);
    // what the key 1 does on the focused row (ticks.svelte.ts's gradeKeys): presses ▲
    await press(g.querySelector("button[data-v=useful]"));
    expect(L.api).toHaveBeenCalledWith("/api/feedback", expect.objectContaining({ target: "observation", target_id: "3", value: "useful", reasons: [], origin: "ui", context: expect.objectContaining({ position: 2 }) }));
    expect(g.querySelector("button[data-v=useful]")?.getAttribute("aria-pressed")).toBe("true");
    expect(g.getAttribute("data-value")).toBe("useful");
    expect(toast).toHaveBeenCalledWith(gradeEffect("observation", "useful", "#3"), expect.any(Function), undefined);
    expect(toast.mock.calls[0]![0]).toBe("Graded #3 useful. Cards near it rank higher.");
    // the same glyph again clears it (a skip row)
    await press(g.querySelector("button[data-v=useful]"));
    expect(L.api).toHaveBeenLastCalledWith("/api/feedback", expect.objectContaining({ value: "skip" }));
    expect(g.querySelector("button[aria-pressed=true]")).toBeNull();
    // another control of the same object follows, and so does this one
    const node = document.createElement("span");
    node.dataset.grade = "observation:3";
    node.append(Object.assign(document.createElement("button"), { type: "button" }));
    node.firstElementChild!.setAttribute("data-v", "not_useful");
    document.body.append(node);
    await press(g.querySelector("button[data-v=not_useful]"));
    expect(node.querySelector("button")?.getAttribute("aria-pressed")).toBe("true");
    GRADED[gkey("observation", 3)] = { value: "wrong", reasons: [] };
    flushSync();
    expect(g.querySelector("button[aria-pressed=true]")?.getAttribute("data-v")).toBe("not_useful"); // a wrong from before is a ▼
    paintGrade(gkey("observation", 3), null);
    expect(node.querySelector("button")?.getAttribute("aria-pressed")).toBe("false");
    // pressed in place: the page is never drawn again, so the list does not move
    expect(L.render).not.toHaveBeenCalled();
    expect(L.afkDrop).not.toHaveBeenCalled();
    expect(L.say).not.toHaveBeenCalled();
    done();
  });

  it("puts the glyph back and says why when the post fails", async () => {
    const { toast } = old({ fail: true });
    const { target, done } = await put(Grade, { target: "idea", id: 7, current: "not_useful", what: "card #7" });
    expect(target.querySelector("button[aria-pressed=true]")?.getAttribute("data-v")).toBe("not_useful");
    await press(target.querySelector("button[data-v=useful]"));
    expect(target.querySelector("button[aria-pressed=true]")?.getAttribute("data-v")).toBe("not_useful");
    expect(toast).toHaveBeenCalledWith("Not graded: the server is restarting", null, "red");
    done();
  });

  it("says what a grade does (taste orders the cards; the source rule counts the downvotes)", () => {
    expect(gradeEffect("idea", "useful", "card #4")).toBe("Graded card #4 useful. Cards like it rank higher from now.");
    expect(gradeEffect("idea", "not_useful", "card #4")).toBe("Graded card #4 not useful. Cards like it rank lower from now.");
    expect(gradeEffect("idea", "skip", "card #4")).toBe("Cleared the grade on card #4.");
    expect(gradeEffect("observation", "not_useful", "#438")).toBe("Graded #438 not useful. Cards near it rank lower; enough downvotes on one source and Kranto asks whether to remove it.");
  });

  it("draws a page head's bar; a grade opens the why chips, a–f click them, + note", async () => {
    const { L, toast, popover, closePop, dialog } = old();
    answering({ "/api/feedback/vocabulary": VOCAB });
    const { target, done } = await put(GradeHead, { target: "observation", id: 5, current: null, what: "this observation" });
    await settle();
    const gh = target.querySelector(".gh.line")!;
    expect(gh.getAttribute("data-why-target")).toBe("observation");
    expect(gh.getAttribute("data-why-id")).toBe("5");
    expect(gh.querySelector(".muted.small")?.textContent).toBe("Your grade");
    expect(gh.querySelector(".grade")?.getAttribute("aria-label")).toBe("Grade this observation");
    const why = gh.querySelector("button.whyb") as HTMLButtonElement;
    expect(why.textContent).toBe("why ▾");
    // why ▾ before a grade: grade it first
    await press(why);
    expect(toast).toHaveBeenLastCalledWith("Grade it first (▲ or ▼), then say why.", undefined, undefined);
    expect(popover).not.toHaveBeenCalled();
    // ▼ opens the chips by itself (the keys stay where they were)
    await press(gh.querySelector("button[data-v=not_useful]"));
    expect(popover).toHaveBeenCalledTimes(1);
    expect(popover.mock.calls[0]![3]).toEqual(expect.objectContaining({ why: true }));
    const pop = document.querySelector(".pop")!;
    expect(pop.querySelector(".pop-h")?.textContent).toBe("Why?");
    expect([...pop.querySelectorAll("button.chip")].map((b) => b.textContent)).toEqual(["a off topic", "b duplicate"]);
    expect(pop.querySelector(".chips")?.getAttribute("data-chips")).toBe("observation:5");
    // b, pressed in the popover: the second chip goes with the grade, quietly, then its own toast
    pop.dispatchEvent(new KeyboardEvent("keydown", { key: "b", bubbles: true }));
    await settle();
    expect(L.api).toHaveBeenLastCalledWith("/api/feedback", expect.objectContaining({ target: "observation", target_id: "5", value: "not_useful", reasons: ["duplicate"] }));
    expect(pop.querySelector("button[data-chip=duplicate]")?.getAttribute("aria-pressed")).toBe("true");
    expect(toast).toHaveBeenLastCalledWith('Kept "duplicate" with the grade.', undefined, undefined);
    // a second press takes it off
    await press(pop.querySelector("button[data-chip=duplicate]"));
    expect(L.api).toHaveBeenLastCalledWith("/api/feedback", expect.objectContaining({ reasons: [] }));
    // + note: the popover closes and the note's dialog opens
    await press([...pop.querySelectorAll("button")].find((b) => b.textContent === "+ note")!);
    expect(closePop).toHaveBeenCalledWith(false);
    expect(dialog).toHaveBeenCalledWith("A note on this observation", expect.any(Array), "Keep note", expect.any(Function));
    expect(L.render).not.toHaveBeenCalled(); // a chip is kept in place too
    done();
  });
});
