import { describe, expect, it } from "vitest";
import { CHOICES, errorsLine, fieldRows, sendingLine, type Privacy } from "./privacy";
import listSrc from "./PrivacyList.svelte?raw";
import paneSrc from "./PrivacyAccessPane.svelte?raw";

const base: Privacy = {
  mode: "local", why: "default", meaning: "counted on this machine only; nothing is sent", answered: false, answered_at: null,
  endpoint: null, sending: false, why_not: "counted on this machine only; nothing is sent", last_sent: null, next: null,
  bytes_today: 0, modes: [], summary: "", sent: [], remind: false,
};

describe("Settings › Privacy & access", () => {
  it("offers three answers, none of them local, and chooses none", () => {
    expect(CHOICES.map(([m]) => m)).toEqual(["basic", "detailed", "off"]);
  });
  it("says why nothing is sent", () => {
    expect(sendingLine(base)).toMatch(/^Not answered yet/);
    expect(sendingLine({ ...base, why: "DO_NOT_TRACK", mode: "off" })).toMatch(/DO_NOT_TRACK/);
    expect(sendingLine({ ...base, answered: true, mode: "basic", why: "config", why_not: "no endpoint is set: nothing leaves this machine" })).toBe("Nothing is sent: no endpoint is set: nothing leaves this machine.");
  });
  it("says when and where reports go once chosen", () => {
    const relay = "https://dde6yrzwuxncv.cloudfront.net/v1/logs";
    expect(sendingLine({ ...base, answered: true, mode: "basic", why: "config", sending: true, why_not: null, endpoint: relay, next: "2026-10-19T02:41+00:00" }))
      .toBe(`Nothing sent yet; the first report goes 2026-10-19T02:41+00:00 UTC. Reports go to ${relay}.`);
  });
  it("says errors are included in the choice, and what waits", () => {
    expect(CHOICES[0]?.[1]).toMatch(/error reports/);
    expect(errorsLine(base)).toBe("Error reports follow your choice: none is kept or sent.");
    const on = { ...base, answered: true, mode: "basic" as const, why: "config" as const, sending: true, why_not: null };
    expect(errorsLine({ ...on, errors: { waiting: 2, sent: 0, last_sent: null } })).toBe("2 waiting; they go within minutes of an error. None sent yet.");
    const last = { id: "2026-10-23T180501", at: "2026-10-23T18:05:01+00:00", status: 204, bytes: 900, gzip_bytes: 400, endpoint: "x", tier: "basic", reports: 1 };
    expect(errorsLine({ ...on, errors: { waiting: 0, sent: 1, last_sent: last } })).toMatch(/Last batch 2026-10-23T18:05:01\+00:00: 1 report, HTTP 204\.$/);
    expect(errorsLine(on)).toBe("Error reports go within minutes of an error.");
  });
  it("opens a pane for every row the Privacy list draws", () => {
    const keys = [...listSrc.matchAll(/<SetRow key="([a-z-]+)"/g)].map((m) => m[1]);
    const ids = /\[([^\]]*)\]\.includes\(id\)/.exec(paneSrc)?.[1] || "";
    expect(keys).toContain("errors");
    for (const k of keys) expect(ids).toContain(`"${k}"`);
  });
  it("lists a report's fields sorted", () => {
    expect(fieldRows({ b: 2, a: true })).toEqual([["a", "true"], ["b", "2"]]);
    expect(fieldRows(null)).toEqual([]);
  });
});
