// For the app's own tests (lib/app/*.test.ts): the frame its draw needs, the network it reads
// (fetch for api(), loadHost() and loadWho(); the shared reads for the rest), and a server
// status to answer with. Nothing here touches a model or the network.
import { vi } from "vitest";
import type { Status } from "../../api/afk.gen";
import { drop, setFetcher } from "../reads.svelte";
import { connect, ui } from "../shell.svelte";
import * as app from "./index";
import { closePop } from "../../ui/popover";
import { load, loadHost, loadWho } from "./data";
import { resetFocus } from "./rows";

/** a card as the server's /api/ideas answers it */
export const card = (n: number, state = "waiting", o: Record<string, unknown> = {}) => ({
  number: n, id: n, title: "Card " + n, status: "ok", score: 0.5, grade: null, topics: [], citations: [], evidence: [], state, later_until: null,
  created_at: "2026-11-01T08:00:00Z", ...o,
});
export function hostStatus(o: Partial<Status> = {}): Status {
  return {
    version: "0.3.74", host_api: 2, observations: 10, rollups: 0, spend_this_month_usd: 0, budget_usd: 20, tokens_today: { in: 100, out: 50 } as never,
    paused: null, preview: null, topics: [{ id: 1, name: "Clinics", description: "care", kind: "topic", ref: null }, { id: 2, name: "Local-first", description: "", kind: "topic", ref: null }],
    sources: [], runs: [], scheduler: true, running: null, ingest_progress: null, next_run: { ingest: null }, lanes: {}, hold: null, builds: true, browser: true, cubs_developer: true,
    update: { available: null, installed: "0.3.74", channel: "stable", state: "idle", detail: null, reason: null, to: null, notes: [], notes_url: null, can_apply: true,
      checked_at: null, check_failing: null, failing_since: null },
    ...o,
  };
}

export interface Net {
  /** every request fetch() was given: [url, init] */
  calls: [string, RequestInit | undefined][];
  /** what a path answers next: a value (200 JSON), or a Response */
  answer: Record<string, unknown>;
}
/** fetch() answered from net.answer by path (the query kept); anything else is a 404 */
export function network(answer: Record<string, unknown>): Net {
  const net: Net = { calls: [], answer };
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    net.calls.push([url, init]);
    const a = net.answer[url];
    if (a instanceof Response) return a;
    if (a === undefined) return new Response("not found", { status: 404 });
    return new Response(JSON.stringify(typeof a === "function" ? (a as (i?: RequestInit) => unknown)(init) : a), { status: 200 });
  }));
  return net;
}
/** the shared reads (read()), answered from a table by path */
export function reads(answers: Record<string, unknown>): void {
  drop("");
  setFetcher(async (path) => {
    if (!(path in answers)) throw new Error("not found: " + path);
    return structuredClone(answers[path]);
  });
}

/** an element for a test's page, made with DOM calls (no source writes HTML, tests included):
 * attributes by name ("class", "id", "href", "data-sel"…), then its children, text as text */
export function h(tag: string, attrs: Record<string, string | boolean> = {}, ...kids: (Node | string)[]): HTMLElement {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== false) e.setAttribute(k, v === true ? "" : v);
  e.append(...kids);
  return e;
}

/** the frame the shell draws (App.svelte's ids), the app connected to it, and its first reads */
export async function frame(o: { host?: Status | null; who?: unknown; reads?: Record<string, unknown>; hash?: string } = {}) {
  document.body.replaceChildren(h("div", { id: "app" }, h("div", { id: "rows", tabindex: "-1" }), h("div", { id: "dscroll", tabindex: "-1" })),
    h("dialog", { id: "dlg" }), h("dialog", { id: "pal" }));
  window.matchMedia = ((q: string) => ({ matches: false, media: q })) as never;
  history.replaceState(null, "", o.hash ?? "#/home");
  const net = network({ "/api/status": o.host === undefined ? hostStatus() : o.host ?? undefined, "/api/whoami": o.who ?? { origin: "ann", require_token: true } });
  reads(o.reads ?? {});
  connect(app);
  await Promise.all([loadHost(), loadWho()]);
  await load();
  return net;
}
export function unframe(): void {
  closePop(false);
  resetFocus();
  connect(null);
  ui.facts = null;
  ui.headOn = false; // a page drawn by itself next draws its own title
  ui.head = null;
  document.body.replaceChildren();
  vi.unstubAllGlobals();
}
export const tick = async (): Promise<void> => {
  for (let i = 0; i < 3; i++) await new Promise((r) => setTimeout(r, 0));
};
