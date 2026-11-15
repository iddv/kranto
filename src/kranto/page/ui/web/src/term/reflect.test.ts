// Reflection: an assistant's verb marks the row it touched, says who, and goes after 8 s;
// the first read only learns where the lines are; Activity's run says which assistant.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { runMeta } from "../lib/activity";
import { byWords, mark, markWords, MARK_MS, reflect, rowMark, selsFor, touched } from "./reflect.svelte";
import type { VerbLine } from "./reflect.svelte";

const line = (seq: number, over: Partial<VerbLine> = {}): VerbLine => ({
  seq, verb: "topic.add", title: "Add topic", subject: { kind: "topic", id: 14 }, page: "#/watch/topic/14/sources",
  mark: "topic:14", by: "console:claude", by_words: "by Claude Code", prepared: null, run: "r1", at: "", ...over,
});
const answer = (body: unknown) => async () => new Response(JSON.stringify(body), { status: 200 });

describe("reflection", () => {
  beforeEach(() => {
    touched.rows = {};
    touched.seq = -1;
  });

  it("finds a row by its data-sel", () => {
    expect(selsFor("topic:14")).toEqual(["t14", "topic:14", "14"]);
    expect(selsFor("")).toEqual([]);
  });

  it("says what happened and who did it", () => {
    expect(markWords(line(1))).toBe("✦ Add topic, by Claude Code");
    expect(markWords(line(1, { prepared: "p1", title: "Publish", by_words: "by Codex (outside)" })))
      .toBe("✦ Publish: prepared by Codex (outside), waits for you");
  });

  it("marks only what came after the page opened, for a while", async () => {
    expect(await reflect(answer({ seq: 3, recent: [line(3)] }))).toBe(false);
    expect(rowMark("t14")).toBeNull();
    expect(await reflect(answer({ seq: 4, recent: [line(4)] }))).toBe(true);
    expect(rowMark("t14")).toBe("✦ Add topic, by Claude Code");
    expect(rowMark("t14", Date.now() + MARK_MS + 10)).toBeNull();
    mark([], Date.now() + MARK_MS + 10);
    expect(touched.rows).toEqual({});
  });

  it("does nothing when the server has no such read", async () => {
    expect(await reflect(async () => new Response("", { status: 404 }))).toBe(false);
    expect(await reflect(vi.fn().mockRejectedValue(new Error("down")))).toBe(false);
  });

  it("says which assistant ran a run", () => {
    expect(byWords("console:claude")).toBe("by Claude Code");
    expect(byWords("mcp:codex")).toBe("by Codex (outside)");
    expect(byWords("mcp")).toBe("by your own assistant");
    expect(byWords("ui")).toBeNull();
    const r = { state: "ok", title: "Add topic", words: null, trigger: { origin: "press", by: "console:claude" } };
    expect(runMeta(r as never)).toContain("by Claude Code");
  });
});
