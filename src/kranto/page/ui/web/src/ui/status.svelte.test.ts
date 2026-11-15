import { afterEach, describe, expect, it } from "vitest";
import { ui } from "../lib/shell.svelte";
import { answering, draw, stub, where } from "../pages/testing.svelte";
import PageAbout from "../pages/settings/PageAbout.svelte";
import KeySheet from "../shell/KeySheet.svelte";
import Glyph from "./Glyph.svelte";
import SetRow from "./SetRow.svelte";
import { SET_LEGEND, SET_ST, stOfWord } from "./settings";

afterEach(() => { ui.area = ""; });

describe("Settings' status words (UP #10)", () => {
  it("draws one glyph per word and one word per glyph, and the legend says each", () => {
    const all = Object.values(SET_ST);
    expect(new Set(all.map((s) => s[0])).size).toBe(all.length);
    expect(new Set(all.map((s) => s[2])).size).toBe(all.length);
    expect(SET_LEGEND.map(([s]) => s[2]).sort()).toEqual(all.map((s) => s[2]).sort());
    // the pages' older words for a state draw that state's glyph
    expect(stOfWord("Failed")?.slice(0, 2)).toEqual(["x", "red"]);
    expect(stOfWord("Connected")?.slice(0, 2)).toEqual(["check", "green"]);
    expect(stOfWord("AGENTS.md")).toBeNull();
  });

  it("draws a status word with its glyph whatever the page asked, and its word beside it on Settings", async () => {
    stub();
    const a = await draw(Glyph as never, where("needs"), undefined, { name: "open", colour: "amber", word: "Needs you" });
    const g = a.target.querySelector(".gl") as HTMLElement;
    expect(g.className).toBe("gl c-amber");
    expect(g.querySelector("svg path")).not.toBeNull(); // the warning triangle, not the ring
    expect(g.querySelector(".gl-w")).toBeNull(); // elsewhere the word is the label only
    a.done();
    ui.area = "settings";
    const b = await draw(Glyph as never, where("settings/system"), undefined, { name: "dot", colour: "grey", word: "Off" });
    expect(b.target.querySelector(".gl")?.className).toBe("gl c-grey");
    expect(b.target.querySelector(".gl-w")?.textContent).toBe("Off");
    b.done();
  });

  it("a setting's row says its state's word first, in its colour", async () => {
    stub();
    ui.area = "settings";
    const { target, done } = await draw(SetRow as never, where("settings/watching"), undefined, { key: "read:every", word: "Read every", summary: "3 hours", state: SET_ST.dflt });
    expect(target.querySelector(".c-main")?.textContent).toBe("Read everyDefault3 hours");
    expect(target.querySelector(".c-main .stw")?.className).toBe("stw c-grey"); // beside the title, on a phone too
    done();
  });

  it("the legend is on every Settings page's pane and in the ? sheet", async () => {
    stub();
    answering({});
    ui.area = "settings";
    const p = await draw(PageAbout, where("settings/system"));
    expect([...p.target.querySelectorAll(".sec h3")].map((h) => h.textContent)).toContain("What the marks mean");
    expect([...p.target.querySelectorAll("#marks-legend dd")].length).toBe(SET_LEGEND.length);
    p.done();
    const k = await draw(KeySheet as never, where("needs"), undefined, { has: [], hasView: () => true, close: () => {} });
    expect(k.target.querySelector("#sheet-marks h3")?.textContent).toBe("Marks");
    expect(k.target.querySelector("#sheet-marks dd")?.textContent).toBe("Ok: working, or turned on and fine");
    k.done();
  });
});
