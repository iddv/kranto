import { flushSync, mount, unmount } from "svelte";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { Facts } from "../../lib/app";
import { ui } from "../../lib/shell.svelte";
import { answering, draw, settle, stub, where } from "../../pages/testing.svelte";
import DialogHost from "../../ui/DialogHost.svelte";
import { closeDialog, dlg } from "../../ui/dialog.svelte";
import Card from "../../ui/Card.svelte";
import { FEATURES_API, featurePath, type FeatureRow, type Features } from "../index";
import { SHELL_API } from "../shell";
import { at, citesOf, CUBS_API, cubPath, groupsOf, modeWords, permissionWords, subjectField, ticketOf } from "../cub";
import CubPage from "./CubPage.svelte";
import CubPane from "./CubPane.svelte";
import CubObjectPage from "./CubObjectPage.svelte";
import AskDialog from "./AskDialog.svelte";

const NOW = new Date().toISOString();
afterEach(() => { ui.facts = null; dlg.now = null; ui.headOn = false; ui.head = null; });
/** the page's head as the shell draws it: its declaration */
const headOf = () => ui.head!;
const hosted = () => { ui.facts = { header: { host: { paused: false } } } as unknown as Facts; };

const proposalCard = { title: "thesis.instrument_name", lines: ["thesis.counter_case", "thesis.catalyst"],
  fields: [{ key: "quote.ask", label: "Price", kind: "money" }, { key: "mode", label: "Mode", kind: "text" }],
  actions: ["digest.dismiss", "digest.refresh"], origin: "cites" };
const digest = (o: Partial<FeatureRow> = {}): FeatureRow => ({
  id: "digest", title: "Digest", says: "Proposals from the news, in practice.", version: "1.0.0", trust: "first-party",
  enabled: true, mode: "practice", tickets_open: 1, last_run: { kind: "digest.scan", status: "ok", finished_at: NOW },
  spend: { month_usd: 0, today_usd: 0, calls: 3 },
  settings: [
    { key: "digest.enabled", value: true, type: "bool", default: false, choices: [], lo: null, hi: null, words: "Digest (practice)", sensitive: true, by_hand: false, per_topic: false },
    { key: "digest.max_proposals_day", value: 3, type: "int", default: 3, choices: [], lo: 1, hi: 10, words: "proposals a day at most", sensitive: false, by_hand: false, per_topic: false },
    { key: "digest.live.enabled", value: false, type: "bool", default: false, choices: [], lo: null, hi: null, words: "live trading may be switched on", sensitive: false, by_hand: true, per_topic: false },
  ],
  manifest: {
    reads: ["topics", "briefs"], requests: ["book.place"],
    actions: [
      { kind: "digest.stop", title: "Stop", doors: ["ui", "cli"], click: "click", subjects: [], says: "halts Digest", fields: [], place: "head" },
      { kind: "digest.dismiss", title: "Dismiss", doors: ["ui", "cli"], click: "click", subjects: ["digest_proposal"], says: "",
        fields: [{ key: "reasons", label: "Why", kind: "choice", choices: ["weak_evidence", "not_for_me"], read: null, hint: "", required: false }], place: "card" },
      { kind: "digest.refresh", title: "Refresh the price", doors: ["ui"], click: "click", subjects: ["digest_proposal"], says: "", fields: [], place: "card" },
    ],
    ui: { nav: [], cards: { proposal: proposalCard }, kind: "watch", glyph: "up",
      lists: [{ id: "proposals", word: "Proposals", read: "proposals", card: "proposal", groups: [{ key: "open", word: "Proposed" }, { key: "history", word: "Decided" }], count: "open" }] },
  },
  ...o,
});
const proposal = { id: 7, state: "proposed", mode: "practice", thesis: { instrument_name: "Acme Robotics", counter_case: "It is small.", catalyst: "A contract." },
  quote: { ask: 50.05 }, cites: [{ label: "obs 5", kind: "obs", id: 5, title: "Contract", url: "https://ex.com/a", date: "2026-10-18" }],
  ticket: { id: 41, state: "needs_confirm" } };
const FEATURES = (f: FeatureRow): Features => ({ api: "kranto-mod/1", reads: [], request_kinds: ["book.place", "post.mastodon"], features: [f],
  request_schemas: { "book.place": { title: "Book this table", doors: ["ui"], page_only: true, performs: true, expires_hours: 24, per_day: 10, fields: [] },
                     "post.mastodon": { title: "Publish this post", doors: ["ui"], page_only: true, performs: false, expires_hours: 48, per_day: 5, fields: [] } } });
