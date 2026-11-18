import { afterEach, describe, expect, it } from "vitest";
import type { Facts } from "../../lib/app";
import { ui } from "../../lib/shell.svelte";
import { answering, draw, settle, stub, where } from "../testing.svelte";
import { frameClassic, layoutOf, SHELL_API, type Arrangement } from "../../features/shell";
import AppearanceList from "./AppearanceList.svelte";
import AppearancePane from "./AppearancePane.svelte";
import ShellPane from "./ShellPane.svelte";

afterEach(() => { ui.facts = null; });
const hosted = () => { ui.facts = { header: { host: { paused: false } } } as unknown as Facts; };
const A = (layout: "new" | "classic"): Arrangement => ({ layout, pins: ["digest"], hidden: [], needs_cap: 3, new_cap: 4, pins_max: 6,
  cubs: [{ id: "digest", trust: "first-party", pinned: true, place: 0, hidden: false, needs_you: true, new: true }] });

describe("One layout (open-source wave 1, PR 1.4: Classic cut, D-2)", () => {
  it("has no Layout row on Appearance, and a file that says classic changes nothing", async () => {
    stub({ host: {} });
    hosted();
    answering({ [SHELL_API]: A("classic") });
    const { target, done } = await draw(AppearanceList, where("settings/appearance"));
    await settle();
    expect([...target.querySelectorAll(".r-title")].map((x) => x.textContent)).toEqual(["Theme", "Custom theme"]);
    expect(target.textContent).not.toContain("Classic");
    done();
  });

  it("offers no choice: an old link to the layout says there is one, and nothing is written", async () => {
    const L = stub({ host: {}, answer: A("new") });
    hosted();
    answering({ [SHELL_API]: A("classic") });
    const { target, done } = await draw(AppearancePane, where("settings/appearance", "elayout"));
    await settle();
    expect(target.querySelectorAll("[data-layout-choice]").length).toBe(0);
    expect(target.querySelector("#layout-one")?.textContent).toContain("One layout");
    expect(L.api).not.toHaveBeenCalled();
    done();
  });

  it("reads an older server's two switches as New too", () => {
    expect(layoutOf({ ...A("new"), layout: undefined, home: true, doors: false })).toBe("new");
    expect(layoutOf(A("classic"))).toBe("new");
    expect(frameClassic(true)).toBe(false);
  });

  it("has no Layout without the server (brb alone draws the navigator)", async () => {
    stub();
    const { target, done } = await draw(AppearanceList, where("settings/appearance"));
    await settle();
    expect([...target.querySelectorAll(".r-title")].map((x) => x.textContent)).toEqual(["Theme", "Custom theme"]);
    done();
  });
});

describe("Settings › System › The home", () => {
  it("writes a cap through the one writer", async () => {
    const L = stub({ host: {}, answer: A("new") });
    hosted();
    answering({ [SHELL_API]: A("new") });
    const { target, done } = await draw(ShellPane, where("settings/system", "ecaps"));
    await settle();
    const i = target.querySelector("#hf-new-cap") as HTMLInputElement;
    i.value = "2";
    i.dispatchEvent(new Event("change", { bubbles: true }));
    await settle();
    expect(L.api).toHaveBeenCalledWith(SHELL_API, { key: "shell.new_cap", value: 2 });
    done();
  });
});
