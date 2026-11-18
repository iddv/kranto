// Feedback: the details the sheet adds and their scrub, the issue, GitHub's prefilled link and
// its length, the draft, and an error's Tell us.
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  DRAFT_KEY, MAX_URL, browserOf, clearDraft, details, fitted, forgetErrors, issue, issueUrl, loadDraft, noteError, osOf,
  routePattern, saveDraft, scrub, scrubDetail, seenErrors, titleOf, withError, type Facts, type Machine, type Names,
} from "./feedback";

// the four things the details must never carry, each made here (no secret-shaped literal in the repo)
const TOPIC = "Clinic schedules";
const TITLE = "Beliefline for paper rotas";
const TOKEN = "gh" + "p_" + "Q1w2E3r4T5y6U7i8O9p0".repeat(2);
const HOME = "/home/someone/kranto-loop/tasks/beliefline";
const M: Machine = { places: [["/home/someone/kranto-loop", "<loop>"], ["/home/someone", "<home>"]], host: "example-host", login: "someone" };
const N: Names = { topics: [TOPIC, "AI"], titles: [TITLE, "beliefline"] };
const FF = "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0";
const facts = (o: Partial<Facts> = {}): Facts => ({
  version: "0.5.10 (stable)", layout: "New", hash: "#/topics/7/ideas", ua: FF,
  update: { checked_at: "2026-10-22T11:09:00Z", ok: false, error: `fetch failed for ${TOPIC} at ${HOME}/x.log with ${TOKEN}` },
  errors: [{ at: Date.parse("2026-10-22T19:02:00Z"), text: `Could not run "${TITLE}": ${TOKEN} in ${HOME} for topic ${TOPIC}` }], ...o,
});

afterEach(() => {
  forgetErrors();
  clearDraft();
});

describe("the details Include details adds", () => {
  it("say the version, the layout, the route's pattern, the browser, the OS, the update check and the errors", () => {
    const d = details(facts(), M, N);
    expect(d).toContain("- Kranto: 0.5.10 (stable)");
    expect(d).toContain("- layout: New");
    expect(d).toContain("- page: `#/topics/:id/ideas`");
    expect(d).toContain("- browser: Firefox 131 on Linux");
    expect(d).toContain("- updates: last checked 2026-10-22 11:09 UTC: failed: fetch failed for [topic]");
    expect(d).toContain("  - 19:02 UTC: Could not run […]");
  });

  it("never carry a topic name, an item title, a token's shape or a home path", () => {
    for (const f of [facts(), facts({ hash: `#/sessions/beliefline-3f2/trace?sel=icard:3&q=${encodeURIComponent(TITLE)}` })]) {
      const d = details(f, M, N);
      for (const bad of [TOPIC, TITLE, TOKEN, HOME, "/home/someone", "beliefline", "someone", "example-host", "icard:3"]) expect(d, bad).not.toContain(bad);
      expect(d).not.toMatch(/gh[pousr]_/);
    }
    // and the whole issue, built from them, neither
    const x = issue({ kind: "bug", text: "the brief's Run now did nothing", include: true }, facts(), M, N);
    for (const bad of [TOPIC, TITLE, TOKEN, HOME]) expect(x.body, bad).not.toContain(bad);
  });

  it("reduce an address to its route's pattern: the query's keys, no id, no value", () => {
    expect(routePattern("#/topics/7/ideas")).toBe("#/topics/:id/ideas");
    expect(routePattern("#/ideas?topic=2&sel=icard:3")).toBe("#/ideas?sel=…&topic=…");
    expect(routePattern("#/sessions/beliefline-3f2/trace")).toBe("#/sessions/:tid/trace");
    expect(routePattern("#/")).toBe("#/");
    expect(routePattern("#/no-such-page/secret-name")).toBe("#/no-such-page/…");
    expect(routePattern("#/Clinic%20schedules")).toBe("#/…");
    expect(scrubDetail("opened #/topics/7/sources?sel=s12 then failed", M, N)).toBe("opened #/topics/:id/sources?sel=… then failed");
  });

  it("name the browser and the OS family only", () => {
    expect([browserOf(FF), osOf(FF)]).toEqual(["Firefox 131", "Linux"]);
    const chrome = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36";
    expect([browserOf(chrome), osOf(chrome)]).toEqual(["Chrome 142", "macOS"]);
    const safari = "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Mobile/15E148 Safari/604.1";
    expect([browserOf(safari), osOf(safari)]).toEqual(["Safari 26", "iOS"]);
    const edge = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36 Edg/142.0.0.0";
    expect([browserOf(edge), osOf(edge)]).toEqual(["Edge 142", "Windows"]);
  });

  it("keep the last five errors the page said", () => {
    for (let i = 1; i <= 7; i++) noteError("error " + i, i);
    expect(seenErrors().map((e) => e.text)).toEqual(["error 3", "error 4", "error 5", "error 6", "error 7"]);
    const d = details(facts({ errors: [], update: null }), M, N);
    expect(d).toContain("- recent errors on this page: none");
    expect(d).toContain("- updates: not known here");
  });
});

describe("the scrub (Kranto's telemetry's and Report to Kranto's)", () => {
  it("takes out tokens, e-mail, phone numbers, handles, paths, the host and the login", () => {
    const out = scrub(`${TOKEN} me@example.com +31 612 345 678 @someone ${HOME} C:\\Users\\Someone\\x example-host someone/fork`, M);
    expect(out).toBe("[secret] [email] [phone] [user] <loop>/tasks/beliefline <home>\\x <host> <you>/fork");
  });
  it("leaves the person's own words be, but for secrets and paths", () => {
    expect(scrub(`The ${TOPIC} topic's Run now did nothing`, M)).toBe(`The ${TOPIC} topic's Run now did nothing`);
  });
});

