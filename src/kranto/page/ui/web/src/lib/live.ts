// The page stays fresh: the live feed (GET api/stream, server-sent events)
// says what changed and the page reads again (its usual reads, at most every 2 s). While the
// feed is down (two errors within 30 s, or busy: the ninth stream says so and ends) the page reads
// every 5 s, as it did before and tries the feed again after 30 s. A read every 60 s runs
// whatever happens, so a missed event never leaves a page stale. A new version on the feed's
// host event means Kranto was updated: the page reloads. the server's status and who this browser
// is are read every 60 s.
import type { App } from "./app";

export const GAP_MS = 2000;
export const POLL_MS = 5000;
export const SAFETY_MS = 60000;
export const RETRY_MS = 30000;

// every stream place taken (the feed says busy): the status bar says live updates are paused
let PAUSED = false;
export const livePaused = (): boolean => PAUSED;

export interface Live {
  /** "live" on the feed, "polling" without it */
  mode(): "live" | "polling";
  stop(): void;
}

export function live(L: Pick<App, "refresh" | "loadHost" | "loadWho">, url = "api/stream",
  onVerb?: () => Promise<boolean>): Live {
  let es: EventSource | null = null;
  let poll: ReturnType<typeof setInterval> | null = null;
  let errors: number[] = [];
  let version: string | null = null;
  let last = 0;
  let queued: ReturnType<typeof setTimeout> | null = null;
  let busy = false;
  let stopped = false;
  let dropped = false;
  const timers: ReturnType<typeof setInterval>[] = [];

  async function read(): Promise<void> {
    if (busy) {
      soon();
      return;
    }
    busy = true;
    last = Date.now();
    try {
      await L.refresh();
    } finally {
      busy = false;
    }
  }
  // a change: read now, or as soon as 2 s have passed since the last read (one read for a burst)
  function soon(): void {
    if (queued) return;
    queued = setTimeout(() => {
      queued = null;
      void read();
    }, Math.max(0, GAP_MS - (Date.now() - last)));
  }
  function polling(on: boolean): void {
    if (on && !poll) poll = setInterval(() => void read(), POLL_MS);
    if (!on && poll) {
      clearInterval(poll);
      poll = null;
    }
  }
  function open(): void {
    if (stopped) return;
    if (typeof EventSource === "undefined") {
      polling(true);
      return;
    }
    const s = (es = new EventSource(url));
    s.addEventListener("open", () => {
      errors = [];
      polling(false);
      // back after a drop: what changed meanwhile sent no event, so read now (a running trace
      // reads on from its cursor: one request, not the next change or the 60 s read)
      if (dropped) {
        dropped = false;
        soon();
      }
    });
    // every place taken: the feed says busy and ends (no 503 in the console, QA B20); poll, and
    // try again in 30 s
    s.addEventListener("busy", () => {
      s.close();
      if (es === s) es = null;
      dropped = true;
      PAUSED = true;
      polling(true);
      timers.push(setTimeout(open, RETRY_MS));
    });
    s.addEventListener("host", (e) => {
      PAUSED = false;
      let v: string | null = null;
      try {
        v = JSON.parse((e as MessageEvent).data).version || null;
      } catch {
        v = null;
      }
      if (version && v && v !== version) location.reload();
      if (v) version = v;
    });
    s.addEventListener("change", (e) => {
      // an assistant's verb: its rows are marked, and the server's reads are read again
      let kinds: string[] = [];
      try {
        kinds = JSON.parse((e as MessageEvent).data).kinds || [];
      } catch {
        kinds = [];
      }
      if (onVerb && kinds.includes("verb")) void onVerb().then(() => soon());
      else soon();
    });
    s.addEventListener("error", () => {
      dropped = true;
      const now = Date.now();
      errors = [...errors.filter((t) => now - t < RETRY_MS), now];
      if (s.readyState === EventSource.CLOSED) {
        // refused (503) or gone: read on a timer, and try the feed again later
        if (es === s) es = null;
        polling(true);
        timers.push(setTimeout(open, RETRY_MS));
      } else if (errors.length >= 2) polling(true);
    });
  }
  open();
  if (onVerb) void onVerb();             // learns where the lines are; marks nothing old
  timers.push(setInterval(() => void read(), SAFETY_MS));
  timers.push(setInterval(() => void L.loadHost(), SAFETY_MS));
  timers.push(setInterval(() => void L.loadWho(), SAFETY_MS));
  const visible = () => {
    if (!document.hidden) soon();
  };
  document.addEventListener("visibilitychange", visible);
  return {
    mode: () => (poll ? "polling" : "live"),
    stop() {
      stopped = true;
      es?.close();
      polling(false);
      if (queued) clearTimeout(queued);
      for (const t of timers) clearInterval(t);
      document.removeEventListener("visibilitychange", visible);
    },
  };
}
