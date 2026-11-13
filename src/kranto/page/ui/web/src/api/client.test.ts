import { afterEach, describe, expect, expectTypeOf, it, vi } from "vitest";
import { ApiError, get } from "./client";
import type { Header } from "./types.gen";

function answering(status: number, body: unknown) {
  const f = vi.fn(async () => new Response(JSON.stringify(body), { status }));
  vi.stubGlobal("fetch", f);
  return f;
}

afterEach(() => vi.unstubAllGlobals());

describe("the typed client", () => {
  it("reads a route with its type, never from a cache", async () => {
    const f = answering(200, { api_version: 3, paused: false });
    const h = await get("api/header");
    expectTypeOf(h).toEqualTypeOf<Header>();
    expect(h.paused).toBe(false);
    expect(f).toHaveBeenCalledWith("api/header", { cache: "no-store" });
  });

  it("passes a query", async () => {
    const f = answering(200, { api_version: 3, paused: false });
    await get("api/header", { a: "1" });
    expect(f).toHaveBeenCalledWith("api/header?a=1", { cache: "no-store" });
  });

  it("turns an error answer into an ApiError with its words", async () => {
    answering(409, { error: "it is running" });
    await expect(get("api/header")).rejects.toEqual(new ApiError(409, "it is running"));
    vi.stubGlobal("fetch", vi.fn(async () => new Response("not json", { status: 502 })));
    await expect(get("api/header")).rejects.toMatchObject({ status: 502, message: "HTTP 502" });
  });
});
