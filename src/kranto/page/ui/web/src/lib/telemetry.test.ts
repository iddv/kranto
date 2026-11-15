import { afterEach, describe, expect, it, vi } from "vitest";
import { flushViews, nodeOf, noteView, resetViews, startViews, STATUS_URL, VIEW_URL } from "./telemetry";

afterEach(() => {
  resetViews();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("page views for the usage counters", () => {
  it("names the route's node pattern, never the object", () => {
    expect(nodeOf(["topics", "42", "evidence"])).toBe("topics/:id/evidence");
    expect(nodeOf(["ideas", "secret-card-id"])).toBe("ideas");
    expect(nodeOf([])).toBeNull(); // a redirect counts no view: its landing does
    expect(nodeOf(["builds", "a-build"])).toBeNull();
    expect(nodeOf(["no", "such", "page", "here"])).toBeNull();
  });

  it("posts nothing when the counters are off", async () => {
    const fetch = vi.fn(async (_url: string, _init?: RequestInit) => new Response(JSON.stringify({ mode: "off" })));
    vi.stubGlobal("fetch", fetch);
    expect(await startViews()).toBe(false);
    noteView(["ideas"], 3);
    flushViews();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0]![0]).toBe(STATUS_URL);
  });

  it("batches views, drops repeats and posts only node and ms", async () => {
    vi.useFakeTimers();
    const fetch = vi.fn(async (_url: string, _init?: RequestInit) => new Response(JSON.stringify({ mode: "local" })));
    vi.stubGlobal("fetch", fetch);
    expect(await startViews()).toBe(true);
    noteView(["topics", "7"], 12.4);
    noteView(["topics", "8"], 3);
    noteView(["ideas", "i123"], 5);
    expect(fetch).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(30000);
    expect(fetch).toHaveBeenCalledTimes(2);
    const [url, init] = fetch.mock.calls[1] as unknown as [string, RequestInit];
    expect(url).toBe(VIEW_URL);
    expect(JSON.parse(init.body as string)).toEqual({ views: [{ node: "topics/:id", ms: 12 }, { node: "ideas", ms: 5 }] });
  });
});
