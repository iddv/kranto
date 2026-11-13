import { describe, expect, it } from "vitest";
import { capUsd, dur, memoryWords, nextRead, readingWords, usd, when } from "./format";

describe("a read in progress and memory, in words (MEM)", () => {
  const p = { sources: 8, source_index: 1, source: "HN search: local-first", items: null, item: 0, kept: 0 };
  it("says the source, its items and what was kept", () => {
    expect(readingWords(p)).toBe("source 1 of 8, HN search: local-first · fetching · 0 kept so far");
    expect(readingWords({ ...p, items: 0 })).toBe("source 1 of 8, HN search: local-first · nothing new · 0 kept so far");
    expect(readingWords({ ...p, source: null, items: 1, kept: 1 })).toBe("source 1 of 8 · 0 of 1 item · 1 kept so far");
  });
  it("says memory against its caps, or that there is none", () => {
    expect(memoryWords({ used_mb: 512, high_mb: 3072, max_mb: 4096 })).toBe("512 MB of 3.0 GB (the high mark; 4.0 GB at most)");
    expect(memoryWords({ used_mb: 2048, high_mb: null, max_mb: 4096 })).toBe("2.0 GB of 4.0 GB at most");
    expect(memoryWords({ used_mb: null, high_mb: null, max_mb: null })).toBe("unknown · no cap set");
  });
});

describe("the shell's small words", () => {
  it("says when the server reads next: now, a time today, or the day and time past today", () => {
    const now = new Date(2026, 9, 16, 10, 0);
    expect(nextRead(new Date(2026, 9, 16, 10, 0, 30).toISOString(), now)).toBe("now");
    expect(nextRead(new Date(2026, 9, 16, 18, 5).toISOString(), now)).toBe("18:05");
    expect(nextRead(new Date(2026, 9, 17, 6, 0).toISOString(), now)).toBe("Sat 06:00");
  });

  it("writes money with two places and a cap as no cap when there is none", () => {
    expect(usd(1)).toBe("$1.00");
    expect(usd(null)).toBe("$0.00");
    expect(capUsd(40)).toBe("$40.00");
    expect(capUsd(null)).toBe("no cap");
  });

  it("writes a time one way: now, minutes or hours under a day, else the date and time", () => {
    const now = new Date(2026, 9, 17, 20, 0).getTime();
    expect(when(now / 1000 - 20, { now })).toBe("now");
    expect(when(now / 1000 - 7 * 60, { now })).toBe("7 min");
    expect(when(now / 1000 - 7 * 60, { now, inSentence: true })).toBe("7 min ago");
    expect(when(new Date(now - 3 * 3600e3).toISOString(), { now })).toBe("3 h");
    expect(when(new Date(2026, 9, 16, 8, 44).getTime() / 1000, { now })).toBe("16 Oct 08:44");
    expect(when(null)).toBe("");
  });

  it("says how long a build has run", () => {
    expect(dur(null)).toBe("–");
    expect(dur(20)).toBe("under 1 min");
    expect(dur(720)).toBe("12 min");
    expect(dur(3900)).toBe("1 h 5 min");
  });
});
