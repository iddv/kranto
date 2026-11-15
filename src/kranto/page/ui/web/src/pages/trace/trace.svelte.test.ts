// The trace page: the tree from the API's answers, folds, the selection a
// link names, Errors only, the inspector's tabs, the chat and the diff, and untrusted text drawn
// as text: no script, no image, no script-scheme link, bidi overrides and ANSI made visible.
import { afterEach, describe, expect, it, vi } from "vitest";
import { flushSync } from "svelte";
import type { SpanSummary, TraceDetail } from "../../api/types.gen";
import { draw, settle, stub } from "../testing.svelte";
import TracePage from "./TracePage.svelte";
import { TraceStore } from "./trace.svelte";
import { safeText } from "./safe";
import { factsLine } from "./words";
import type { Where } from "../../lib/pages.svelte";

const TID = "session:demo";
const T0 = 1_790_000_000;

function sp(o: Partial<SpanSummary> & Pick<SpanSummary, "id" | "kind" | "name" | "pos" | "depth">): SpanSummary {
  return {
    parent: null, stage: null, start: T0 + o.pos, end: T0 + o.pos + 1, status: "ok", preview: "", usd: null, usd_kind: "none",
    tokens: null, children: 0, error: null, tool: null, denied: false, rev: 1, ...o,
  };
}
const SPANS: SpanSummary[] = [
  sp({ id: "run", kind: "run", name: "Demo session", pos: 0, depth: 0, children: 2 }),
  sp({ id: "stb", kind: "stage", name: "build", pos: 1, depth: 1, parent: "run", children: 1, stage: "build" }),
  sp({ id: "ses", kind: "session", name: "build", pos: 2, depth: 2, parent: "stb", children: 3, stage: "build", tokens: { in: 10, cache_read: 900, cache_write: 0, out: 50 } }),
  sp({ id: "t1", kind: "turn", name: "turn 1", pos: 3, depth: 3, parent: "ses", children: 1, stage: "build" }),
  sp({ id: "b1", kind: "tool", name: "Bash", tool: "Bash", pos: 4, depth: 4, parent: "t1", preview: "ls -la", stage: "build" }),
  sp({ id: "t2", kind: "turn", name: "turn 2", pos: 5, depth: 3, parent: "ses", children: 1, stage: "build" }),
  sp({ id: "e1", kind: "tool", name: "Edit", tool: "Edit", pos: 6, depth: 4, parent: "t2", preview: "app.py", stage: "build" }),
  sp({ id: "t3", kind: "turn", name: "turn 3", pos: 7, depth: 3, parent: "ses", children: 1, stage: "build" }),
  sp({ id: "x1", kind: "tool", name: "Bash", tool: "Bash", pos: 8, depth: 4, parent: "t3", preview: "pytest -q", status: "error", error: "exit 2", stage: "build" }),
  sp({ id: "stv", kind: "stage", name: "verify", pos: 9, depth: 1, parent: "run", children: 0, stage: "verify" }),
];
const DETAIL: TraceDetail = {
  id: TID, source: "session", key: "demo", n: 2, title: "Demo session", state: "error", outcome: null, started: T0, ended: T0 + 60,
  wall_s: 60, usd: 1.5, usd_kind: "exact", tokens: { in: 10, cache_read: 900, cache_write: 0, out: 50 }, sessions: 1, tools: 3,
  errors: 1, failed_at: "x1", failed_label: "build › turn 3 › Bash", model: "m", spans: SPANS.length, href: "#/sessions/demo/trace",
  stages: [SPANS[1]!, SPANS[9]!], links: [{ kind: "check", ref: "f3", span: "x1", note: null, detail: null }], files: [],
  cursor: "c0", running: false, note: null, line: null, stop: null,
};
let over: Partial<TraceDetail> = {}; // a test's own detail (the empty states)
// the bidi overrides are made at runtime: a literal one in a source file is itself the attack
const RLO = String.fromCharCode(0x202e), PDF = String.fromCharCode(0x202c), ESC = String.fromCharCode(0x1b);
const JS = "java" + "script:"; // the scheme, made here: the sources hold no such sink (test_web_ui)
const EVIL = [
  "<script>alert(1)</script>", '<img src=x onerror="alert(1)">', "![pic](http://evil.example/x.png)",
  `[click me](${JS}alert(1))`, RLO + "evil.exe" + PDF, ESC + "[31mred text" + ESC + "[0m", `<a href="${JS}alert(2)">x</a>`,
].join("\n");
const SPAN = (id: string) => ({
  ...SPANS.find((s) => s.id === id)!, attributes: { call_id: "toolu_1", tool: "Bash" }, events: [], links: [], inputs: { bytes: 10, part: "input" },
  outputs: { bytes: 20, part: "output" }, source: { file: ".den/v5/r2/transcripts/build.transcript.jsonl", line: 4 }, error_detail: null,
  path: "/x/.den/v5/r2/transcripts/build.transcript.jsonl", redactions: [],
});