describe("the issue", () => {
  it("is titled by its kind and first line, says its kind, and adds the details only when asked", () => {
    expect(titleOf("bug", "the brief's Run now did nothing\nmore", M)).toBe("Bug: the brief's Run now did nothing");
    expect(titleOf("idea", "x".repeat(200), M).length).toBeLessThanOrEqual(87);
    const on = issue({ kind: "bug", text: "the brief's Run now did nothing", include: true }, facts(), M, N);
    expect(on.labels).toEqual(["feedback", "bug"]);
    expect(on.body).toContain("the brief's Run now did nothing\n\n**Kind:** Bug · sent with Feedback in Kranto\n\n### Details Kranto added");
    expect(on.body).toContain(on.details);
    const off = issue({ kind: "question", text: "how do I pause?", include: false }, facts(), M, N);
    expect(off.details).toBe("");
    expect(off.body).not.toContain("Details Kranto added");
  });

  it("carries an error's report (Send this error) as shown, details or not, scrubbed once more", () => {
    const report = "Error 1a2b3c4d: TypeError in list:source\n\n### Error Kranto caught\n- error id: `1a2b3c4d`\n```\nkranto.source_health._status:209\n```\n" + ` and ${HOME}`;
    const d = { kind: "bug" as const, text: "Couldn't read this source (error 1a2b3c4d)", include: false };
    const x = issue(d, facts(), M, N, 0, report);
    expect(x.body).toContain("**Kind:** Bug · sent with Feedback in Kranto\n\nError 1a2b3c4d: TypeError in list:source");
    expect(x.body).toContain("kranto.source_health._status:209");
    expect(x.body).not.toContain(HOME);
    expect(fitted(d, facts(), M, N, "iddv/kranto", MAX_URL, report).url).toContain(encodeURIComponent("kranto.source_health._status:209"));
  });
});

describe("GitHub's prefilled link (Open on GitHub)", () => {
  const d = { kind: "bug" as const, text: "the brief's Run now did nothing", include: true };
  it("is GitHub's new-issue page for the repository, with the title, the body and the labels", () => {
    const f = fitted(d, facts(), M, N, "iddv/kranto");
    const u = new URL(f.url);
    expect(u.origin + u.pathname).toBe("https://github.com/iddv/kranto/issues/new");
    expect(u.searchParams.get("title")).toBe("Bug: the brief's Run now did nothing");
    expect(u.searchParams.get("body")).toBe(f.issue.body);
    expect(u.searchParams.get("labels")).toBe("feedback,bug");
    expect(u.searchParams.get("template")).toBe("feedback.yml");
    expect(f.trimmed).toBeNull();
    expect(issueUrl("someone/fork", "t", "b", ["feedback", "idea"])).toBe("https://github.com/someone/fork/issues/new?template=feedback.yml&title=t&body=b&labels=feedback%2Cidea");
  });
  it("stays under GitHub's length: the oldest errors go first, and it says so", () => {
    const errors = Array.from({ length: 5 }, (_, i) => ({ at: i * 60000, text: `error ${i} ` + "words ".repeat(160) }));
    const f = fitted(d, facts({ errors }), M, N, "iddv/kranto");
    expect(f.url.length).toBeLessThanOrEqual(MAX_URL);
    expect(f.trimmed).toMatch(/oldest errors were left out/);
    expect(f.issue.body).toMatch(/\(trimmed to fit GitHub's link: the \d oldest errors left out\)/);
    expect(f.issue.body).toContain("error 4");
    expect(f.issue.body).not.toContain("error 0");
  });
  it("cuts the person's words last, saying where the rest is", () => {
    const f = fitted({ ...d, text: "a long story ".repeat(800) }, facts(), M, N, "iddv/kranto");
    expect(f.url.length).toBeLessThanOrEqual(MAX_URL);
    expect(f.issue.body).toContain("(the rest did not fit GitHub's link: paste it here)");
    expect(f.trimmed).toMatch(/your words were cut/);
    expect(f.issue.title).toBe("Bug: a long story a long story a long story a long story a long story a long story…");
  });
});

describe("the draft", () => {
  beforeEach(() => localStorage.clear());
  it("is kept in this browser while the sheet is closed, and cleared", () => {
    expect(loadDraft()).toEqual({ kind: "bug", text: "", include: true });
    saveDraft({ kind: "idea", text: "more themes", include: false });
    expect(JSON.parse(localStorage.getItem(DRAFT_KEY)!)).toEqual({ kind: "idea", text: "more themes", include: false });
    expect(loadDraft()).toEqual({ kind: "idea", text: "more themes", include: false });
    clearDraft();
    expect(loadDraft().text).toBe("");
    saveDraft({ kind: "bug", text: "", include: true });
    expect(localStorage.getItem(DRAFT_KEY)).toBeNull();
  });
  it("says an error's words when Tell us opens it, scrubbed, after what was written", () => {
    const d = withError({ kind: "idea", text: "first thought", include: true }, `Not graded: "${TITLE}" is gone (${HOME})`, M, N);
    expect(d.kind).toBe("bug");
    expect(d.text).toBe("first thought\n\nSomething went wrong: Not graded: […] is gone (<loop>/tasks/[title])\n\nWhat I was doing: ");
    expect(withError(d, `Not graded: "${TITLE}" is gone (${HOME})`, M, N)).toBe(d);
  });
});
