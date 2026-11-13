// The small Markdown (ui/md.ts) as a draft's preview uses it (13, Codex 19, Gemini 10): a
// draft's "*Why:*" showed its stars and "[the case for patient agents](/blog/…)" its brackets.
import { describe, expect, it } from "vitest";
import { blocks, inline } from "./md";

describe("a table (What Kranto sends' fields)", () => {
  it("is one row a line, its cells joined, without its pipes or its rule", () => {
    expect(blocks("| Field | Meaning |\n|---|---|\n| version | Kranto's version |")).toEqual([
      { k: "ul", items: [[{ t: "text", s: "Field · Meaning" }], [{ t: "text", s: "version · Kranto's version" }]] }]);
  });
});

describe("a draft's inline Markdown", () => {
  it("draws *italics* and **bold**, and leaves a lone star alone", () => {
    expect(inline("*Why:* it is cheap, **now**", true)).toEqual([
      { t: "em", s: "Why:" }, { t: "text", s: " it is cheap, " }, { t: "strong", s: "now" }]);
    expect(inline("2 * 3 * 4")).toEqual([{ t: "text", s: "2 * 3 * 4" }]);
  });

  it("links what a page may open, and shows the words of any other link without its brackets", () => {
    expect(inline("see [the paper](https://ex.com/a)", true)).toEqual([
      { t: "text", s: "see " }, { t: "link", s: "the paper", href: "https://ex.com/a" }]);
    expect(inline("read [the case for patient agents](/blog/the-case)", true)).toEqual([
      { t: "text", s: "read " }, { t: "text", s: "the case for patient agents" }]);
  });
});
