import { describe, expect, it } from "vitest";

import { pageUrl } from "./base";

describe("the page's own addresses", () => {
  it("puts a path of the page's own under its prefix", () => {
    expect(pageUrl("api/term", "/brb/")).toBe("/brb/api/term");
    expect(pageUrl("static/brand/mark.svg", "/brb/")).toBe("/brb/static/brand/mark.svg");
    expect(pageUrl("api/stream", "/")).toBe("/api/stream");
  });

  it("leaves an absolute path or a full address as it is", () => {
    expect(pageUrl("/api/health", "/brb/")).toBe("/api/health");
    expect(pageUrl("https://example.org/x", "/brb/")).toBe("https://example.org/x");
    expect(pageUrl("data:image/png;base64,AA", "/brb/")).toBe("data:image/png;base64,AA");
  });
});
