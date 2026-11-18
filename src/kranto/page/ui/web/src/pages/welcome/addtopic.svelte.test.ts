import { afterEach, describe, expect, it, vi } from "vitest";
import type { Facts, App } from "../../lib/app";
import type { Where } from "../../lib/pages.svelte";
import { ui } from "../../lib/shell.svelte";
import { SETUP_API } from "../settings/keys.svelte";
import { SOURCES_API } from "../settings/sources.svelte";
import { answering, draw, settle, stub, where } from "../testing.svelte";
import AddTopic from "./AddTopic.svelte";
import AddTopicPane from "./AddTopicPane.svelte";
import Welcome from "./Welcome.svelte";
import { about, afkJob, perDay, RESTORE, TOPIC, type Proposal } from "./welcome.svelte";

const READS = {
  "/api/topics": { topics: [{ id: 1, name: "Energy access", status: "active" }, { id: 2, name: "Old", status: "paused" }] },
  [SOURCES_API]: { sources: [{ id: 5, review: "approved", topics: [{ id: 1, name: "Energy access" }], items_per_day: 4, validation: {} },
    { id: 6, review: "approved", topics: [], items_per_day: null, validation: { recent: 90 } }, { id: 8, review: null, topics: [{ id: 1, name: "Energy access" }], items_per_day: 50 }] },
  [SETUP_API]: { every_hours: 6, budget_usd: 20 },
};
// the scout's proposals as the server sends them (SourceRow, generated from its web/types.py)
const prop = (id: number, label: string, o: Partial<Proposal>): Proposal => ({
  id, kind: "rss", label, origin: "scout", review: "proposed", group: "proposed", status: "proposed", detail: "", site: "web", site_name: "Any website", preset: null,
  fields: null, topics: [], proposed_for: null, found_for: null, why: null, replaces: null, validation: {}, items_7d: 0, items_per_day: null, kept_30d: 0, judged_30d: 0, kept_rate: null,
  yield_per_day: 0, mute: null, last_fetch: null, last_error: null, retry_at: null, failing_runs: 0, backoff_until: null, needs_fixing: false, connection: null,
  retention_days: 90, note: null, spend: null, grades: null, removal: null, proposed_topic: 1, role: "core", pretick: false, ...o,
});
const P: Proposal[] = [prop(11, "r/solar", { pretick: true, validation: { recent: 30 } }), prop(12, "HN", { group: "wildcard", role: "wildcard" })];
const hosted = () => { ui.facts = { header: { host: { paused: false } } } as unknown as Facts; };
afterEach(() => {
  ui.facts = null;
  TOPIC.t = null;
  RESTORE.tried = false;
  history.replaceState(null, "", "#/");
});
/** the old module with the proposals' group and watching what is ticked; api answers by path */
function stubbed(answers: Record<string, unknown> = {}) {
  const L = stub({ host: { budget_usd: null } });
  const afkDrop = vi.fn(), sigOf = (n: Element) => new XMLSerializer().serializeToString(n);
  Object.assign(L, { afkDrop, sigOf });
  L.api.mockImplementation(async (path: string) => answers[path] ?? {});
  return { L };
}
/** what was approved: the ids posted to the approve endpoint, with their topic */
function watched(L: { api: { mock: { calls: unknown[][] } } }): unknown[] {
  return L.api.mock.calls.filter((c) => c[0] === "/api/sources/approve").map((c) => c[1]);
}
const page = (): Where => where("topics/new");
const step = (): Where => ({ ...where("welcome/topics"), stage: true });

