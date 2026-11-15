import { afterEach, describe, expect, it } from "vitest";
import type { Facts } from "../../lib/app";
import type { Where } from "../../lib/pages.svelte";
import { ui } from "../../lib/shell.svelte";
import { termUi } from "../../term/state.svelte";
import { answering, draw, settle, stub, where } from "../testing.svelte";
import SourcesPane from "./SourcesPane.svelte";
import { APPROVE_API, batchApi, DESCRIBE, FROMTEXT_API, preticked, type FromTextBatch, type FromTextLine } from "./describe.svelte";
import type { SourceRow } from "../../api/afk.gen";
import { CATALOG_API, FORM, type Catalog } from "./sources.svelte";

// the server's /api/catalog and /api/sources/from-text (generated from its web/types.py)
const CAT: Catalog = {
  providers: [{ key: "web", name: "Any website", presets: [{ key: "web.feed", provider: "web", provider_name: "Any website", name: "RSS or Atom feed", blurb: "Any feed URL.", access: "public",
    needs: null, available: true, reason: null, retention_days: null, fields: [{ key: "url", label: "Feed URL", hint: "", placeholder: "https://example.org/feed.xml" }] }] }],
  connected: {}, topics: [{ id: 3, name: "Rust", description: "", kind: "user", ref: null, sources: 2 }], prefilter: 0.3,
};
const row = (id: number, o: Partial<SourceRow> = {}): SourceRow => ({
  proposed_topic: 3, role: "core", pretick: false,
  id, kind: "rss", label: `Source ${id}`, origin: "manual", review: "proposed", group: "proposed", status: "proposed", detail: "", site: "web", site_name: "example.org",
  preset: "web.feed", fields: { url: `https://ex.org/${id}` }, topics: [], proposed_for: null, found_for: null, why: null, replaces: null, validation: { items: 30, recent: 9, from: "a line" },
  items_7d: 0, items_per_day: null, kept_30d: 0, judged_30d: 0, kept_rate: null, yield_per_day: 0, mute: null, last_fetch: null, last_error: null, retry_at: null,
  failing_runs: 0, backoff_until: null, needs_fixing: false, connection: null, retention_days: null, note: null, spend: null, grades: null, removal: null, ...o,
});
const line = (status: FromTextLine["status"], from: string, o: Partial<FromTextLine> = {}): FromTextLine =>
  ({ status, from, preset: null, fields: {}, why: null, cost: null, source_id: null, label: null, row: null, ...o });
const BATCH: FromTextBatch = {
  id: "fromtext:7", call_id: 7, topic: 3, stopped_at: null, read: 120, total: 120,
  counts: { valid: 2, unverified: 1, invalid: 1, not_found: 1, refused: 1, connect_first: 1, already_proposed: 1, already_watching: 1 },
  message: "Resolved 9 lines: 3 ready to approve, 1 could not be fetched, 2 not found or not offered, 1 need an account connected, 2 already proposed or watched.",
  lines: [
    line("valid", "This Week in Rust", { source_id: 11, label: "this-week-in-rust.org", preset: "web.site", row: row(11) }),
    line("invalid", "Jepsen", { source_id: 12, label: "jepsen.io", preset: "web.site", fields: { site: "https://jepsen.io/" }, why: "no feed found at https://jepsen.io/", row: row(12, { review: "invalid" }) }),
    line("unverified", "Murat's blog", { source_id: 13, label: "muratbuffalo.blogspot.com", preset: "web.feed", fields: { url: "https://m.example/feed" }, why: "HTTP 429", row: row(13) }),
    line("not_found", "my LinkedIn feed", { why: "LinkedIn is not offered" }),
    line("refused", "reddit.com/r/rust", { preset: "web.feed", fields: { url: "https://reddit.com/r/rust/.rss" }, why: "Kranto does not add Reddit" }),
    line("connect_first", "@karpathy on X", { preset: "x.profile", fields: { handle: "@karpathy" }, why: "connect X / Twitter first" }),
    line("valid", "Fly.io's blog", { source_id: 14, label: "fly.io", preset: "web.site", row: row(14) }),
    line("already_proposed", "this week in rust again", { source_id: 11, label: "this-week-in-rust.org", why: "named twice" }),
    line("already_watching", "HN front page", { source_id: 2, label: "HN front page", why: "already watched" }),
  ],
};
const stubL = (o: Parameters<typeof stub>[0] = {}) => stub(o);
const hosted = () => { ui.facts = { header: { host: { paused: false } } } as unknown as Facts; };
const at = (q: Record<string, string> = {}, sel: string | null = null): Where => ({ ...where("settings", sel), r: { path: ["settings", "sources", "new"], q, sel } });
afterEach(() => {
  ui.facts = null; FORM.f = null; termUi.enabled = false; termUi.subject = null;
  Object.assign(DESCRIBE, { text: "", topic: "", batch: null, ticked: [], waiting: null, error: null });
  history.replaceState(null, "", "#/");
});

