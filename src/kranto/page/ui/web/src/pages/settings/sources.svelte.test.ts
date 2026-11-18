import { afterEach, describe, expect, it, vi } from "vitest";
import type { Facts } from "../../lib/app";
import type { Where } from "../../lib/pages.svelte";
import { ui } from "../../lib/shell.svelte";
import { answering, draw, settle, stub, where } from "../testing.svelte";
import { FOLD_KEY, FOLDED } from "../../ui/fold.svelte";
import SourcesList from "./SourcesList.svelte";
import SourcesPane from "./SourcesPane.svelte";
import { gradeWords, removalWords } from "./sourceverbs";
import { CATALOG_API, filterSources, FORM, GROUPS, listGroup, presetWords, proposalTopic, SOURCES_API, topicWords, type Catalog, type Source, type SourcePage, type Sources } from "./sources.svelte";

const NOW = new Date().toISOString();
// The server's /api/sources (Sources is generated from its web/types.py)
const src = (id: number, o: Partial<Source> = {}): Source => ({
  id, kind: "rss", label: `Source ${id}`, origin: "manual", review: "approved", group: "approved", status: "ok", detail: "", site: "hn", site_name: "Hacker News",
  preset: "hn-front", fields: null, topics: [{ id: 3, name: "Local-first", kind: "user" }], proposed_for: null, found_for: null, why: null, replaces: null, validation: {}, items_7d: 14,
  items_per_day: 2, kept_30d: 4, judged_30d: 10, kept_rate: 0.4, yield_per_day: 0.13, mute: null, last_fetch: NOW, last_error: null, retry_at: null,
  failing_runs: 0, backoff_until: null, needs_fixing: false, connection: null, retention_days: 90, note: null, spend: null, grades: null, removal: null, ...o,
});
const D: Sources = {
  sources: [src(1), src(2, { review: "proposed", group: "proposed", status: "proposed", why: "Close to the topic", site_name: "Lobsters", items_per_day: null }),
    src(3, { review: "retired", group: "retired", status: "retired", mute: { muted_until: "2026-11-02T00:00:00Z", read_less: false, since: NOW } })],
  topics: [{ id: 3, name: "Local-first", description: "", kind: "topic", ref: null, sources: 2 }], reddit: { watched: 2, note: "" },
  connections_need_you: 0, every_hours: 6, default_retention_days: 90,
};
// The server's /api/catalog (Catalog is generated from its web/types.py)
const HN = { provider: "hn", provider_name: "Hacker News", needs: null, reason: null, retention_days: null };
const CAT: Catalog = {
  providers: [{ key: "hn", name: "Hacker News", presets: [{ ...HN, key: "hn-front", name: "Front page", blurb: "The front page.", access: "public", available: true, fields: [] },
    { ...HN, key: "hn-user", name: "A user", blurb: "One user's posts.", access: "public", available: true, fields: [{ key: "user", label: "User", hint: "Their handle", placeholder: "pg" }] }] },
  { key: "x", name: "X Corp", presets: [{ key: "x-list", provider: "x", provider_name: "X Corp", name: "A list", blurb: "A list.", access: "login", needs: "x", available: false, reason: "Not offered yet", retention_days: null, fields: [] }] }],
  connected: {}, topics: [{ id: 3, name: "Local-first", description: "", kind: "user", ref: null, sources: 2 }], prefilter: 0.3,
};
// The server's /api/sources/<id> (SourcePage, generated)
const PAGE: SourcePage = { ...src(1), params: { url: "https://hn.example/rss" }, how: { request: "GET https://hn.example/rss", pacing: "one a second", terms: "public" }, every_hours: 6,
  added_at: "2026-09-01T10:00:00Z", retention_override: false, retention_kind_days: 90, topic_facts: [{ id: 3, name: "Local-first", kind: "user", status: "active", sources: 2, kept_month: 34 }],
  kept_month: 19, spend_month: { usd: 0.12, tokens: { in: 40000, out: 1200 } },
  fetches: [{ id: 1, source_id: 1, run_uuid: "r1", state: "ok", trigger: "run", fetched: 30, new: 4, error: null, created_at: NOW, retry_at: null }] };