describe("Add topic", () => {
  it("counts items a day, and polls a scout's job until it is done", async () => {
    expect(perDay([{ items_per_day: 4 }, { validation: { recent: 90 } }, { items_per_day: null, validation: null }])).toBe(7);
    expect([about(7), about(12.4)]).toEqual(["7.0", "12"]);
    const L = { api: vi.fn().mockResolvedValueOnce({ job: { state: "running" } }).mockResolvedValueOnce({ job: { state: "done", result: { proposals: [] } } }) } as unknown as App;
    const said: string[] = [];
    expect(await afkJob(L, { job: { state: "running", elapsed_s: 20 } }, "/api/topics/3/scout", "Scouting", (w) => said.push(w), 0)).toEqual({ proposals: [] });
    expect(said).toEqual(["Scouting… (20 s)", "Scouting… (20 s)"]);
    expect(await afkJob(L, { proposals: [1] }, "x", "Scouting", () => {})).toEqual({ proposals: [1] });
    const failed = { api: vi.fn(async () => ({ job: { state: "failed", error: "no model" } })) } as unknown as App;
    await expect(afkJob(failed, { job: { state: "running" } }, "x", "Scouting", () => {}, 0)).rejects.toThrow("no model");
  });

  it("is the list on Topics › Add topic: the words, the suggestions, and the cursor in the name", async () => {
    stubbed();
    hosted();
    answering(READS);
    const { target, done } = await draw(AddTopic, page());
    expect(target.querySelector(".wl")?.getAttribute("data-title")).toBe("Add topic");
    expect(target.querySelector(".lh .small")?.textContent).toBe("Topics");
    expect(target.querySelector(".lsub")?.textContent).toBe("A name and one sentence; Kranto finds places to read.");
    expect(target.querySelector(".box-h h2")?.textContent).toBe("Add a topic");
    await settle();
    expect(document.activeElement?.id).toBe("topic-name");
    const chips = [...target.querySelectorAll<HTMLButtonElement>(".chips .chip")];
    expect(chips.length).toBe(7);
    chips[5]!.click();
    await settle();
    expect((target.querySelector("#topic-name") as HTMLInputElement).value).toBe("Energy access");
    expect((target.querySelector("#topic-desc") as HTMLTextAreaElement).value).toMatch(/^Getting reliable electricity/);
    expect(chips[5]!.getAttribute("aria-pressed")).toBe("true");
    expect(target.querySelector(".wizard-foot")).toBeNull();
    done();
    stub();
    ui.facts = null;
    const none = await draw(AddTopic, page());
    expect(none.target.querySelector("strong")?.textContent).toBe("Topics need Kranto's server, which is not answering. ");
    none.done();
  });

  it("scouts once both words are there, then shows the proposals, ticked, and watches them", async () => {
    const { L } = stubbed({ "/api/topics": { id: 7, proposals: P, message: "2 proposed.", invalid: 1 } });
    hosted();
    answering(READS);
    const { target, done } = await draw(AddTopic, page());
    const scout = target.querySelector("#scout") as HTMLButtonElement;
    expect(scout.textContent).toBe("Find places to read");
    expect(scout.className).toBe("btn primary");
    const name = target.querySelector("#topic-name") as HTMLInputElement;
    name.value = "Solar";
    name.dispatchEvent(new Event("input", { bubbles: true }));
    scout.click();
    expect(L.api).not.toHaveBeenCalled();
    expect(document.activeElement?.id).toBe("topic-desc");
    const desc = target.querySelector("#topic-desc") as HTMLTextAreaElement;
    desc.value = "Off-grid solar.";
    desc.dispatchEvent(new Event("input", { bubbles: true }));
    scout.click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/topics", { name: "Solar", description: "Off-grid solar.", scout: true });
    expect(TOPIC.t?.id).toBe(7);
    expect([...TOPIC.t!.ticked]).toEqual([11]);
    expect(scout.textContent).toBe("Find more");
    expect(scout.className).toBe("btn");
    expect(scout.disabled).toBe(false);
    expect(target.querySelector(".box-h h2")?.textContent).toBe("Topic");
    expect(name.disabled).toBe(true);
    expect(target.querySelector(".chips")).toBeNull();
    expect(target.querySelector(".box-b p.mt")?.textContent).toBe("2 places found. 1 could not be read and is not shown.");
    const box = target.querySelector(".grp.props")!;
    expect(box.querySelector("h2")?.textContent).toBe("Proposed for “Solar”");
    expect(box.querySelectorAll("li.row").length).toBe(2);
    expect([...box.querySelectorAll("input.ptick")].filter((x) => (x as HTMLInputElement).checked).length).toBe(1);
    const foot = target.querySelector(".wizard-foot") as HTMLElement;
    expect(foot.querySelector("a")?.getAttribute("href")).toBe("#/topics/7");
    const go = foot.querySelector(".btn.primary") as HTMLButtonElement;
    expect(go.textContent).toBe("Watch these and open the topic");
    go.click();
    await settle();
    expect(watched(L)).toEqual([expect.objectContaining({ ids: [11] })]);
    expect(location.hash).toBe("#/topics/7/sources");
    expect(TOPIC.t?.id ?? null).toBeNull();
    done();
  });

  it("starts afresh on Add another topic, and Done goes on without watching", async () => {
    const { L } = stubbed();
    hosted();
    answering(READS);
    TOPIC.t = { name: "Solar", desc: "x", id: 7, rows: P, ticked: new Set(), message: null, invalid: 0 };
    const { target, done } = await draw(AddTopic, page());
    const go = target.querySelector(".wizard-foot .btn.primary") as HTMLButtonElement;
    expect(go.textContent).toBe("Done");
    ([...target.querySelectorAll("button")].find((b) => b.textContent === "Add another topic") as HTMLButtonElement).click();
    await settle();
    expect(TOPIC.t?.id).toBeNull();
    expect((target.querySelector("#topic-name") as HTMLInputElement).value).toBe("");
    expect(target.querySelector(".grp.props")).toBeNull();
    TOPIC.t = { name: "Solar", desc: "x", id: 7, rows: P, ticked: new Set(), message: null, invalid: 0 };
    await settle();
    (target.querySelector(".wizard-foot .btn.primary") as HTMLButtonElement).click();
    await settle();
    expect(watched(L)).toEqual([]);
    expect(location.hash).toBe("#/topics/7/sources");
    done();
  });

  it("its side is the pane: the topics so far, the one being added, and what happens next", async () => {
    stubbed();
    hosted();
    answering(READS);
    TOPIC.t = { name: "Solar", desc: "x", id: 7, rows: P, ticked: new Set([11]), message: null, invalid: 0 };
    const { target, done } = await draw(AddTopicPane, page());
    expect(target.querySelector(".pane > .pane-in")?.getAttribute("data-title")).toBe("Add topic");
    const rows = [...target.querySelectorAll("li.row")];
    expect(rows.map((r) => r.querySelector(".r-title")?.textContent)).toEqual(["Energy access", "Solar"]);
    expect(rows[0]?.querySelector(".r-meta")?.textContent).toBe("1 source · about 4.0 items a day");
    expect(rows[0]?.querySelector("a")?.getAttribute("href")).toBe("#/topics/1");
    expect(rows[1]?.querySelector(".r-meta")?.textContent).toBe("1 ticked of 2 proposed");
    expect(target.querySelector(".box-b.small.muted")?.textContent).toBe("Together: 1 topic, 2 sources, about 7.0 new items a day. Model calls stop at the monthly cap set under Settings › Spend. You can change any of this later under Topics.");
    expect(target.querySelector(".box-b.small p")?.textContent).toMatch(/^Kranto reads every 6 hours and keeps what fits your sentence\. The first brief comes as soon as 8 items are kept/);
    expect(target.querySelectorAll(".box-b.small p").length).toBe(1);
    done();
    stub();
    ui.facts = null;
    const none = await draw(AddTopicPane, page());
    expect(none.target.querySelector(".pane")?.children.length).toBe(1);
    const empty = none.target.querySelector(".pane > div");
    expect(empty?.tagName).toBe("DIV");
    expect(empty?.attributes.length).toBe(0);
    expect(empty?.childNodes.length).toBe(0);
    none.done();
  });

  it("is onboarding's step 2: the form beside its side, Skip for now, and Watch these and continue", async () => {
    const { L } = stubbed();
    hosted();
    answering({ ...READS, "/api/topics": { topics: [] } });
    const { target, done } = await draw(Welcome, step());
    expect(target.querySelector(".ph h1")?.textContent).toBe("What topics are you interested in?");
    expect(target.querySelector(".cols aside p.empty")?.textContent).toBe("None yet.");
    expect(target.querySelectorAll(".cols aside .box-b.small p").length).toBe(2);
    const foot = target.querySelector(".wizard-foot") as HTMLElement;
    expect([...foot.querySelectorAll("a")].map((a) => [a.textContent, a.getAttribute("href")])).toEqual([["Back", "#/welcome"], ["Skip for now", "#/welcome/finish"]]);
    const go = foot.querySelector("#watch-continue") as HTMLButtonElement;
    expect(go.textContent).toBe("Continue");
    TOPIC.t = { name: "Solar", desc: "x", id: 7, rows: P, ticked: new Set([11]), message: null, invalid: 0 };
    await settle();
    expect(go.textContent).toBe("Watch these and continue");
    go.click();
    await settle();
    expect(watched(L)).toEqual([expect.objectContaining({ ids: [11] })]);
    expect(location.hash).toBe("#/welcome/finish");
    done();
  });

  // a first run: a reload in step 2 lost the proposals (they stayed proposed on the topic's page)
  const SETUP_TOPIC = { ...READS, [SETUP_API]: { every_hours: 6, budget_usd: 20, topics: 1, done: false } };
  const TOPICS = { topics: [{ id: 3, name: "Old", description: "o", status: "paused" }, { id: 9, name: "Energy access", description: "Getting power to people.", status: "active" }] };
  /** step 2 drawn fresh, as after a reload, with api answering by path (a function: a refusal) */
  async function reloaded(answers: Record<string, unknown>) {
    const { L } = stubbed();
    L.api.mockImplementation(async (path: string) => {
      const a = answers[path];
      if (typeof a === "function") return (a as () => unknown)();
      return a ?? {};
    });
    hosted();
    answering(SETUP_TOPIC);
    const drawn = await draw(Welcome, step());
    await settle();
    await settle();
    return { L, ...drawn };
  }
  function shows(target: HTMLElement, ticked: number[]): void {
    expect((target.querySelector("#topic-name") as HTMLInputElement).value).toBe("Energy access");
    expect((target.querySelector("#topic-name") as HTMLInputElement).disabled).toBe(true);
    expect(TOPIC.t?.id).toBe(9);
    expect([...TOPIC.t!.ticked]).toEqual(ticked);
    const box = target.querySelector(".grp.props")!;
    expect(box.querySelector("h2")?.textContent).toBe("Proposed for “Energy access”");
    expect(box.querySelectorAll("li.row").length).toBe(2);
    expect((target.querySelector("#watch-continue") as HTMLButtonElement).textContent).toBe("Watch these and continue");
  }

  it("after a reload, step 2 reads setup's topic and its finished scout back from the server", async () => {
    const { target, done } = await reloaded({ "/api/topics": TOPICS, "/api/topics/9/scout": { job: { state: "done", result: { proposals: P, message: "2 proposed.", invalid: 1 } } } });
    shows(target, [11]);
    expect(target.querySelector(".box-b p.mt")?.textContent).toBe("2 places found. 1 could not be read and is not shown.");
    done();
  });

  it("after a reload with the server started again since, step 2 reads the topic's own rows", async () => {
    const gone = () => Promise.reject(new Error("this topic has no scout running or finished"));
    const { L, target, done } = await reloaded({ "/api/topics": TOPICS, "/api/topics/9/scout": gone, "/api/topics/9": { source_rows: P } });
    shows(target, [11]);
    expect(L.api).toHaveBeenCalledWith("/api/topics/9");
    expect(target.querySelector(".box-b p.mt")?.textContent).toBe("2 places found.");
    done();
  });

  it("after a reload during the scout, step 2 waits for it again and then shows its proposals", async () => {
    let polls = 0;
    const scout = () => (polls++ === 0 ? { job: { state: "running", elapsed_s: 40 } } : { job: { state: "done", result: { proposals: P, message: "2 proposed.", invalid: 0 } } });
    const { target, done } = await reloaded({ "/api/topics": TOPICS, "/api/topics/9/scout": scout });
    expect(target.querySelector("#scout-state h2")?.textContent).toBe("Finding places to read");
    expect(target.querySelector("#scout-elapsed")?.textContent).toMatch(/^Finding places to read… \(4\d s\)$/);
    await new Promise((r) => setTimeout(r, 1700));
    await settle();
    shows(target, [11]);
    done();
  });

  it("reads nothing back once setup is done", async () => {
    const { L } = stubbed();
    hosted();
    answering({ ...SETUP_TOPIC, [SETUP_API]: { topics: 1, done: true } });
    const { target, done } = await draw(Welcome, step());
    await settle();
    expect(L.api).not.toHaveBeenCalledWith("/api/topics");
    expect((target.querySelector("#topic-name") as HTMLInputElement).value).toBe("");
    done();
  });
});