describe("Add source › Describe what to add", () => {
  it("posts the text and the topic, says it is resolving, and opens the batch with its ready lines ticked", async () => {
    const L = stubL();
    let finish: (v: unknown) => void = () => {};
    L.api.mockImplementation((path: string) => path === FROMTEXT_API ? new Promise((res) => (finish = res)) : Promise.resolve({}));
    hosted();
    answering({ [CATALOG_API]: CAT });
    const { target, done } = await draw(SourcesPane, at({ topic: "3" }));
    expect(target.querySelector(".dt")?.textContent).toBe("Add source");
    expect(target.querySelector("#s-describe h3")?.textContent).toBe("Describe what to add");
    expect((target.querySelector("#d-topic") as HTMLSelectElement).value).toBe("3");
    expect((target.querySelector("#resolve") as HTMLButtonElement).disabled).toBe(true);
    const box = target.querySelector("#d-text") as HTMLTextAreaElement;
    box.value = "This Week in Rust\n\nJepsen\n";
    box.dispatchEvent(new Event("input", { bubbles: true }));
    await settle();
    (target.querySelector("#resolve") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith(FROMTEXT_API, { text: "This Week in Rust\n\nJepsen", topic: 3 });
    expect(target.querySelector("#s-describe .inline .muted")?.textContent).toMatch(/^Resolving 2 lines… each source is fetched before you see it/);
    expect((target.querySelector("#d-text") as HTMLTextAreaElement).disabled).toBe(true);
    finish({ job: { key: "fromtext", state: "done", started: 0, finished: 1, elapsed_s: 1, result: BATCH, error: null } });
    await settle();
    expect(location.hash).toBe("#/settings/sources/new?topic=3&batch=7");
    expect(L.say).toHaveBeenCalledWith(BATCH.message);
    expect(DESCRIBE.ticked).toEqual([11, 14]);
    expect(DESCRIBE.text).toBe("");
    done();
  });

  it("keeps the text when resolving fails, and says why", async () => {
    const L = stubL();
    L.api.mockImplementation(async () => ({ job: { key: "fromtext", state: "failed", elapsed_s: 3, result: null, error: "the reply named no sources" } }));
    L.act.mockImplementation(async (_b: unknown, fn: () => Promise<unknown>, ok?: (r: unknown) => void) => { try { ok?.(await fn()); } catch { /* the app says it */ } });
    hosted();
    answering({ [CATALOG_API]: CAT });
    DESCRIBE.text = "something vague";
    const { target, done } = await draw(SourcesPane, at());
    (target.querySelector("#resolve") as HTMLButtonElement).click();
    await settle();
    expect(DESCRIBE.text).toBe("something vague");
    expect(target.querySelector("#s-describe .note.c-red")?.textContent).toBe("Resolving failed: the reply named no sources Your text is kept; click Resolve again.");
    done();
  });

  it("draws the batch as five sections in the issue's order, the fetched ones ticked", async () => {
    stubL();
    hosted();
    answering({ [CATALOG_API]: CAT });
    Object.assign(DESCRIBE, { batch: BATCH, ticked: [11, 14] });
    const { target, done } = await draw(SourcesPane, at({ topic: "3", batch: "7" }));
    expect(target.querySelector(".dt")?.textContent).toBe("Described sources for Rust");
    expect(target.querySelector(".lede")?.textContent).toBe(BATCH.message);
    expect([...target.querySelectorAll(".sec h3")].map((h) => h.textContent)).toEqual(["Ready to approve3", "Could not be fetched1", "Not found or not offered2", "Needs an account1", "Already watching or proposed2"]);
    const ready = [...target.querySelectorAll("#s-ready li.row")];
    expect(ready.map((r) => r.querySelector(".r-title")?.textContent)).toEqual(["this-week-in-rust.org", "muratbuffalo.blogspot.com", "fly.io"]);
    expect(ready.map((r) => (r.querySelector(".ptick") as HTMLInputElement).checked)).toEqual([true, false, true]);
    expect(ready[0]!.querySelector(".c-meta")?.textContent).toBe("from «This Week in Rust» · example.org · 30 items, 9 in 30 days");
    expect(ready[1]!.querySelector(".c-meta")?.textContent).toContain("ticking it watches it anyway");
    expect(ready[0]!.querySelector("a.r-title")?.getAttribute("href")).toBe("#/settings/sources/new?sel=ereview:11");
    expect(target.querySelector("#s-failed .ptick")).toBeNull();
    expect(target.querySelector("#s-failed .c-meta")?.textContent).toBe("from «Jepsen» · no feed found at https://jepsen.io/ · example.org");
    expect([...target.querySelectorAll("#s-notfound .r-title")].map((x) => x.textContent)).toEqual(["my LinkedIn feed", "reddit.com/r/rust"]);
    expect(target.querySelector("#s-notfound .ptick")).toBeNull();
    expect(target.querySelector("#s-account .r-act a")?.getAttribute("href")).toBe("#/settings/connections/x");
    expect([...target.querySelectorAll("#s-already .ptick")].map((x) => (x as HTMLInputElement).checked)).toEqual([true, false]);
    expect(target.querySelector(".dh .acts .muted")?.textContent).toBe("2 ticked · about 0.6 items a day before filtering");
    done();
  });

  it("Approve the ticked posts exactly the ticked ids, in one request, and nothing when none is ticked", async () => {
    const L = stubL({ answer: { approved: [11, 13], skipped: [] } });
    hosted();
    answering({ [CATALOG_API]: CAT });
    Object.assign(DESCRIBE, { batch: BATCH, ticked: [11, 14] });
    const { target, done } = await draw(SourcesPane, at({ topic: "3", batch: "7" }));
    const boxes = [...target.querySelectorAll("#s-ready .ptick")] as HTMLInputElement[];
    boxes[1]!.click();             // Murat's (not fetched now): ticked by hand
    boxes[2]!.click();             // Fly.io's: unticked (the wrong one)
    await settle();
    (target.querySelector("#approve-ticked") as HTMLButtonElement).click();
    await settle();
    expect(L.api.mock.calls.filter((c) => c[0] === APPROVE_API)).toEqual([[APPROVE_API, { ids: [11, 13], topic: 3 }]]);
    expect(location.hash).toBe("#/topics/3/sources");
    expect(L.toast).toHaveBeenCalledWith("Watching 2 sources for Rust. Their first fetch is the next ingest run.");
    done();
    const M = stubL();
    hosted();
    Object.assign(DESCRIBE, { batch: BATCH, ticked: [] });
    const none = await draw(SourcesPane, at({ topic: "3", batch: "7" }));
    const btn = none.target.querySelector("#approve-ticked") as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    btn.click();
    await settle();
    expect(M.api).not.toHaveBeenCalled();
    none.done();
  });

  it("Try as opens the catalog's form for the kind tried, with its fields, to correct one", async () => {
    stubL();
    hosted();
    answering({ [CATALOG_API]: CAT });
    Object.assign(DESCRIBE, { batch: BATCH, ticked: [] });
    const { target, done } = await draw(SourcesPane, at({ topic: "3", batch: "7" }));
    const tries = [...target.querySelectorAll(".r-act a")].filter((a) => a.textContent === "Try as") as HTMLAnchorElement[];
    expect(tries.length).toBe(2);                     // the one that failed, the one not fetched now
    const murat = tries.find((a) => a.closest("#s-ready"))!;
    expect(murat.getAttribute("href")).toBe("#/settings/sources/new?topic=3&sel=epreset%3Aweb.feed");
    expect(FORM.f).toBeNull();
    murat.click();
    expect(FORM.f).toEqual({ key: "preset:web.feed", fields: { url: "https://m.example/feed" }, topic: "3", preview: null, error: null });
    done();
    stubL();
    hosted();
    answering({ [CATALOG_API]: CAT });
    const pane = await draw(SourcesPane, at({ topic: "3" }, "epreset:web.feed"));
    expect((pane.target.querySelector("#f-url") as HTMLInputElement).value).toBe("https://m.example/feed");
    pane.done();
  });

  it("says what an X line costs before it is approved, and never ticks one for you", async () => {
    stubL();
    hosted();
    answering({ [CATALOG_API]: CAT });
    const x = line("valid", "@gridbuilder on X", { source_id: 21, label: "X: @gridbuilder", preset: "x.profile", row: row(21, { site_name: "X / Twitter" }),
      cost: { check: 0.05, run: 0.05, month: 12 } });
    const home = line("unverified", "my X timeline", { source_id: 22, label: "Your X home timeline", preset: "x.home", why: "not fetched before you approve it: X bills every read",
      row: row(22, { site_name: "X / Twitter" }), cost: { check: 0, run: 0.1, month: 24 } });
    const b = { ...BATCH, lines: [x, home] };
    Object.assign(DESCRIBE, { batch: b, ticked: [] });
    const { target, done } = await draw(SourcesPane, at({ topic: "3", batch: "7" }));
    const metas = [...target.querySelectorAll("#s-ready .c-meta")].map((m) => m.textContent);
    expect(metas[0]).toContain("X bills about $0.05 a run, up to about $12.00 a month; the check read 10 posts ($0.05)");
    expect(metas[1]).toContain("X bills about $0.10 a run, up to about $24.00 a month; not read before you approve it");
    expect(preticked(b)).toEqual([]);
    expect(preticked(BATCH)).toEqual([11, 14]);
    done();
  });

  it("offers Find these with Claude Code only where the terminal is on, and shows what its session sent back", async () => {
    stubL();
    hosted();
    answering({ [CATALOG_API]: CAT });
    Object.assign(DESCRIBE, { batch: BATCH, ticked: [11, 14] });
    const off = await draw(SourcesPane, at({ topic: "3", batch: "7" }));
    expect(off.target.querySelector("#find-with-claude")).toBeNull();
    expect(off.target.querySelector("#s-failed p.muted")?.textContent).toBe("Open in Claude Code is not available here: correct the fields by hand with Try as.");
    off.done();
    termUi.enabled = true;
    const sent: FromTextBatch = { ...BATCH, id: "fromtext:8", call_id: 8, lines: [line("valid", "Jepsen", { source_id: 15, label: "jepsen.io", preset: "web.feed", row: row(15) })] };
    stubL();
    hosted();
    answering({ [CATALOG_API]: CAT, "api/term": { sessions: [{ tid: "t1", subject: { kind: "sources", id: "7" }, batches: [8] }, { tid: "t2", subject: { kind: "idea", id: "7" }, batches: [9] }] },
      [batchApi(8)]: { job: { key: "fromtext:8", state: "done", started: 0, finished: 1, elapsed_s: 0, result: sent, error: null } } });
    const on = await draw(SourcesPane, at({ topic: "3", batch: "7" }));
    await settle();
    const btn = on.target.querySelector("#find-with-claude") as HTMLButtonElement;
    expect(btn.closest("#s-failed")).not.toBeNull();                 // once, under the first such section
    expect(on.target.querySelectorAll("#find-with-claude").length).toBe(1);
    btn.click();
    expect(termUi.subject).toEqual({ kind: "sources", id: "7" });
    expect(termUi.title).toBe("Find feeds for 3 lines");
    expect(on.target.querySelector("#s-found h3")?.textContent).toBe("Found by Claude Code1");
    expect(on.target.querySelector("#s-found .r-title")?.textContent).toBe("jepsen.io");
    expect(DESCRIBE.ticked).toEqual([11, 14, 15]);
    on.done();
  });

  it("says what Find these runs on, and shows the Claude API's refusal under the button", async () => {
    termUi.enabled = true;
    stubL();
    hosted();
    answering({ [CATALOG_API]: CAT, "api/term": { sources_on: "on your Claude API key (the watcher's), Sonnet 5",
      sessions: [{ tid: "t1", subject: { kind: "sources", id: "7" }, state: "ended", batches: [], refused: "Credit balance is too low" }] } });
    Object.assign(DESCRIBE, { batch: BATCH, ticked: [11, 14] });
    const d = await draw(SourcesPane, at({ topic: "3", batch: "7" }));
    await settle();
    const btn = d.target.querySelector("#find-with-claude") as HTMLButtonElement;
    expect(btn.nextElementSibling?.textContent).toMatch(/^On your Claude API key \(the watcher's\), Sonnet 5\. It looks the feeds up/);
    expect(d.target.querySelector("#find-refused")?.textContent).toBe("The Claude API refused the session's last request: Credit balance is too low");
    d.done();
  });

  it("opens a batch again by its address, and a described proposal's review says the line it came from", async () => {
    stubL();
    hosted();
    answering({ [CATALOG_API]: CAT, [batchApi(7)]: { job: { key: "fromtext:7", state: "done", started: 0, finished: 1, elapsed_s: 0, result: BATCH, error: null } },
      "/api/sources": { sources: [row(12, { review: "proposed", why: "the blog's own feed", validation: { items: 3, recent: 1, from: "Jepsen" } })], topics: [], reddit: { watched: 0, note: "" },
        connections_need_you: 0, every_hours: 3, default_retention_days: 90 } });
    const again = await draw(SourcesPane, at({ batch: "7" }));
    expect(again.target.querySelector(".dt")?.textContent).toBe("Described sources for Rust");
    expect(DESCRIBE.ticked).toEqual([11, 14]);
    again.done();
    const review = await draw(SourcesPane, at({}, "ereview:12"));
    expect(review.target.querySelector(".lede")?.textContent).toBe("the blog's own feed From your list: «Jepsen»");
    expect(review.target.querySelector("#s-preview h3")?.textContent).toBe("The test fetch");
    review.done();
  });
});
