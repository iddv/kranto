// Page views for Kranto's usage counters: which page was shown and how long it
// took to draw, nothing else. The page is the route's node pattern as nodes.json writes it
// ("topics/:id", never the id), so no object, filter or text of the address is ever posted.
// Off (Settings › Privacy & access, DO_NOT_TRACK in the service): nothing is posted at all. The views go
// to Kranto's own server (POST /api/telemetry/view) at most once every 30 s; the server counts
// them through its allow-list and sends nothing unless the person chose to.
import { NODES } from "./router";

export const VIEW_URL = "/api/telemetry/view";
export const STATUS_URL = "/api/settings/telemetry";
export const FLUSH_MS = 30000;
const MAX = 50;

let on = false;
let last: string | null = null;
let queue: { node: string; ms: number }[] = [];
let timer: ReturnType<typeof setTimeout> | null = null;

/** The node pattern a path matches (the first match wins, as matchRoute), unfilled. */
export function nodeOf(path: string[]): string | null {
  for (const n of NODES) {
    const pat = n.route ? n.route.split("/") : [];
    if (pat.length !== path.length || !pat.every((p, i) => p[0] === ":" || p === path[i])) continue;
    return n.node || null;
  }
  return null;
}

/** Ask the server once whether the counters are on (hosted only: the server answers). */
export async function startViews(): Promise<boolean> {
  try {
    const r = await fetch(STATUS_URL, { cache: "no-store" });
    const st = r.ok ? ((await r.json()) as { mode?: string }) : null;
    on = !!st && !!st.mode && st.mode !== "off";
  } catch {
    on = false;
  }
  if (on) addEventListener("visibilitychange", () => document.hidden && flushViews());
  return on;
}

/** A page was drawn: one view, unless it is the page already counted last. */
export function noteView(path: string[], ms: number): void {
  if (!on) return;
  const node = nodeOf(path);
  if (!node || node === last) return;
  last = node;
  if (queue.length < MAX) queue.push({ node, ms: Math.max(0, Math.round(ms)) });
  if (!timer) timer = setTimeout(flushViews, FLUSH_MS);
}

export function flushViews(): void {
  if (timer) clearTimeout(timer);
  timer = null;
  if (!queue.length) return;
  const views = queue;
  queue = [];
  void fetch(VIEW_URL, {
    method: "POST",
    cache: "no-store",
    keepalive: true,
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ views }),
  }).catch(() => undefined);
}

/** tests: back to the start */
export function resetViews(enabled = false): void {
  on = enabled;
  last = null;
  queue = [];
  if (timer) clearTimeout(timer);
  timer = null;
}
