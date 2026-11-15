import { mount, unmount, type Component } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Facts } from "../lib/app";
import { ui } from "../lib/shell.svelte";
import { answering, settle, stub } from "../pages/testing.svelte";
import Grade from "./Grade.svelte";
import GradeHead from "./GradeHead.svelte";
import { GRADED } from "./grades.svelte";
import { gradeKeys } from "./ticks.svelte";

const hosted = () => { ui.facts = { header: { host: { paused: false } } } as unknown as Facts; };
afterEach(() => { ui.facts = null; for (const k of Object.keys(GRADED)) delete GRADED[k]; document.body.replaceChildren(); });

function old() {
  const L = stub({ host: { topics: [] } });
  const toast = vi.fn();
  Object.assign(L, { toast });
  hosted();
  return { L, toast };
}
async function put(C: Component<never>, props: Record<string, unknown> = {}) {
  const target = document.createElement("div");
  document.body.append(target);
  const app = mount(C as Component<Record<string, unknown>>, { target, props });
  await settle();
  return { target, done: () => { void unmount(app); target.remove(); } };
}

describe("the grade control and its keys (▲ ▼ on cards and evidence, no ✕, no bulk grading)", () => {
  it("draws ▲ and ▼ only, each saying its verb, and nothing without the server", async () => {
    stub();
    const none = await put(Grade, { target: "observation", id: 2, what: "#2" });
    expect(none.target.querySelector(".grade")).toBeNull();
    none.done();
    old();
    const g = await put(Grade, { target: "observation", id: 2, what: "#2" });
    const bs = [...g.target.querySelectorAll<HTMLButtonElement>(".grade button")];
    expect(bs.map((b) => b.textContent)).toEqual(["▲", "▼"]);
    expect(bs.map((b) => b.title)).toEqual(["Useful (1)", "Not useful (2)"]);
    expect(bs.every((b) => b.dataset.verb === "feedback.add")).toBe(true);
    g.done();
  });

  it("says in the toast what a grade does", async () => {
    const { L, toast } = old();
    const g = await put(Grade, { target: "idea", id: 112, what: "card #112" });
    (g.target.querySelector("button.up") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/feedback", expect.objectContaining({ target: "idea", target_id: "112", value: "useful" }));
    expect((toast.mock.calls.at(-1) as [string])[0]).toBe("Graded card #112 useful. Cards like it rank higher from now.");
    const o = await put(Grade, { target: "observation", id: 438, what: "#438" });
    (o.target.querySelector("button.dn") as HTMLButtonElement).click();
    await settle();
    expect((toast.mock.calls.at(-1) as [string])[0]).toBe("Graded #438 not useful. Cards near it rank lower; enough downvotes on one source and Kranto asks whether to remove it.");
    g.done();
    o.done();
  });

  it("gives the Grade keys to the page head when no row is focused, and a–f click its why chips once graded", async () => {
    const { L } = old();
    answering({ "/api/feedback/vocabulary": { chips: { idea: [{ key: "novel", label: "novel", letter: "a" }, { key: "vague", label: "vague", letter: "b" }] } } });
    const pane = document.createElement("div");
    pane.id = "dscroll";
    document.body.append(pane);
    const app = mount(GradeHead, { target: pane, props: { target: "idea", id: 4, current: { value: "useful", reasons: [] }, what: "card #4" } });
    await settle();
    const keys: Record<string, () => void> = {};
    gradeKeys(document.body, keys, () => null);
    expect(Object.keys(keys).sort()).toEqual(["0", "1", "2", "a", "b", "c", "d", "e", "f"]);
    keys["1"]!();                                   // already useful: pressed again it would clear it
    await settle();
    expect(L.api).not.toHaveBeenCalled();
    keys["b"]!();
    await settle();
    expect(L.api).toHaveBeenLastCalledWith("/api/feedback", expect.objectContaining({ target: "idea", target_id: "4", value: "useful", reasons: ["vague"] }));
    keys["2"]!();
    await settle();
    expect(L.api).toHaveBeenLastCalledWith("/api/feedback", expect.objectContaining({ target: "idea", target_id: "4", value: "not_useful" }));
    keys["f"]!();                                   // no sixth chip
    await settle();
    expect(L.api).toHaveBeenCalledTimes(2);
    void unmount(app);
  });

  it("sets the Grade keys a page has not taken: the focused row's control; never a bulk request", async () => {
    const { L } = old();
    const g = await put(Grade, { target: "observation", id: 7, what: "#7" });
    const row = document.createElement("li");
    row.append(g.target);
    document.body.append(row);
    const keys: Record<string, () => void> = { "1": () => {} };
    gradeKeys(document.body, keys, () => row);
    expect(Object.keys(keys).sort()).toEqual(["0", "1", "2"]);
    keys["2"]!();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/feedback", expect.objectContaining({ target: "observation", target_id: "7", value: "not_useful" }));
    expect(L.api).not.toHaveBeenCalledWith("/api/feedback/batch", expect.anything());
    const none: Record<string, () => void> = {};
    gradeKeys(document.createElement("div"), none, () => null);
    expect(none).toEqual({});
    g.done();
  });
});
