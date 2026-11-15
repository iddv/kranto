import { describe, expect, it } from "vitest";
import { palGroups, palKey, palScore, type PalItem } from "./palette";

const item = (g: string, title: string, q: string, ...rest: string[]): PalItem => ({ g, title, score: palScore(q, title, ...rest) });

describe("the palette's ranking", () => {
  it("scores a start, a word, a part, and every word somewhere", () => {
    expect(palScore("plot", "Plotkeeper")).toBe(4);
    expect(palScore("keep", "Plot keeper")).toBe(3);
    expect(palScore("eep", "Plotkeeper")).toBe(2);
    expect(palScore("garden plot", "Plotkeeper", "a community garden")).toBe(1);
    expect(palScore("nothing", "Plotkeeper")).toBe(0);
    expect(palScore("  ", "Plotkeeper")).toBe(0);
    expect(palScore("Plotkeeper", "plotkeeper")).toBe(5);
  });

  // B (Codex 21): "post" and enter opened Settings › Posting's tags, not Post
  it("puts the page whose name is the query first: post opens Post", () => {
    const q = "post";
    const groups = palGroups([item("Settings", "Posting tags", q), item("Go to", "Post", q), item("Go to", "Post › Blog", q)], q);
    expect(groups[0]?.[0]).toBe("Go to");
    expect(groups[0]?.[1][0]?.title).toBe("Post");
  });

  it("leads with the group of the best match, so plot finds the evidence first", () => {
    const q = "plot";
    const items = [item("Ideas", "community gardens juggle plot assignments", q), item("Evidence", "Plotkeeper", q),
                   item("Commands", "Go to Plots", q)];
    const groups = palGroups(items, q);
    // a word of each starts with plot (3), the evidence's title does (4); a tie keeps the order
    expect(groups.map((g) => g[0])).toEqual(["Evidence", "Ideas", "Commands"]);
  });

  it("keeps the groups' order on a tie and cuts each group short", () => {
    const many = Array.from({ length: 10 }, (_, i) => item("Ideas", `idea ${i}`, "idea"));
    const ev = Array.from({ length: 10 }, (_, i) => item("Evidence", `idea ${i}`, "idea"));
    const groups = palGroups([...ev, ...many], "idea");
    expect(groups.map((g) => g[0])).toEqual(["Ideas", "Evidence"]);
    expect(groups[0]?.[1]).toHaveLength(6);
    expect(groups[1]?.[1]).toHaveLength(8);
    const cmds = Array.from({ length: 50 }, (_, i) => ({ g: "Commands", title: `c${i}`, score: 1 }));
    expect(palGroups(cmds, "")[0]?.[1]).toHaveLength(40);
    expect(palKey({ g: "Ideas", title: "x" })).toBe("Ideas\u0000x");
  });
});
