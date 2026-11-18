import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GAP_MS, live, livePaused, POLL_MS, RETRY_MS, SAFETY_MS } from "./live";

class FakeSource {
  static CLOSED = 2;
  static all: FakeSource[] = [];
  readyState = 1;
  listeners: Record<string, ((e: MessageEvent) => void)[]> = {};
  constructor(readonly url: string) {
    FakeSource.all.push(this);
  }
  addEventListener(name: string, fn: (e: MessageEvent) => void) {
    (this.listeners[name] = this.listeners[name] || []).push(fn);
  }
  emit(name: string, data?: unknown) {
    for (const fn of this.listeners[name] || []) fn({ data: JSON.stringify(data) } as MessageEvent);
  }
  close() {
    this.readyState = FakeSource.CLOSED;
  }
}

const read = () => vi.fn<() => Promise<void>>(async () => {});
let L: { refresh: ReturnType<typeof read>; loadHost: ReturnType<typeof read>; loadWho: ReturnType<typeof read> };
beforeEach(() => {
  vi.useFakeTimers();
  FakeSource.all = [];
  vi.stubGlobal("EventSource", FakeSource);
  L = { refresh: read(), loadHost: read(), loadWho: read() };
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("the live feed", () => {
  it("reads again on a change, once for a burst, at most every 2 s", async () => {
    const f = live(L);
    const s = FakeSource.all[0] as FakeSource;
    expect(s.url).toBe("/api/stream"); // under the page's prefix (here "/": lib/base.ts)
    s.emit("open");
    s.emit("change", { kinds: ["builds"] });
    s.emit("change", { kinds: ["term"] });
    await vi.advanceTimersByTimeAsync(0);
    expect(L.refresh).toHaveBeenCalledTimes(1);
    s.emit("change", { kinds: ["builds"] });
    await vi.advanceTimersByTimeAsync(GAP_MS - 100);
    expect(L.refresh).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(200);
    expect(L.refresh).toHaveBeenCalledTimes(2);
    expect(f.mode()).toBe("live");
    f.stop();
  });

  it("polls every 5 s after two errors, and stops once the feed is back", async () => {
    const f = live(L);
    const s = FakeSource.all[0] as FakeSource;
    s.emit("error");
    expect(f.mode()).toBe("live");
    s.emit("error");
    expect(f.mode()).toBe("polling");
    await vi.advanceTimersByTimeAsync(POLL_MS * 2 + 10);
    expect(L.refresh).toHaveBeenCalledTimes(2);
    s.emit("open");
    expect(f.mode()).toBe("live");
    f.stop();
  });

  it("reads at once when the feed comes back after a drop, not at the next change", async () => {
    const f = live(L);
    const s = FakeSource.all[0] as FakeSource;
    s.emit("open");
    await vi.advanceTimersByTimeAsync(GAP_MS * 2);
    expect(L.refresh).not.toHaveBeenCalled(); // the first open: the page has just read
    s.emit("error"); // the feed drops; what changes meanwhile sends no event
    s.emit("open"); // and comes back
    await vi.advanceTimersByTimeAsync(GAP_MS);
    expect(L.refresh).toHaveBeenCalledTimes(1);
    s.emit("open"); // a second open with no drop between reads nothing more
    await vi.advanceTimersByTimeAsync(GAP_MS * 2);
    expect(L.refresh).toHaveBeenCalledTimes(1);
    f.stop();
  });

  it("polls when refused, and tries the feed again 30 s later", async () => {
    const f = live(L);
    const s = FakeSource.all[0] as FakeSource;
    s.readyState = FakeSource.CLOSED; // refused or gone (an older server answered the ninth stream 503)
    s.emit("error");
    expect(f.mode()).toBe("polling");
    await vi.advanceTimersByTimeAsync(RETRY_MS + 10);
    expect(FakeSource.all).toHaveLength(2);
    f.stop();
  });

  it("polls when the feed says busy, says live updates are paused, and is live again on a real stream", async () => {
    const f = live(L);
    const s = FakeSource.all[0] as FakeSource;
    s.emit("open"); // the busy answer is a 200: open fires first
    s.emit("busy", { why: "every place is taken", retry_ms: 30000 });
    expect(s.readyState).toBe(FakeSource.CLOSED); // closed by the page, so no reconnect storm
    expect(f.mode()).toBe("polling");
    expect(livePaused()).toBe(true);
    await vi.advanceTimersByTimeAsync(RETRY_MS + 10);
    const t = FakeSource.all[1] as FakeSource;
    t.emit("open");
    t.emit("host", { version: "0.3.57" });
    expect(f.mode()).toBe("live");
    expect(livePaused()).toBe(false);
    f.stop();
  });

  it("reads every 60 s whatever happens, with the server's status and who this is", async () => {
    const f = live(L);
    await vi.advanceTimersByTimeAsync(SAFETY_MS + 10);
    expect(L.refresh).toHaveBeenCalledTimes(1);
    expect(L.loadHost).toHaveBeenCalledTimes(1);
    expect(L.loadWho).toHaveBeenCalledTimes(1);
    f.stop();
  });

  it("reloads the page when the feed's host answers with a new version", () => {
    const reload = vi.fn();
    vi.stubGlobal("location", { reload });
    const f = live(L);
    const s = FakeSource.all[0] as FakeSource;
    s.emit("host", { version: "0.3.57" });
    s.emit("host", { version: "0.3.57" });
    expect(reload).not.toHaveBeenCalled();
    s.emit("host", { version: "0.3.58" });
    expect(reload).toHaveBeenCalledTimes(1);
    f.stop();
  });
});