function answers(path: string): unknown {
  const u = new URL(path, "http://x/");
  const p = u.pathname.replace(/^\//, ""), q = Object.fromEntries(u.searchParams);
  if (p === "api/trace") return { ...DETAIL, ...over };
  if (p === "api/trace/spans") {
    if (q.filter === "errors") return { spans: SPANS.filter((s) => ["run", "stb", "ses", "t3", "x1"].includes(s.id)), cursor: "c", more: false, total: 5, rev: 1, matches: ["x1"] };
    return { spans: SPANS, cursor: "c1", more: false, total: SPANS.length, rev: 1, running: false };
  }
  if (p === "api/trace/span") return SPAN(q.span!);
  if (p === "api/trace/payload") {
    if (q.part === "output") return { text: EVIL, offset: 0, next: null, bytes: EVIL.length, is_error: q.span === "x1", redactions: [{ kind: "GitHub token", n: 1 }] };
    if (q.part === "input") return { fields: [{ key: "command", value: EVIL }], redactions: [] };
    if (q.part === "chat") return {
      messages: [
        { role: "you", kind: "text", text: "Make it.", ts: null, i: 0 },
        { role: "claude", kind: "thinking", text: "plan", ts: null, i: 1, span: "t1" },
        { role: "claude", kind: "text", text: "I'll look. " + EVIL, ts: null, i: 2, span: "t1" },
        { role: "claude", kind: "tool_call", tool: "Bash", text: "ls -la", ts: null, i: 3, span: "b1" },
        { role: "tool", kind: "tool_result", text: EVIL, ts: null, i: 4, span: "b1", is_error: false, cut: false },
      ], offset: 0, next: null, total: 5, focus: 2, redactions: [],
    };
    if (q.part === "diff") return { file_path: "app.py", hunks: [{ header: "@@ -1,2 +1,2 @@", lines: [" a", "-b", "+c"] }], added: 1, removed: 1, new_file: false, redactions: [] };
  }
  if (p === "api/traces") return { traces: [{ ...DETAIL, n: 2 }], next: null };
  throw new Error("not found: " + path);
}

function at(path: string, q: Record<string, string> = {}): Where {
  const p = path.split("/");
  return { r: { path: p, q, sel: null }, node: "trace", list: p, object: null, obj: null, id: null, sel: false, stage: true, missing: false };
}

async function open(q: Record<string, string> = {}) {
  const L = stub();
  const keys: Record<string, () => void> = {};
  (L as unknown as { pageKey: (k: string, f: () => void) => void }).pageKey = vi.fn((k: string, f: () => void) => { keys[k] = f; });
  const get = vi.fn(async (p: string) => structuredClone(answers(p)));
  const d = await draw(TracePage, at("sessions/demo/trace", q), null, { get });
  await settle();
  await settle();
  return { ...d, get, keys };
}

const rowNames = (t: HTMLElement) => [...t.querySelectorAll(".sr .t-nm b")].map((b) => b.textContent);

afterEach(() => {
  document.body.replaceChildren();
  over = {};
});

describe("a Watching run's trace", () => {
  it("counts model calls, not sessions, and its crumb uses the doors' words", async () => {
    const run = { ...DETAIL, source: "afk", sessions: 0, tools: 0, calls: 20 };
    expect(factsLine(run)[0]).toBe("20 model calls");
    expect(factsLine(run).join(" ")).not.toMatch(/session|tool call/);
    expect(factsLine({ ...run, tools: 2 })[1]).toBe("2 host calls");
    expect(factsLine(DETAIL).slice(0, 2)).toEqual(["1 session", "3 tool calls"]); // a session: as before
    over = run;
    const L = stub();
    (L as unknown as { pageKey: (k: string, f: () => void) => void }).pageKey = vi.fn();
    const get = vi.fn(async (p: string) => structuredClone(answers(p)));
    const { target, done } = await draw(TracePage, at("afk/r1/trace"), null, { get });
    await settle();
    const crumb = (target.querySelector(".crumb")?.textContent || "").replace(/\s+/g, " ").trim();
    expect(crumb).toBe("Home › Activity › Trace"); // a run is under Activity
    expect(target.querySelector(".facts-line")?.textContent).toContain("20 model calls");
    done();
  });
});

describe("the trace page", () => {
  it("says why a trace is short in the server's note, and nothing of its own", async () => {
    over = { note: "This session kept no transcript: sessions that ended before Kranto 0.5.0 kept none, so there is nothing to show but how it ended." };
    let d = await open();
    expect(d.target.querySelector("#trace-note")?.textContent).toContain("kept no transcript");
    d.done();
    document.body.replaceChildren();
    over = { sessions: 0 };
    d = await open();
    expect(d.target.querySelector("#trace-note")).toBeNull();
    d.done();
    document.body.replaceChildren();
    over = {};
    d = await open();
    expect(d.target.querySelector("#trace-note")).toBeNull(); // a trace with its sessions says nothing
    d.done();
  });

  it("draws the head and the tree, turns folded", async () => {
    const { target, done } = await open();
    expect(target.querySelector("h1")?.textContent).toBe("Demo session");
    expect((target.querySelector(".crumb")?.textContent || "").replace(/\s+/g, " ").trim()).toBe("Home › Open in Claude Code › Trace");
    expect(target.querySelector(".dk")?.textContent).toMatch(/^session · trace/);
    const facts = target.querySelector(".facts-line")?.textContent || "";
    expect(facts).toContain("failed");
    expect(facts).toContain("1 session");
    expect(facts).toContain("3 tool calls");
    expect(facts).not.toMatch(/\$\d/); // tokens, never dollars
    expect(rowNames(target)).toEqual(["Demo session", "build", "session build", "turn 1", "turn 2", "turn 3", "verify"]);
    done();
  });

  it("unfolds a turn, and opens at the span a link names with its Output", async () => {
    const { target, done } = await open({ check: "f3" });
    expect(rowNames(target)).toContain("Bash");
    const sel = target.querySelector(".sr.t-sel");
    expect(sel?.getAttribute("data-span")).toBe("x1");
    await settle();
    const cur = target.querySelector(".itabs [aria-current=page]")?.textContent || "";
    expect(cur.startsWith("Output")).toBe(true);
    expect(target.querySelector(".sr.failed .fa")?.textContent).toContain("failed here");
    done();
  });

  it("a search offers Search every payload…, which asks the server to read the files", async () => {
    const { target, get, done } = await open();
    const box = target.querySelector<HTMLInputElement>(".find input")!;
    box.value = "zanzibar";
    box.dispatchEvent(new Event("input", { bubbles: true }));
    target.querySelector<HTMLFormElement>("form.find")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await settle();
    await settle();
    const more = target.querySelector<HTMLButtonElement>("#search-payloads");
    expect(more?.textContent).toBe("Search every payload…");
    expect(get.mock.calls.some(([p]) => String(p).includes("q=zanzibar") && !String(p).includes("payloads"))).toBe(true);
    more!.click();
    await settle();
    await settle();
    expect(get.mock.calls.some(([p]) => String(p).includes("q=zanzibar") && String(p).includes("payloads=1"))).toBe(true);
    expect(target.querySelector(".fl")?.textContent).toContain('"zanzibar" · in every payload');
    expect(target.querySelector("#search-payloads")).toBeNull(); // the second step is the last
    done();
  });

  it("folds and unfolds by the triangle", async () => {
    const { target, done } = await open();
    const tw = [...target.querySelectorAll(".sr")].find((r) => r.querySelector(".t-nm b")?.textContent === "turn 1")!.querySelector(".t-tw") as HTMLButtonElement;
    tw.click();
    flushSync();
    expect(rowNames(target)).toContain("Bash");
    tw.click();
    flushSync();
    expect(rowNames(target)).not.toContain("Bash");
    done();
  });

  it("Errors only shows the error spans and their ancestors", async () => {
    const { target, get, done } = await open();
    (target.querySelector(".chip") as HTMLButtonElement).click();
    await settle();
    expect(get.mock.calls.some(([p]) => String(p).includes("filter=errors"))).toBe(true);
    expect(rowNames(target)).toEqual(["Demo session", "build", "session build", "turn 3", "Bash"]);
    expect(target.querySelector(".fl")?.textContent).toContain("1 match");
    done();
  });

  it("e moves to the next error; j and k move; esc closes the inspector", async () => {
    const { target, keys, done } = await open();
    keys.e!();
    await settle();
    expect(target.querySelector(".sr.t-sel")?.getAttribute("data-span")).toBe("x1");
    keys.k!();
    await settle();
    expect(target.querySelector(".sr.t-sel")?.getAttribute("data-span")).toBe("t3");
    keys.esc!();
    await settle();
    expect(target.querySelector(".sr.t-sel")).toBeNull();
    done();
  });

  it("draws untrusted text as text: no script, no image, no live link; bidi and ANSI visible", async () => {
    const { target, keys, done } = await open({ span: "b1" });
    for (const tab of ["2", "3", "4"]) {
      keys[tab]!();
      await settle();
      await settle();
      expect(target.querySelector("script")).toBeNull();
      expect(target.querySelector("img")).toBeNull();
      expect(target.querySelector("a[href^='javascript']")).toBeNull();
      expect(target.querySelector("[onerror]")).toBeNull();
      const text = target.textContent || "";
      expect(text).not.toContain(ESC);
      expect(text).not.toContain(RLO);
      expect(text).toContain("<U+202E>");
      expect(text).toContain("<script>alert(1)</script>"); // shown, as words
    }
    done();
  });

  it("the chat lists the conversation in order, thinking folded; the diff shows its lines", async () => {
    const { target, keys, done } = await open({ span: "e1" });
    keys["4"]!();
    await settle();
    await settle();
    const who = [...target.querySelectorAll(".msg .who")].map((w) => (w.textContent || "").trim().split(" ")[0]);
    expect(who).toEqual(["you", "claude", "claude", "claude", "tool"]);
    expect(target.querySelector(".msg details")?.hasAttribute("open")).toBe(false);
    keys["5"]!();
    await settle();
    await settle();
    expect([...target.querySelectorAll(".dline")].map((l) => [l.className.includes("add") ? "+" : l.className.includes("del") ? "-" : " ", l.textContent])).toEqual([
      [" ", " a"], ["-", "-b"], ["+", "+c"]]);
    expect(target.textContent).toContain("+1");
    done();
  });

  it("Raw never draws the line: the command and the path to copy", async () => {
    const { target, keys, done } = await open({ span: "b1" });
    keys["6"]!();
    await settle();
    await settle();
    const t = target.textContent || "";
    expect(t).toContain("kranto trace show session:demo --span b1 --raw");
    expect(t).toContain("never draws a raw line");
    done();
  });
});

describe("a big trace", () => {
  it("holds 50,000 spans and draws a window of them (ui/Virtual)", async () => {
    const N = 50_000;
    const many = [SPANS[0]!, ...Array.from({ length: N - 1 }, (_, i) => sp({ id: "s" + i, kind: "event", name: "event " + i, pos: i + 1, depth: 1, parent: "run" }))];
    many[0] = { ...many[0]!, children: N - 1 };
    const L = stub();
    (L as unknown as { pageKey: () => void }).pageKey = vi.fn();
    const get = vi.fn(async (p: string) => {
      if (p.startsWith("api/trace?")) return { ...DETAIL, stages: [], links: [], failed_at: null, spans: N };
      if (p.startsWith("api/trace/spans")) {
        const after = new URL(p, "http://x/").searchParams.get("after");
        const from = after ? Number(after) : 0, page = many.slice(from, from + 5000);
        return { spans: page, cursor: String(from + page.length), more: from + page.length < N, total: N, rev: 1 };
      }
      throw new Error(p);
    });
    const t0 = performance.now();
    const { target, done } = await draw(TracePage, at("sessions/demo/trace"), null, { get });
    for (let i = 0; i < 14; i++) await settle();
    const rows = target.querySelectorAll(".sr").length;
    expect(rows).toBeGreaterThan(10);
    expect(rows).toBeLessThan(100);                        // a window, never 50,000 nodes
    expect((target.querySelector(".spacer") as HTMLElement).style.height).toBe(N * 30 + "px");
    expect(performance.now() - t0).toBeLessThan(15_000);
    done();
  });
});

describe("the trace's store", () => {
  it("reads pages from the cursor, folds a session's turns, and starts over on a stale cursor", async () => {
    let calls = 0;
    const get = vi.fn(async (p: string) => {
      if (p.startsWith("api/trace?")) return DETAIL;
      calls++;
      if (calls === 2) throw new Error("the trace was read again from its files; read from the top");
      const after = new URL(p, "http://x/").searchParams.get("after");
      return after ? { spans: SPANS.slice(5), cursor: "c2", more: false, total: 10, rev: 2 } : { spans: SPANS.slice(0, 5), cursor: "c1", more: true, total: 10, rev: 1 };
    });
    const s = new TraceStore(TID, get);
    await s.load();
    expect(s.order.map((x) => x.pos)).toEqual(SPANS.map((x) => x.pos));
    expect(s.rows().map((x) => x.id)).toEqual(["run", "stb", "ses", "t1", "t2", "t3", "stv"]);
    s.reveal("x1");
    expect(s.rows().map((x) => x.id)).toContain("x1");
  });
});

describe("safe text", () => {
  it("drops ANSI, pictures control characters, names bidi overrides", () => {
    expect(safeText(ESC + "[31mred" + ESC + "[0m")).toBe("red");
    expect(safeText("a" + String.fromCharCode(7) + "b")).toBe("a␇b");
    expect(safeText("x" + RLO + "y")).toBe("x<U+202E>y");
    expect(safeText("tab\tand\nnewline")).toBe("tab\tand\nnewline");
  });
});
