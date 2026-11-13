// A trace's words and marks: a status is a glyph **and** a word, never colour
// alone; numbers in the mono face. Tokens, never dollars (the owner's ruling of 2026-10-09:
// dollars only on Settings › Spend).
import type { SpanSummary, TraceSummary } from "../../api/types.gen";
import { kTok } from "../../lib/format";

export const STATUS: Record<string, { glyph: string; word: string; tone: string }> = {
  ok: { glyph: "●", word: "ok", tone: "green" },
  error: { glyph: "✕", word: "error", tone: "red" },
  running: { glyph: "◔", word: "running", tone: "blue" },
  unset: { glyph: "○", word: "no outcome", tone: "grey" },
};
export const DENIED = { glyph: "⊘", word: "denied", tone: "red" };

/** the mark a row shows: its status, a denial, an event's level */
export function mark(s: Pick<SpanSummary, "status" | "denied" | "kind"> & { attrs?: Record<string, unknown> }): { glyph: string; word: string; tone: string } {
  if (s.denied) return DENIED;
  if (s.kind === "event") {
    const lv = s.attrs?.level;
    if (s.status === "error" || lv === "error") return { glyph: "⚠", word: "error", tone: "red" };
    return lv === "warning" ? { glyph: "⚠", word: "warning", tone: "amber" } : { glyph: "ⓘ", word: "note", tone: "grey" };
  }
  return STATUS[s.status] || STATUS.unset!;
}

export const STATE: Record<TraceSummary["state"], { glyph: string; word: string; tone: string }> = {
  // every run's trace (an ingest, a console session, a build): running, never "building"
  running: { glyph: "◔", word: "running", tone: "blue" },
  ok: { glyph: "✓", word: "ok", tone: "green" },
  error: { glyph: "✕", word: "failed", tone: "red" },
  stopped: { glyph: "⊘", word: "stopped", tone: "amber" },
};

export const KIND: Record<string, string> = {
  run: "run", stage: "stage", session: "session", turn: "turn", tool: "tool", subagent: "sub-agent",
  hook: "hook", call: "one-shot", event: "event",
};

/** a span's time: "73 ms", "2.7 s", "11 min", "1 h 47 min"; "" without both ends */
export function took(s: Pick<SpanSummary, "start" | "end">): string {
  if (s.start == null || s.end == null) return "";
  return secs(s.end - s.start);
}
export function secs(d: number): string {
  if (d < 0) return "";
  if (d < 1) return Math.round(d * 1000) + " ms";
  if (d < 10) return d.toFixed(1) + " s";
  if (d < 60) return Math.round(d) + " s";
  const m = Math.round(d / 60);
  return m < 60 ? m + " min" : Math.floor(m / 60) + " h " + (m % 60) + " min";
}

/** a span's tokens: "25k/6" (in, cached included / out) or "" */
export function toks(t: Record<string, number> | null | undefined): string {
  if (!t) return "";
  const i = (t.in || 0) + (t.cache_read || 0) + (t.cache_write || 0), o = t.out || 0;
  return i || o ? `${kTok(i)}/${kTok(o)}` : "";
}
export function tokTitle(t: Record<string, number> | null | undefined): string | undefined {
  if (!t) return undefined;
  const n = (k: string) => (t[k] || 0).toLocaleString("en-GB");
  return `${n("in")} in · ${n("cache_read")} cache read · ${n("cache_write")} cache write · ${n("out")} out` + (t.thinking ? ` · ${n("thinking")} thinking` : "");
}

/** the row's words: the span's name and, for a tool or a turn, the first words of its input */
export function rowName(s: SpanSummary): string {
  if (s.kind === "session") return `session ${s.name}`;
  return s.name;
}

/** "Beliefline · Build 1" */
export const traceTitle = (t: Pick<TraceSummary, "title">): string => t.title;

/** the facts line of a trace's head: state, sessions, tool calls, tokens, wall time, errors */
export function factsLine(t: TraceSummary): string[] {
  const out: string[] = [];
  if (t.calls != null) {
    // a Watching run: model calls (and a cub's host calls, when it made any), no sessions
    out.push(`${t.calls} model call${t.calls === 1 ? "" : "s"}`);
    if (t.tools) out.push(`${t.tools} host call${t.tools === 1 ? "" : "s"}`);
  } else {
    out.push(`${t.sessions} session${t.sessions === 1 ? "" : "s"}`);
    out.push(`${t.tools} tool call${t.tools === 1 ? "" : "s"}`);
  }
  const k = t.tokens || {};
  const tk = (k.in || 0) + (k.cache_read || 0) + (k.cache_write || 0) + (k.out || 0);
  if (tk) out.push(kTok(tk) + " tokens");
  if (t.wall_s) out.push(secs(t.wall_s));
  out.push(`${t.errors} error${t.errors === 1 ? "" : "s"}`);
  return out;
}