const shell = { home: true, pins: ["digest"], hidden: [], needs_cap: 3, new_cap: 4, pins_max: 6, cubs: [{ id: "digest", trust: "first-party", pinned: true, place: 0, hidden: false, needs_you: true, new: true }] };

function cubWhere(sel: string | null = null, q: Record<string, string> = {}) {
  const w = where("cub/digest", sel);
  return { ...w, node: "cub", id: "digest", stage: true, object: null, obj: null, sel: false, r: { path: ["cub", "digest"], q, sel } };
}

describe("a cub's page, drawn from its manifest", () => {
  it("draws the head, the facts, the flash, the list's groups and the ask's button on one that waits", async () => {
    stub();
    hosted();
    answering({ [FEATURES_API]: FEATURES(digest()), [SHELL_API]: shell, [featurePath("digest", "proposals")]: { open: [proposal], history: [], today: [] } });
    ui.headOn = true;
    const { target, done } = await draw(CubPage, cubWhere());
    await settle();
    const h = headOf();
    expect(h.crumb!.map((c) => c.w)).toEqual(["Cubs", "Digest"]);               // Home › Cubs › Digest, no "cub" tag
    expect(h.stop?.label).toBe("Stop");
    expect(h.trust).toMatchObject({ w: "built-in" });
    expect(h.tags!.map((t) => t.w)).toEqual(["practice"]);
    expect(h.facts).toContain("3 model calls this month");
    expect(h.facts).not.toContain("$");
    expect(h.flash?.text).toContain("Practice: approving what it asks sends nothing");
    expect(h.flash?.link?.href).toBe("#/settings/digest");
    expect(h.gear).toBe("settings/digest");
    expect(h.sub!.map((x) => x.w + (x.n ?? ""))).toEqual(["Proposals1", "Log"]);
    expect(target.querySelector(".lh")).toBeNull();                              // never a head of its own
    expect(target.querySelector(".r-title")?.textContent).toBe("Acme Robotics");
    expect(target.querySelector('[data-act="ask-open"]')?.textContent).toBe("Approve");
    (target.querySelector('[data-act="ask-open"]') as HTMLButtonElement).click();
    expect(dlg.now?.comp).toBe(AskDialog);
    expect((dlg.now?.props as { id: number }).id).toBe(41);
    done();
  });

  it("opens an object in the sheet with its card, the origin fence and its actions", async () => {
    const L = stub();
    hosted();
    answering({ [FEATURES_API]: FEATURES(digest()), [SHELL_API]: shell, [featurePath("digest", "proposals")]: { open: [proposal], history: [], today: [] } });
    const { target, done } = await draw(CubPane, cubWhere("v7"));                // the shell's one sheet
    await settle();
    expect(target.querySelector("#cub-sheet .card-t")?.textContent).toBe("Acme Robotics");
    expect(target.querySelector("#cub-sheet .fence a")?.getAttribute("href")).toBe("#/library/o/5");
    (target.querySelector('#cub-sheet [data-act="digest.refresh"]') as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/f/digest/act/refresh", { fields: { proposal_id: 7 }, confirm: undefined });
    done();
  });

  it("draws a markdown field as a box of several lines and sends its lines as typed", async () => {
    const L = stub();
    hosted();
    const md = { id: "md", word: "File it", submit: "digest.refresh", cost: "free", says: "",
      fields: [{ key: "markdown", label: "Markdown", kind: "markdown" as const, choices: [], read: null, hint: "", required: true }] };
    const f = digest();
    answering({ [FEATURES_API]: FEATURES({ ...f, manifest: { ...f.manifest, ui: { ...f.manifest.ui, forms: [md] } } } as FeatureRow),
      [SHELL_API]: shell, [featurePath("digest", "proposals")]: { open: [], history: [], today: [] } });
    const { target, done } = await draw(CubPane, cubWhere("form:md"));
    await settle();
    const box = target.querySelector("#ff-markdown") as HTMLTextAreaElement;
    expect(box.tagName).toBe("TEXTAREA");
    box.value = "# A title\n\n## Body\n\nTwo lines.";
    box.dispatchEvent(new Event("input", { bubbles: true }));
    ([...target.querySelectorAll("button.primary")].find((b) => b.textContent === "File it") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/f/digest/act/refresh", { fields: { markdown: "# A title\n\n## Body\n\nTwo lines." }, confirm: undefined });
    done();
  });

  // its Settings and About are its Settings page now: pages/settings/featurepage.svelte.test.ts
});

describe("the one dialog of what a cub asks (SEND)", () => {
  // the server's GET /api/tickets/88/ask for live's issue of 27 Oct: no account, in practice
  const view = (o: Record<string, unknown> = {}, ask: Record<string, unknown> = {}) => ({
    id: 88, cub: "newsletter", kind: "send.newsletter", state: "needs_confirm", said: null,
    readback: [["Draft", "draft:3, in Kranto"], ["Subject", "This week: Eka Robotics raises $150M"]], because: { briefs: [41] },
    history: [{ state: "needs_confirm", door: null, note: null, created_at: NOW }], created_at: NOW, expires_at: NOW, run_uuid: "u-1",
    ask: { question: "Send this issue?", verb: "Send now", button: "Send", noun: "issue", title: "This week: Eka Robotics raises $150M",
      to: null, body: "## Eka Robotics\n**$150M** Series A.\n\n" + "More. ".repeat(80), schedule: false, when: null, open: true, said: null, again: false, facts: [],
      needs: { connect: "newsletter", line: "needs a newsletter account", words: "No newsletter account is connected, so nothing can be sent yet.", button: "Connect a newsletter account" },
      practice: { on: true, words: "Practice: nothing is sent", switch: { cub: "newsletter", kind: "send.newsletter", words: "This issue and the ones after it go out when you approve them" } }, ...ask },
    ...o,
  });
  const PROVIDERS = { accounts: [], providers: [{ key: "resend", name: "Resend", state: "available", flow: "paste", steps: ["Make a Full access key."],
    fields: [{ key: "key", label: "API key", secret: true }, { key: "audience", label: "Audience" }, { key: "from", label: "From" }] }] };
  const NL = { platforms: [{ id: "resend", name: "Resend", about: "An email platform.", can_schedule: true }, { id: "buttondown", name: "Buttondown", about: "A newsletter service.", can_schedule: false }] };
  async function open(answers: (path: string, body?: unknown) => unknown) {
    const L = stub();
    L.api.mockImplementation(async (path: string, body?: unknown) => answers(path, body));
    const target = document.createElement("div");
    document.body.append(target);
    const c = mount(AskDialog, { target, props: { id: 88, close: () => {} } });
    await settle();
    flushSync();
    const q = (s: string) => target.querySelector(s);
    const text = () => (target.textContent || "").replace(/\s+/g, " ");
    const click = async (s: string) => { (q(s) as HTMLButtonElement).click(); await settle(); flushSync(); };
    return { L, target, q, text, click, done: () => { void unmount(c); target.remove(); } };
  }

  it("reads plainly: the question, the subject, the body drawn and collapsed, and what stops it fixed here", async () => {
    const d = await open(() => view());
    expect(d.q("#dlg-t")?.textContent).toBe("Send this issue?");
    expect(d.q(".pd-subject")?.textContent).toBe("This week: Eka Robotics raises $150M");
    expect(d.q(".pd-body .md-h")?.textContent).toBe("Eka Robotics");                  // drawn, not raw markdown
    expect(d.q(".pd-body")?.textContent).not.toContain("**");
    expect(d.q("#pd-all")?.textContent).toBe("Show all");
    expect(d.q("#ask-needs")?.textContent).toBe("No newsletter account is connected, so nothing can be sent yet.");
    expect(d.q("#dlg-ok")?.textContent).toBe("Connect a newsletter account");
    const send = [...d.target.querySelectorAll(".dlg-f button")].find((b) => b.textContent === "Send now") as HTMLButtonElement;
    expect(send.disabled).toBe(true);                                                  // Send waits, with why on it
    expect(d.q("#ask-practice")?.textContent).toBe("Practice: nothing is sent");
    expect((d.q("#ask-real") as HTMLInputElement).checked).toBe(false);
    // nothing of the old dialog: no refs, numbers, versions, because links, counts or policy
    for (const w of ["draft:3", "#88", "ticket", "dry", "because", "words,", "characters", "typed fields", "cub"]) expect(d.text().toLowerCase()).not.toContain(w);
    expect(d.q("#ask-facts")).toBeNull();
    await d.click("#ask-details");                                                   // the audit facts, behind Details
    expect(d.q("#ask-facts")?.textContent).toContain("draft:3, in Kranto");
    expect(d.q("#ask-facts a")?.getAttribute("href")).toBe("#/afk/u-1/trace");
    d.done();
  });

  it("connects an account in place and comes back to the same issue, ready", async () => {
    let connected = false;
    const d = await open((path, body) => {
      if (path === "/api/tickets/88/ask") return connected ? view({}, { needs: null, to: "312 subscribers on Resend", schedule: true }) : view();
      if (path === "/api/connections") return PROVIDERS;
      if (path === "/api/newsletter") return NL;
      if (path === "/api/connections/resend/credentials") {
        expect(body).toEqual({ key: "k", audience: "Newsletter", from: "Me <news@example.org>" });
        connected = true;
        return { message: "Resend is connected.", ok: true };
      }
      throw new Error("not asked: " + path);
    });
    await d.click("#dlg-ok");                                                        // Connect a newsletter account
    expect(d.text()).toContain("Choose the account your issues go out through");
    expect([...d.target.querySelectorAll(".ask-choose button")].map((b) => b.textContent)).toEqual(["Resend", "Buttondown"]);
    await d.click("#ask-pick-resend");
    expect(d.q(".pd-subject")?.textContent).toBe("Connect Resend");
    for (const [k, v] of [["key", "k"], ["audience", "Newsletter"], ["from", "Me <news@example.org>"]]) (d.q("#ask-f-" + k) as HTMLInputElement).value = v!;
    expect(d.q("#ask-f-key")?.getAttribute("type")).toBe("password");
    await d.click("#dlg-ok");                                                        // Save and test
    expect(d.q("#dlg-t")?.textContent).toBe("Send this issue?");                     // back to the same issue
    expect(d.q(".pd-keys")?.textContent).toBe("To312 subscribers on Resend");
    expect(d.q("#dlg-ok")?.textContent).toBe("Send now");
    expect(d.q("#ask-schedule")?.textContent).toBe("Schedule");
    expect(d.L.say).toHaveBeenCalledWith("Resend is connected.");
    d.done();
  });

  it("an approval in practice says nothing was sent, in the same place; never like a send", async () => {
    const d = await open((path) => (path.endsWith("/confirm") ? { state: "dry", outcome: { state: "dry", note: "practice: nothing was sent; the draft stays in Kranto" } } : view({}, { needs: null, to: "312 subscribers on Resend" })));
    await d.click("#dlg-ok");
    expect(d.L.api).toHaveBeenCalledWith("/api/tickets/88/confirm", { confirm: true });
    expect(d.q("#ask-result")?.textContent).toBe("Nothing was sent (practice).");
    expect(d.text()).not.toMatch(/\bSent\b/);
    expect(d.q("#dlg-ok")).toBeNull();
    expect(d.q(".dlg-f button")?.textContent).toBe("Close");
    d.done();
  });

  it("Send for real is the cub's own switch, turned by the owner's click here; Schedule sends a time", async () => {
    let live = false;
    const d = await open((path, body) => {
      if (path === "/api/cubs/newsletter/live") { expect(body).toEqual({ kind: "send.newsletter", confirm: true }); live = true; return {}; }
      if (path.endsWith("/confirm")) { expect(body).toEqual({ confirm: true, when: "2099-11-02T09:30Z" }); return { state: "done", note: "scheduled: b-1 for 2099-11-02T09:30Z (scheduled)" }; }
      return view({}, { needs: null, schedule: true, to: "312 subscribers on Resend", practice: { on: !live, words: live ? "" : "Practice: nothing is sent", switch: { cub: "newsletter", kind: "send.newsletter", words: "This issue and the ones after it go out when you approve them" } } });
    });
    const sw = d.q("#ask-real") as HTMLInputElement;
    sw.checked = true;
    sw.dispatchEvent(new Event("change", { bubbles: true }));
    await settle();
    flushSync();
    expect(live).toBe(true);
    expect((d.q("#ask-real") as HTMLInputElement).checked).toBe(true);
    expect(d.q("#ask-practice")).toBeNull();
    await d.click("#ask-schedule");
    const at = d.q("#ask-at") as HTMLInputElement;
    at.value = "2099-11-02T09:30";
    at.dispatchEvent(new Event("input", { bubbles: true }));
    flushSync();
    expect(d.q("#dlg-ok")?.textContent).toBe("Schedule");
    await d.click("#dlg-ok");
    expect(d.q("#ask-result")?.textContent).toContain("Scheduled.");
    d.done();
  });

  it("an ask already answered offers no button, only what happened", async () => {
    const d = await open(() => view({ state: "dry" }, { open: false, said: "Practiced on 28 Oct: not sent" }));
    expect(d.q("#ask-said")?.textContent).toBe("Practiced on 28 Oct: not sent");
    expect(d.q("#dlg-ok")).toBeNull();
    expect(d.q(".dlg-f button")?.textContent).toBe("Close");
    d.done();
  });

  it("a kind with no plain words (a booking) shows every fact it approves", async () => {
    const d = await open(() => view({ kind: "book.place" }, { question: "Book this table?", verb: "Approve", to: null, body: "", needs: null, practice: null, facts: [["Table", "for 2"], ["Price", "$50.05"]] }));
    expect(d.q(".pd-keys")?.textContent).toBe("Tablefor 2Price$50.05");
    expect(d.q("#dlg-ok")?.textContent).toBe("Approve");
    d.done();
  });
});

describe("an installed cub's head and its Log", () => {
  let host: ReturnType<typeof mount> | null = null;
  beforeEach(() => { host = mount(DialogHost, { target: document.body }); });
  afterEach(() => {
    closeDialog();
    if (host) void unmount(host);
    document.body.replaceChildren();
  });
  const tootRow = digest({ id: "toot", title: "Toot the pick", trust: "owner", mode: "drafts only",
    manifest: { requests: ["post.mastodon"], actions: [], ui: { nav: [], cards: {}, lists: [] } } });
  const detail = (o: Record<string, unknown> = {}) => ({ id: "toot", title: "Toot the pick", version: "1.0.0", trust: "owner", state: "installed", enabled: true,
    mode: "drafts only", live: [], tree_ok: true, paused: null, update: null, grants: { requests: ["post.mastodon"] }, words: [], inventory: null, ...o });
  const tootWhere = (sel: string | null, q: Record<string, string> = {}) => ({ ...cubWhere(sel, q), id: "toot", r: { path: ["cub", "toot"], q, sel } });
  const dialog = () => document.getElementById("dlg")!;

  it("offers an update staged from a terminal on the page's head, without an action", async () => {
    const up = { version: "1.2.0", sha: null, job: "j1", needs: "house", adds: ["requests: post.topic"] };
    const reads = { [FEATURES_API]: FEATURES(tootRow), [SHELL_API]: shell, [cubPath("toot")]: detail({ update: up }) };
    stub();
    hosted();
    answering(reads);
    ui.headOn = true;
    let v = await draw(CubPage, tootWhere(null));
    await settle();
    const up1 = headOf().more!.find((x) => x.id === "cub-update-ready")!;
    expect(up1.label).toBe("Update to 1.2.0");
    // Update is on its Settings page (D-2: featurepage.svelte.test.ts presses it)
    up1.run(document.body);
    expect(location.hash).toBe("#/settings/toot");
    v.done();
    stub();
    hosted();
    ui.headOn = true;
    answering({ ...reads, [cubPath("toot")]: detail() });
    v = await draw(CubPage, tootWhere(null));
    await settle();
    expect(headOf().more!.some((x) => x.id === "cub-update-ready")).toBe(false);
    // nothing on a cub's page is called Settings but the gear
    expect(headOf().gear).toBe("settings/toot");
    expect(headOf().more!.map((x) => x.label)).not.toContain("Settings");
    v.done();
  });

  it("shows an installed cub's own log under Log, beside its history in words", async () => {
    stub();
    hosted();
    answering({ [FEATURES_API]: FEATURES(tootRow), [SHELL_API]: shell, "/api/asks?cub=toot": { asks: [], history: [{ id: 3, title: "This week", said: "Practiced on 28 Oct: not sent", at: NOW }] },
      [cubPath("toot", "log") + "?limit=100"]: { lines: [{ ts: NOW, src: "host", level: "info", msg: "job.run toot.weekly" },
                                                        { ts: NOW, src: "cub", level: "warning", msg: "no new editor's pick" }], calls: [] } });
    const { target, done } = await draw(CubPage, tootWhere(null, { list: "log" }));
    await settle();
    expect([...target.querySelectorAll("[aria-labelledby=cub-lines] .r-title")].map((x) => x.textContent)).toEqual(["no new editor's pick", "job.run toot.weekly"]);
    expect(target.querySelector("[aria-labelledby=cub-log] .r-title")?.textContent).toBe("Practiced on 28 Oct: not sent: This week");
    expect(target.querySelector("[aria-labelledby=cub-log]")?.textContent).toContain("Practiced on 28 Oct: not sent");
    done();
  });
});

describe("the helpers", () => {
  it("reads dotted keys, cites, groups, tickets and subjects", () => {
    expect(at({ a: { b: 2 } }, "a.b")).toBe(2);
    expect(at({ a: 1 }, "a.b")).toBeUndefined();
    expect(citesOf(["obs 5", { label: "exa 2", url: "ftp://x" }])).toEqual([
      { label: "obs 5", obs: 5, brief: null, url: null, title: "", date: "", n: 1 }, { label: "exa 2", obs: null, brief: null, url: null, title: "", date: "", n: 1 }]);
    // an issue names a brief per item: one cite a brief, its page, with how many items it gave
    const briefs = [2, 2, 2, 1, 1].map((id) => ({ kind: "brief", id, label: `brief ${id}` }));
    expect(citesOf(briefs).map((c) => [c.label, c.brief, c.n])).toEqual([["News brief 2", 2, 3], ["News brief 1", 1, 2]]);
    const l = { id: "x", word: "X", read: "r", card: "c", groups: [{ key: "open", word: "Open" }], count: null };
    expect(groupsOf(l, { open: [{ id: 1 }], other: [] })).toEqual([{ key: "open", word: "Open", items: [{ id: 1 }] }]);
    expect(ticketOf({ ticket: { id: 4, state: "done" } })).toBeNull();
    expect(ticketOf({ ticket: 9 })).toBe(9);
    expect(subjectField({ id: "digest" }, { subjects: ["digest_proposal"] })).toBe("proposal_id");
    expect(subjectField({ id: "news" }, { subjects: ["topic"] })).toBe("topic_id");
    expect(permissionWords({ reads: ["briefs"], requests: ["newsletter.send"] })).toEqual([["Reads", "briefs"], ["Asks you", "newsletter send: each one waits for your approval on the page"]]);
    expect(permissionWords({ http: { hosts: ["example.com", "news.example.org"] } })).toEqual([["Calls", "example.com, news.example.org and their subdomains, without your credentials"]]);
    expect(permissionWords({ http: { hosts: ["example.com"] } })).toEqual([["Calls", "example.com and its subdomains, without your credentials"]]);
    expect(modeWords("send.newsletter", true)).toBe("for real: approving it sends it now");
    expect(modeWords("send.newsletter", false)).toBe("practice: approving it sends nothing");
    expect(modeWords("book.propose", false)).toBe("practice: approving it does nothing");
  });
  it("draws a card's dotted keys as text", () => {
    const target = document.createElement("div");
    const c = mount(Card, { target, props: { schema: proposalCard, object: { ...proposal, thesis: { ...proposal.thesis, instrument_name: "<b>A</b>" } } } });
    expect(target.querySelector(".card-t")?.textContent).toBe("<b>A</b>");
    expect(target.querySelector("dd")?.textContent).toBe("$50.05");
    void unmount(c);
  });
});

describe("an object whose id holds a colon (the newsletter's issue draft:1)", () => {
  it("opens its sheet with its ask's button from sel=o<id>, the link the home and Needs you give (QA B3, seen on live)", async () => {
    stub();
    hosted();
    const base = digest();
    const mail = { ...base, id: "mail", title: "Newsletter", trust: "owner", mode: "live", settings: [],
      manifest: { ...base.manifest, actions: [], ui: { ...base.manifest.ui, lists: [{ id: "issues", word: "Issues", read: "issues", card: "issue", groups: [{ key: "waiting", word: "Waits for you" }] }],
        cards: { issue: { title: "subject", lines: [], fields: [], actions: [], origin: "cites" } } } } } as unknown as FeatureRow;
    answering({ [FEATURES_API]: FEATURES(mail), [SHELL_API]: shell, [featurePath("mail", "issues")]: { waiting: [{ id: "draft:1", subject: "This week", ticket: 9, state: "waiting" }] }, [CUBS_API]: { cubs: [] } });
    const w = where("cub/mail", "odraft:1");
    const { target, done } = await draw(CubPane, { ...w, node: "cub", id: "mail", stage: false, object: "sel", obj: ["sel", "odraft:1"], sel: true, r: { path: ["cub", "mail"], q: {}, sel: "odraft:1" } });
    await settle();
    expect(target.querySelector("#cub-sheet")?.textContent).not.toContain("not in this list");
    expect(target.querySelector('#cub-sheet [data-act="ask-open"]')?.textContent).toBe("Approve");
    done();
  });
});

describe("the head never holds a verb that can only fail (QA's pattern for UIBUGS B1)", () => {
  // the server refuses an action while its feature is off (features_api: "<title> is off", 409)
  // and the page offers one with a when only while that setting is on (Action.when, the server
  // #291): for each state of the switches, every verb the head draws is one the server runs
  const gateRow = (value: boolean) => ({ key: "digest.news_theses", value, type: "bool", default: false, choices: [], lo: null, hi: null, words: "news theses", sensitive: false, by_hand: false, per_topic: false });
  const scan = { kind: "digest.scan_now", title: "Propose now", doors: ["ui"], click: "click", subjects: [], says: "", fields: [], place: "head", when: "digest.news_theses" };
  const compose = { id: "compose", word: "Compose", submit: "digest.refresh", fields: [], cost: "", says: "" };
  const withRun = (enabled: boolean, gate: boolean): FeatureRow => {
    const f = digest({ enabled, mode: enabled ? "practice" : "off" });
    return { ...f, settings: [...(f.settings || []), gateRow(gate)],
      manifest: { ...f.manifest, actions: [...(f.manifest.actions || []), scan], ui: { ...f.manifest.ui, forms: [compose] } } } as unknown as FeatureRow;
  };
  for (const [enabled, gate] of [[true, true], [true, false], [false, true], [false, false]] as const) {
    it(`feature ${enabled ? "on" : "off"}, its when ${gate ? "on" : "off"}`, async () => {
      stub();
      hosted();
      const f = withRun(enabled, gate);
      answering({ [FEATURES_API]: FEATURES(f), [SHELL_API]: shell, [featurePath("digest", "proposals")]: { open: [], history: [] }, [CUBS_API]: { cubs: [] } });
      ui.headOn = true;
      const { done } = await draw(CubPage, cubWhere());
      await settle();
      const h = headOf();
      // every verb the head offers (its primary, Stop, ⋯), as the action it runs or "form"
      const ids = [h.primary?.id, h.stop?.id, ...(h.more || []).map((x) => x.id)].filter((x): x is string => !!x && (x.startsWith("head-") || x.startsWith("form-")));
      const verbs = ids.map((x) => (x.startsWith("form-") ? "form" : x.slice(5)));
      const runs = (k: string | null) => enabled && (k !== "digest.scan_now" || gate);
      expect(verbs.filter((k) => !runs(k))).toEqual([]);
      if (enabled) expect(verbs).toContain("digest.stop");    // it does draw what runs
      done();
    });
  }
});

describe("a cub draws like Kranto's own", () => {
  const issue = { title: "subject", lines: ["intro"], fields: [], actions: [], origin: "cites", open: "page" as const, body: "body_markdown" };
  const mail = (o: { empty?: string } = {}): FeatureRow => {
    const base = digest();
    return { ...base, id: "mail", title: "Newsletter", trust: "owner", mode: "drafts only", settings: [],
      manifest: { ...base.manifest, actions: [], ui: { ...base.manifest.ui, kind: "send", glyph: "mail", primary: "compose",
        forms: [{ id: "compose", word: "Compose", submit: "mail.compose", fields: [], cost: "", says: "" }],
        lists: [{ id: "issues", word: "Issues", read: "issues", card: "issue", count: "waiting", empty: o.empty,
          groups: [{ key: "waiting", word: "Waits for you", tone: "wait" as const }, { key: "sent", word: "Sent", tone: "good" as const }] }],
        cards: { issue } } } } as unknown as FeatureRow;
  };
  const mailWhere = (path: string[], sel: string | null = null) => ({ ...where(path.join("/"), sel), node: path.length > 2 ? "cub/o" : "cub", id: "mail", stage: path.length > 2, object: null, obj: null, sel: false, r: { path, q: {}, sel } });
  // a planted link to a script address (spelled in two parts: no source here writes that scheme)
  const PLANTED = ["java", "script:alert(1)"].join("");
  const ISSUE = { id: "draft:1", subject: "This week", intro: "Three items.", state: "waiting", ticket: 9,
    body_markdown: `**Robots** leave the lab.\n\n<script>alert(1)</script> [a link](${PLANTED})`,
    cites: ["obs 5", ...[4, 4, 4].map((id) => ({ kind: "brief", id, label: `brief ${id}` }))] };

  it("says its own words when a list is empty, its compose form is the one primary, and its tones colour the rows", async () => {
    stub();
    hosted();
    ui.headOn = true;
    answering({ [FEATURES_API]: FEATURES(mail({ empty: "No issue yet. Monday 08:00 composes one." })), [SHELL_API]: shell, [featurePath("mail", "issues")]: { waiting: [], sent: [] } });
    let v = await draw(CubPage, mailWhere(["cub", "mail"]));
    await settle();
    expect(v.target.querySelector(".state-empty")?.textContent).toBe("No issue yet. Monday 08:00 composes one.");
    expect(headOf().primary).toMatchObject({ label: "Compose", href: "#/cub/mail?sel=form%3Acompose" });
    expect(headOf().glyph).toBe("✉");
    v.done();
    stub();
    hosted();
    answering({ [FEATURES_API]: FEATURES(mail()), [SHELL_API]: shell, [featurePath("mail", "issues")]: { waiting: [ISSUE], sent: [] } });
    v = await draw(CubPage, mailWhere(["cub", "mail"]));
    await settle();
    const row = v.target.querySelector("[aria-labelledby=cub-g-waiting] li.row")!;
    expect(row.querySelector(".gl")?.getAttribute("title")).toBe("waits on you");     // the group's tone
    expect(row.querySelector("a.r-title")?.getAttribute("href")).toBe("#/cub/mail/o/draft%3A1");   // open: page
    expect(row.getAttribute("data-sel")).toBe("odraft:1");                          // j and k still step to it
    expect(v.target.querySelector("[aria-labelledby=cub-g-sent] .state-empty")?.textContent).toBe("None.");
    v.done();
    stub();
    hosted();
    answering({ [FEATURES_API]: FEATURES(mail()), [SHELL_API]: shell, [featurePath("mail", "issues")]: { waiting: [], sent: [] } });
    v = await draw(CubPage, mailWhere(["cub", "mail"]));
    await settle();
    expect(v.target.querySelector(".state-empty")?.textContent).toBe("Nothing here yet.");   // the core's words, never "Nothing here."
    v.done();
  });

  it("opens an issue as a page of its text, drawn as text: no markup, no script, no link it did not earn", async () => {
    stub();
    hosted();
    ui.headOn = true;
    answering({ [FEATURES_API]: FEATURES(mail()), [SHELL_API]: shell, [featurePath("mail", "issues")]: { waiting: [ISSUE], sent: [] } });
    const v = await draw(CubObjectPage, mailWhere(["cub", "mail", "o", "draft%3A1"]));
    await settle();
    const body = v.target.querySelector(".cub-body")!;
    expect(body.querySelector("strong")?.textContent).toBe("Robots");
    expect(body.textContent).toContain("<script>alert(1)</script>");                // its words, as words
    expect(body.querySelector("script")).toBeNull();
    expect(body.querySelector("a")).toBeNull();                                      // a link out is not the cub's to make
    expect(headOf().title).toBe("This week");
    expect(headOf().crumb!.map((c) => c.w)).toEqual(["Cubs", "Newsletter", "This week"]);
    expect(headOf().primary?.label).toBe("Approve");                               // an ask waits
    expect(headOf().facts).toBe("Three items. · waiting");
    // what it rests on: the observation, and the brief once (it gave three items), its page
    const rests = [...v.target.querySelectorAll(".ctx li")].map((li) => [li.textContent!.trim(), li.querySelector("a")?.getAttribute("href")]);
    expect(rests).toEqual([["obs 5", "#/library/o/5"], ["News brief 4 · 3 items", "#/news/b/4"]]);
    v.done();
  });
});