/** the old module, stubbed with what the source rows and panes place of it */
const stubL = (o: Parameters<typeof stub>[0] = {}) => {
  const L = stub(o);
  Object.assign(L, { sigOf: (n: Element) => n.className + "|" + (n.textContent || "") });
  return L;
};
const hosted = () => { ui.facts = { header: { host: { paused: false } } } as unknown as Facts; };
afterEach(() => { ui.facts = null; FORM.f = null; });
const at = (path: string, q: Record<string, string> = {}, sel: string | null = null): Where => ({ ...where("settings/sources", sel), r: { path: path.split("/"), q, sel } });
const source = (id: number, node = "settings/sources"): Where =>
  ({ ...where(node), r: { path: ["settings", "sources", String(id)], q: {}, sel: null }, list: ["settings", "sources"], object: "source", obj: ["settings", "sources", String(id)], id: String(id) });

describe("Settings › Sources", () => {
  it("filters by state, site and words, and knows a proposal's topic", () => {
    expect(filterSources(D.sources, { status: "attention" })).toEqual([]);
    expect(filterSources(D.sources, { site: "Lobsters" }).map((s) => s.id)).toEqual([2]);
    expect(filterSources(D.sources, { q: "close" }).map((s) => s.id)).toEqual([2]);
    // the groups in the owner's words, in the page's order (D7; the owner's O-5: Watched)
    expect(GROUPS.map((g) => g[1])).toEqual(["Proposed", "Watched", "Wildcards", "No topic", "Retired", "Could not be fetched", "Imported labels"]);
    expect(GROUPS.every((g) => g[2])).toBe(true);
    // a proposed wildcard is a proposal (listed under Proposed, the Proposed filter finds it)
    const wild = { ...D.sources[1]!, group: "wildcard" };
    expect(listGroup(wild)).toBe("proposed");
    expect(filterSources([wild], { status: "proposed" }).length).toBe(1);
    // a proposal says its topic; a wildcard that it is unrelated to it
    const pk = { id: 40, name: "Plotkeeper (project)", kind: "project" };
    expect(topicWords({ ...D.sources[1]!, found_for: pk })).toBe("for Plotkeeper (project)");
    expect(topicWords({ ...wild, found_for: pk })).toBe("wildcard for Plotkeeper (project): unrelated, may carry its patterns");
    expect(topicWords({ ...D.sources[1]!, found_for: pk }, 40)).toBeNull();
    // the catalog's login words: who it reads as, or where to connect one (SRC D5, D7)
    const xp = { ...CAT.providers[1]!.presets[0]!, available: true };
    expect(presetWords(xp, CAT).meta).toBe("with your account · A list. Connect it first under Settings › Watching.");
    expect(presetWords(xp, { ...CAT, connected: { x: [{ instance: "x.com", account: "@octo-owner", state: "connected" }] } }).meta).toBe("with your account · connected as @octo-owner · A list.");
    expect(proposalTopic(D.sources[1]!, null)).toBe(3);
    expect(proposalTopic({ ...D.sources[1]!, group: "wildcard" }, null)).toBeNull();
    expect(proposalTopic({ ...D.sources[1]!, topics: [], proposed_for: "Gone" }, [])).toBeUndefined();
  });

  it("lists the sources by state, with the filters, the grades and Approve on a proposal", async () => {
    const L = stubL({ host: { topics: [{ id: 3, name: "Local-first" }] } });
    hosted();
    answering({ [SOURCES_API]: D, "/api/connections": { accounts: [], providers: [] }, "/api/feedback?target=source&ids=1,2,3": { grades: { 1: { value: "useful" } } } });
    const { target, done } = await draw(SourcesList, at("settings/sources"));
    // the sources by state; the accounts some are read with are Settings › Accounts' only (the
    // owner's O1, 2026-10-22), one line says where
    expect([...target.querySelectorAll(".grp h2")].map((h) => h.textContent)).toEqual(["Proposed", "Watched", "Retired"]);    expect(target.querySelector('a[href="#/settings/watching"]')?.textContent).toBe("Settings › Watching");
    expect(target.querySelector(".tb .tbn > span.muted")?.textContent).toBe("3 of 3");
    expect((target.querySelector(".tbn.filters #search") as HTMLInputElement).placeholder).toBe("Filter sources  ( / )");
    const one = target.querySelector('[data-sel="s1"]') as HTMLElement;
    // one line, one fact: the topics it feeds; items a day, kept and yield are its sheet's
    expect(one.querySelector(".c-num")?.textContent).toBe("");
    expect(one.querySelector(".c-aside")?.textContent).toBe("");
    expect(one.querySelector(".c-meta")?.textContent).toBe("Local-first");
    expect(target.querySelector(".grade")).toBeNull(); // a source's verdict is its evidence's grades
    expect(target.querySelector('[data-sel="s3"] .c-meta')?.textContent).toBe("muted until 2 Nov");
    const ok = target.querySelector('[data-sel="s2"] .r-act button') as HTMLButtonElement;
    expect(ok.textContent).toBe("Approve");
    ok.click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/sources", { id: 2, status: "approved", topic: 3 });
    expect(L.toast).toHaveBeenCalledWith("Watching Source 2 for Local-first. Its first fetch is the next ingest run.");
    expect(target.querySelector("#add-source")?.getAttribute("href")).toBe("#/settings/sources/new");
    done();
  });

  it("Dismiss beside Approve, groups that fold and stay folded, no ticks and no Select", async () => {
    const L = stubL({ host: { topics: [{ id: 3, name: "Local-first" }] } });
    hosted();
    localStorage.removeItem(FOLD_KEY);
    FOLDED.clear();
    answering({ [SOURCES_API]: D, "/api/connections": { accounts: [], providers: [] }, "/api/feedback?target=source&ids=1,2,3": { grades: {} } });
    const { target, done } = await draw(SourcesList, at("settings/sources"));
    // #8: a proposal's quick actions are Approve and Dismiss, a quiet ✕ (D-4); Dismiss offers Undo
    expect([...target.querySelectorAll('[data-sel="s2"] .r-act button')].map((b) => b.textContent)).toEqual(["Approve", "✕"]);
    expect(target.querySelector('[data-sel="s2"] [data-act="dismiss"]')?.getAttribute("aria-label")).toBe("Dismiss Source 2");
    (target.querySelector('[data-sel="s2"] [data-act="dismiss"]') as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/sources/2/status", { status: "retired" });
    const undo = L.toast.mock.calls.at(-1)?.[1] as () => void;
    undo();
    await settle();
    expect(L.api).toHaveBeenLastCalledWith("/api/sources/2/status", { status: "proposed" });
    // bulk grading went with (D-3): no tick, no Select, no bulk bar
    expect(target.querySelector("input.tick, #select-rows, #bulk")).toBeNull();
    // #7: Proposed folds to its heading, and the fold is kept in this browser
    const proposed = target.querySelector('section[aria-labelledby="src-proposed"]') as HTMLElement;
    (proposed.querySelector(".twisty") as HTMLButtonElement).click();
    await settle();
    expect((proposed.querySelector("ul.lst") as HTMLElement).hidden).toBe(true);
    expect(proposed.querySelector(".twisty")?.getAttribute("aria-expanded")).toBe("false");
    expect(JSON.parse(localStorage.getItem(FOLD_KEY) || "[]")).toEqual(["sources:proposed"]);
    (proposed.querySelector(".twisty") as HTMLButtonElement).click();
    await settle();
    expect((proposed.querySelector("ul.lst") as HTMLElement).hidden).toBe(false);
    done();
    localStorage.removeItem(FOLD_KEY);
  });

  it("says when Sources need the server, and when nothing matches", async () => {
    stubL();
    const none = await draw(SourcesList, at("settings/sources"));
    expect(none.target.querySelector("strong")?.textContent).toBe("Sources need Kranto's server, which is not answering. ");
    none.done();
    stubL();
    hosted();
    answering({ [SOURCES_API]: D, "/api/connections": { accounts: [], providers: [] }, "/api/feedback?target=source&ids=1,2,3": { grades: {} } });
    const { target, done } = await draw(SourcesList, at("settings/sources", { q: "nothing like it" }));
    expect(target.querySelector("p.empty")?.textContent).toBe("No sources match.");
    done();
  });

  it("is the catalog at Add source: a filter that hides rows as you type, Choose on what is offered", async () => {
    stubL();
    hosted();
    answering({ [CATALOG_API]: CAT, "/api/connections": { accounts: [], providers: [] } });
    const { target, done } = await draw(SourcesList, at("settings/sources/new", { topic: "3" }));
    // opened from a topic, its head says so from the first press, with a lede and the way back
    expect(target.querySelector(".wl")?.getAttribute("data-title")).toBe("Add source to Local-first");
    expect(target.querySelector("h1")?.textContent).toBe("Add source to Local-first");
    expect(target.querySelector(".lsub")?.textContent).toBe("Pick a kind, give it an address or a search, Preview, then Add.");
    expect(target.querySelector("#add-back")?.textContent).toBe("All sources of Local-first");
    expect(target.querySelector("#add-back")?.getAttribute("href")).toBe("#/watch/sources?topic=3");
    expect(target.querySelector(".tbn > span:not(.grow)")?.textContent).toBe("3 kinds on 2 sites");
    expect(target.querySelector('[data-sel="epreset:hn-user"] .r-act a')?.getAttribute("href")).toBe("#/settings/sources/new?topic=3&sel=epreset%3Ahn-user");
    const off = [...target.querySelectorAll("li.row")].find((x) => x.querySelector(".r-title")?.textContent === "A list") as HTMLElement;
    expect(off.className).toBe("row lr off");
    expect(off.querySelector(".c-meta")?.textContent).toBe("next update · Not offered yet");
    expect(off.dataset.sel).toBeUndefined();
    const q = target.querySelector("#search") as HTMLInputElement;
    q.value = "user";
    q.dispatchEvent(new Event("input", { bubbles: true }));
    await settle();
    expect(location.hash).toBe("#/settings/sources/new?q=user");
    expect((target.querySelector('[data-sel="epreset:hn-front"]') as HTMLElement).hidden).toBe(true);
    expect((target.querySelector('[data-sel="epreset:hn-user"]') as HTMLElement).hidden).toBe(false);
    expect((target.querySelector('[aria-labelledby="cat-x"]') as HTMLElement).hidden).toBe(true);
    history.replaceState(null, "", "#/");
    done();
  });

  it("says in the pane what is read for which topic, and how a source is added", async () => {
    stubL();
    hosted();
    answering({ [SOURCES_API]: D });
    const home = await draw(SourcesPane, at("settings/sources"));
    expect(home.target.querySelector(".dt")?.textContent).toBe("Where Kranto reads");
    expect(home.target.querySelector(".note strong")?.textContent).toBe("Reddit's feeds stop on 13 Nov 2026. ");
    expect(home.target.querySelector("#s-topics a")?.getAttribute("href")).toBe("#/topics/3/sources");
    expect([...home.target.querySelectorAll("#s-counts dt")].map((x) => x.textContent)).toEqual(["Proposed", "Watched", "Retired"]);
    home.done();
    stubL();
    hosted();
    const add = await draw(SourcesPane, at("settings/sources/new"));
    expect(add.target.querySelector(".dk")?.textContent).toBe(" settings · add source");
    expect(add.target.querySelector(".lede")?.textContent).toBe("Paste a list or describe the sources; or pick a kind on the left.?"); // and the tip's ?
    expect(add.target.querySelector("#s-describe h3")?.textContent).toBe("Describe what to add");
    add.done();
  });

  it("opens a watched source with its verbs, fetches it now and saves its retention", async () => {
    const L = stubL({ answer: { state: "ok", fetched: 30, new: 4, effective_days: 30 } });
    const afkDrop = vi.fn();
    Object.assign(L, { afkDrop });
    hosted();
    answering({ "/api/sources/1": PAGE, "/api/observations?source=1&limit=5&sort=new": { results: [], total: 0 }, "/api/feedback?target=source&ids=1": { grades: {} } });
    const { target, done } = await draw(SourcesPane, source(1), "#/settings/sources");
    // its kind line counts its topics; the lede says where it came from; Topics is its first
    // section: each topic it feeds with its watched sources and kept items, Remove (this topic only)
    expect(target.querySelector(".dk")?.textContent).toBe(" source · Hacker News · ok · 1 topic");
    expect(target.querySelector(".lede")?.textContent).toMatch(/^Added by you on 1 Sep/);
    expect([...target.querySelectorAll(".toc a")].map((a) => a.firstChild?.textContent)[0]).toBe("Topics");
    const tr = target.querySelector("#source-topics li.row") as HTMLElement;
    expect(tr.querySelector("a.r-title")?.getAttribute("href")).toBe("#/topics/3");
    expect(tr.querySelector(".c-meta")?.textContent).toBe("2 watched · 19 of its 34 kept items this month");
    expect(tr.querySelector("[data-act=remove-from]")?.textContent).toBe("Remove from Local-first");
    expect(tr.querySelector("[data-act=remove-from]")?.getAttribute("title")).toBe("It has no other topic: Kranto stops reading it (as Retire)");
    // the account it is read with is Settings › Accounts' (D7)
    expect([...target.querySelectorAll("#s-how dt")].map((x) => x.textContent)).toContain("Account");
    expect(target.querySelector('#s-how a[href="#/settings/connections"]')).toBeNull();
    expect([...target.querySelectorAll(".dh .acts .btn")].map((b) => b.textContent)).toEqual(["Fetch now", "Mute", "Retire"]);
    // one topic: no reach to say
    expect(target.querySelector("#retire-source")?.getAttribute("title")).toBeNull();
    // what judging its items cost this month, beside the topic's own
    expect(target.querySelector("#source-tokens")?.textContent).toMatch(/^41(\.\d)?k tokens$/);
    expect([...target.querySelectorAll("#s-facts .fact dt")].map((x) => x.textContent)).toContain("Tokens this month");
    expect(target.querySelector(".acts .mono")?.textContent).toBe("kept 90 days");
    expect(target.querySelector(".gh, .grade")).toBeNull();
    expect(target.querySelector("#s-fetches .r-title")?.textContent).toBe("30 fetched, 4 new");
    expect(target.querySelector("#s-recent p.muted")?.textContent).toBe("Nothing kept from it yet.");
    (target.querySelector("#fetch-now") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/sources/1/fetch", {});
    expect(L.say).toHaveBeenCalledWith("Fetched 30 items, 4 new. Nothing is judged until the next run.", "blue");
    const ret = target.querySelector("#ret-days") as HTMLInputElement;
    expect(ret.placeholder).toBe("90");
    ret.value = "30";
    (ret.nextElementSibling as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/sources/1/retention", { days: 30 });
    expect(L.say).toHaveBeenCalledWith("Kept 30 days.");
    const mute = [...target.querySelectorAll(".dh .acts button")].find((b) => b.textContent === "Mute") as HTMLButtonElement;
    mute.click();
    expect(L.popover).toHaveBeenCalledWith(mute, "Mute Source 1", [], expect.anything());
    expect([...document.querySelectorAll(".pop.menu button")].map((b) => b.textContent)).toEqual(["Mute for 7 days", "Mute for 30 days", "Read less", "Retire"]);
    (document.querySelector(".pop.menu button") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/sources/1/mute", { days: 7 });
    const retire = [...target.querySelectorAll(".dh .acts button")].find((b) => b.textContent === "Retire") as HTMLButtonElement;
    retire.click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/sources/1/status", { status: "retired" });
    expect(L.toast).toHaveBeenLastCalledWith("Source 1 is retired: no longer fetched.", expect.any(Function));
    done();
  });

  it("a shared source says its topics and the reach of every verb: Remove from one, the rest everywhere", async () => {
    const four = [{ id: 3, name: "Local-first", kind: "user" }, { id: 5, name: "LLM tooling", kind: "user" }, { id: 7, name: "Receipts (project)", kind: "project" }, { id: 8, name: "Sidedoor (project)", kind: "project" }];
    const L = stubL({ host: { topics: [{ id: 3, name: "Local-first" }, { id: 5, name: "LLM tooling" }, { id: 11, name: "Robotics" }] },
      answer: { id: 3, added: [], removed: [1], retired: [], approved: [], remaining: { 1: four.slice(1) } } });
    const menu = vi.fn();
    Object.assign(L, { menu });
    hosted();
    const shared: SourcePage = { ...PAGE, topics: four, origin: "scout", found_for: four[1]!, why: "Writes about tools weekly",
      topic_facts: four.map((t, i) => ({ ...t, status: "active", sources: 10 + i, kept_month: 30 + i })) };
    answering({ "/api/sources/1": shared, "/api/observations?source=1&limit=5&sort=new": { results: [], total: 0 }, "/api/feedback?target=source&ids=1": { grades: {} } });
    const { target, done } = await draw(SourcesPane, source(1), "#/settings/sources");
    expect(target.querySelector(".dk")?.textContent).toBe(" source · Hacker News · ok · 4 topics");
    expect(target.querySelector(".lede")?.textContent).toMatch(/^Writes about tools weekly · Found by the scout for LLM tooling on 1 Sep/);
    expect([...target.querySelectorAll("#source-topics .r-title")].map((x) => x.textContent)).toEqual(["Local-first", "LLM tooling", "Receipts (project)", "Sidedoor (project)"]);
    expect(target.querySelectorAll("#source-topics li.row")[2]?.querySelector(".c-meta")?.textContent).toBe("project topic · 12 watched · 19 of its 32 kept items this month");
    expect(target.querySelector("#retire-source")?.getAttribute("title")).toBe("Retire: not read for any topic (everywhere: all 4 topics); its evidence stays; Watch again undoes it");
    // Mute's items each say they act everywhere
    (target.querySelector(".dh .acts .btn.quiet") as HTMLButtonElement).click();
    expect([...document.querySelectorAll(".pop button[role=menuitem]")].map((b) => b.textContent)).toEqual(
      ["Mute for 7 days", "Mute for 30 days", "Read less", "Retire"].map((w) => w + "everywhere: all 4 topics"));
    for (const x of document.querySelectorAll(".pop")) x.remove();
    // Remove from Local-first: this topic only; the toast names what it still feeds; Undo links it again
    const rm = target.querySelector("#source-topics [data-act=remove-from]") as HTMLButtonElement;
    expect(rm.getAttribute("title")).toBe("It keeps feeding LLM tooling, Receipts (project) and 1 more");
    rm.click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/topics/3/sources", { remove: [1], origin: "ui" });
    const [said, undo] = L.toast.mock.calls.at(-1) as [string, () => void];
    expect(said).toBe("Removed Source 1 from Local-first. It still feeds LLM tooling, Receipts (project) and 1 more.");
    undo();
    await settle();
    expect(L.api).toHaveBeenLastCalledWith("/api/topics/3/sources", { add: [1], origin: "ui" });
    // Add to another topic: the active topics it does not feed
    (target.querySelector("#source-add-topic") as HTMLButtonElement).click();
    const items = (menu.mock.calls[0] as unknown as [unknown, { label: string; run: () => void }[]])[1];
    expect(items.map((x) => x.label)).toEqual(["Robotics"]);
    items[0]!.run();
    await settle();
    expect(L.api).toHaveBeenLastCalledWith("/api/topics/11/sources", { add: [1], origin: "ui" });
    expect((L.toast.mock.calls.at(-1) as [string])[0]).toBe("Source 1 feeds Robotics too, from the next run.");
    done();
  });

  it("says what you graded of a source and the source rule's word, with no grade of its own and no Read less", async () => {
    stubL();
    hosted();
    const grades = { useful: 1, not_useful: 2, wrong: 1, missed: 0, reasons: { off_topic: 2 } };
    const removal = { recommend: true, down: 3, up: 1, window_days: 90, kept: null };
    answering({ "/api/sources/1": { ...PAGE, grades, suggest: "read_less", removal }, "/api/observations?source=1&limit=5&sort=new": { results: [], total: 0 } });
    const { target, done } = await draw(SourcesPane, source(1), "#/settings/sources");
    expect([...target.querySelectorAll(".dh .acts .btn")].map((b) => b.textContent)).toEqual(["Fetch now", "Mute", "Retire"]);
    expect(target.querySelector("#source-grades")?.textContent).toBe("1 useful · 2 not useful · 1 wrong · 2 off topic");
    expect(target.textContent).toContain("Kranto recommends removing it: 3 of its 4 graded posts were not useful in 90 days");
    expect(target.querySelector(".grade, .gh")).toBeNull();
    expect(target.textContent).not.toContain("Your grade ▲");
    done();
  });
  it("says when a source was kept", () => {
    expect(removalWords({ recommend: false, down: 0, up: 0, window_days: 90, kept: { at: "2026-10-28T08:00:00Z", down: 4, up: 1 } }))
      .toBe("kept on 28 Oct, after 4 of 5 graded posts were not useful");
    expect(removalWords(null)).toBeNull();
    expect(removalWords({ recommend: false, down: 1, up: 0, window_days: 90, kept: null })).toBeNull();
  });
  it("says nothing of grades when none was given", () => {
    expect(gradeWords(null)).toBeNull();
    expect(gradeWords({ useful: 0, not_useful: 0, wrong: 0, reasons: {} })).toBeNull();
  });

  it("opens a proposal on a topic's page with Approve and watch for that topic, and folds four verbs into ⋯", async () => {
    const L = stubL({ host: { topics: [{ id: 7, name: "Sync" }] } });
    const menu = vi.fn();
    Object.assign(L, { menu });
    hosted();
    const proposed = { ...PAGE, ...src(2, { review: "proposed", group: "proposed", status: "proposed", why: "Close to the topic" }) };
    answering({ "/api/sources/2": proposed, "/api/sources/4": { ...PAGE, id: 4, status: "needs_login", detail: "Refused" } });
    const one = await draw(SourcesPane, { ...source(2, "topics/7/sources"), sel: true }, "#/topics/7/sources");
    expect(one.target.querySelector(".lede")?.textContent).toMatch(/^Close to the topic · Added by you on 1 Sep/);
    expect([...one.target.querySelectorAll(".dh .acts .btn")].map((b) => b.textContent)).toEqual(["Approve and watch", "Review", "Dismiss"]);
    expect(one.target.querySelector(".dh .acts a")?.getAttribute("href")).toBe("#/settings/sources/new?review=2");
    (one.target.querySelector("#approve-source") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/sources", { id: 2, status: "approved", topic: "7" });
    expect(L.toast).toHaveBeenCalledWith("Watching Source 2 for Sync. Its first fetch is the next ingest run.");
    one.done();
    const M = stubL();
    Object.assign(M, { menu });
    hosted();
    answering({ "/api/sources/4": { ...PAGE, id: 4, status: "needs_login", detail: "Refused" }, "/api/observations?source=4&limit=5&sort=new": { results: [], total: 0 }, "/api/feedback?target=source&ids=4": { grades: {} } });
    const four = await draw(SourcesPane, source(4));
    expect([...four.target.querySelectorAll(".dh .acts .btn")].map((b) => b.textContent)).toEqual(["Reconnect", "Fetch now", "⋯"]);
    expect(four.target.querySelector(".note strong")?.textContent).toBe("Needs login. ");
    (four.target.querySelector(".btn.more") as HTMLButtonElement).click();
    expect(menu.mock.calls[0]![1].map((x: { label: string }) => x.label)).toEqual(["Mute", "Retire"]);
    four.done();
  });

  it("previews a chosen kind and adds it, back to the topic it was opened from", async () => {
    const L = stubL();
    const preview = { items: 12, recent: 5, median_similarity: 0.41, prefilter: 0.3, existing_id: null, newest: [{ title: "First", url: "data:text/html,x", published_at: NOW }] };
    L.api.mockImplementation(async (path: string) => (path === "/api/sources/preview" ? preview : { id: 9, label: "A user: pg" }));
    const afkDrop = vi.fn();
    Object.assign(L, { afkDrop });
    hosted();
    answering({ [CATALOG_API]: CAT });
    history.replaceState(null, "", "#/settings/sources/new?topic=3&sel=epreset:hn-user");
    const w = at("settings/sources/new", { topic: "3" }, "epreset:hn-user");
    const { target, done } = await draw(SourcesPane, w, "#/settings/sources/new?topic=3");
    expect(target.querySelector(".dt")?.textContent).toBe("Hacker News: A user");
    expect(target.querySelector(".dk")?.textContent).toBe(" add source · Hacker News · to Local-first");
    expect((target.querySelector("#f-topic") as HTMLSelectElement).value).toBe("3");
    expect(target.querySelector("#s-preview")).toBeNull();
    const user = target.querySelector("#f-user") as HTMLInputElement;
    user.value = "pg";
    user.dispatchEvent(new Event("input", { bubbles: true }));
    (target.querySelector("#preview") as HTMLButtonElement).click();
    await settle();
    expect(FORM.f?.error).toBeNull();
    expect(L.api).toHaveBeenCalledWith("/api/sources/preview", { preset: "hn-user", fields: { user: "pg" }, topic: "3" });
    expect(target.querySelector("#s-preview strong")?.textContent).toBe("12 items; 5 in the last 30 days; similarity to the topic 0.41");
    expect(target.querySelector("#preview")?.textContent).toBe("Preview again");
    expect(target.querySelector("#s-preview .ctx a")?.hasAttribute("href")).toBe(false);
    (target.querySelector("#add") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/sources", { preset: "hn-user", fields: { user: "pg" }, topic: "3" });
    expect(location.hash).toBe("#/topics/3/sources");
    expect(L.say).toHaveBeenCalledWith("A user: pg is watched. Its first fetch is the next ingest run.");
    expect(FORM.f).toBeNull();
    history.replaceState(null, "", "#/");
    done();
  });

  it("reviews a proposal with the scout's test fetch, and Dismiss retires it", async () => {
    const L = stubL();
    Object.assign(L, { afkDrop: vi.fn() });
    hosted();
    const p = src(2, { review: "proposed", group: "proposed", status: "proposed", why: "Close to the topic", preset: "hn-front", validation: { items: 8, recent: 3 } });
    answering({ [CATALOG_API]: CAT, [SOURCES_API]: { ...D, sources: [p] } });
    const { target, done } = await draw(SourcesPane, at("settings/sources/new", {}, "ereview:2"));
    expect(target.querySelector(".dt")?.textContent).toBe("Review: Source 2");
    expect(target.querySelector("#s-preview h3")?.textContent).toBe("The scout's test fetch");
    expect(target.querySelector("#s-preview p")?.textContent).toBe("8 items; 3 in the last 30 days. No topic: every item is judged.");
    expect(target.querySelector("#add")?.textContent).toBe("Approve and watch");
    const no = target.querySelector("#dismiss-source") as HTMLButtonElement;
    expect(no.className).toBe("btn"); // a button like the rest, not a link (UP #8)
    no.click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/sources/2/status", { status: "retired" });
    expect(location.hash).toBe("#/settings/sources");
    expect(L.toast).toHaveBeenCalledWith("Dismissed Source 2: not watched, and not proposed again.", expect.any(Function));
    history.replaceState(null, "", "#/");
    done();
  });
});
