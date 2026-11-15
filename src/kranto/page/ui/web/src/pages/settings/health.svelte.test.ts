import { afterEach, describe, expect, it, vi } from "vitest";
import type { Facts } from "../../lib/app";
import { ui } from "../../lib/shell.svelte";
import { answering, draw, settle, stub, where } from "../testing.svelte";
import HealthList from "./HealthList.svelte";
import HealthPane from "./HealthPane.svelte";
import { HEALTH_API, pacedWord, SOURCES_API, type Health } from "./health";
import { answerDialog, dialogShown } from "../../ui/testing";

const NOW = new Date().toISOString();
// The server's /api/health whole (Health is generated from its web/types.py)
const D: Health = {
  month: "2026-10", tokens_month: { in: 1200000, out: 30000 }, spent_usd: 4, alarm: false, budget: { monthly_usd: 10, alarm_fraction: 0.8 },
  outcomes: { kept: 3, prefiltered: 12, near_duplicate: 1 }, exploration: [{ admitted_by: "topic", n: 4, mean_signal: 0.41, in_cross_source: 2 }],
  retention: { line: "90 days", last: { run_uuid: "c1", kind: "compact", status: "ok", started_at: "2026-10-14T02:59:00Z", finished_at: "2026-10-14T03:00:00Z",
    summary: { expired: 2, rollups: 1 }, error: null }, rollups: 3, replaced: 40, removed: [], last_purge: null },
  runs: [{ run_uuid: "r1", kind: "ingest", status: "ok", started_at: NOW, finished_at: NOW, error: null, tokens: null, summary: { contributed: 2, tokens: { in: 900, out: 100 },
    sources: [{ label: "HN", fetch_state: "paced", retry_at: null }] } }],
  errors: [{ purpose: "judge", http_status: 429, n: 2, last_at: NOW, example: "rate limited" }],
  messages: [{ id: 7, kind: "strike", dedup_key: "card:9", origin: "card", title: "A strike", body: "Something moved in local-first sync. More follows.",
    links: [], evidence_ids: [], created_at: NOW }],
  deliveries: {}, delivery_status: "on: ntfy",
  decisions: [{ decision_id: 3, candidate_id: 9, origin: "card", title: "Sync engines", promoted: 0, reason: "below_threshold", score: 0.3, threshold: 0.5,
    detail: "", message_id: null, subject_key: "c:9", decided_at: NOW, created_at: NOW }],
  strike: { max_per_week: 3, min_card_score: 0.5, min_burst_score: 0.6, min_watch_score: 0.4, refractory_days: 7, warmup_snapshots: 3, warmup_days: 3 },
  next_run: { ingest: null }, lanes: {}, models: { judge: "m" }, grade_labels: {}, paused: null, watch_paused: null, running: null, busy: false, can_run: true, api_key: true,
  ingest_progress: null,
  memory: { level: "ok", used_mb: 980, rss_mb: 700, high_mb: 3072, max_mb: 4096, group: "kranto.service", words: "Kranto uses 980 MB of its 3.0 GB MemoryHigh (kranto.service)" },
};
const SRCS = { sources: [{ id: 5, label: "Lobsters", review: "approved", status: "failing", failing_runs: 3, needs_fixing: true, last_error: "HTTP 500" },
                         { id: 6, label: "Fine", review: "approved", status: "ok" }] };
const hosted = () => { ui.facts = { header: { host: { paused: false } } } as unknown as Facts; };
afterEach(() => { ui.facts = null; });

describe("a provider's pause", () => {
  afterEach(() => { ui.facts = null; });
  it("says until when, and Resume now ends it", async () => {
    const L = stub({ answer: { ok: true, was_paused: true } });
    const afkDrop = vi.fn();
    Object.assign(L, { afkDrop });
    hosted();
    answering({ [HEALTH_API]: { ...D, watch_paused: { until: "2026-11-01T00:00:00Z", reason: "spend limit set in the Claude Console reached: You have reached your specified API usage limits", provider: "anthropic" } }, [SOURCES_API]: SRCS });
    const { target, done } = await draw(HealthPane, where("settings/health"));
    expect(target.querySelector(".dk .gl")?.getAttribute("title")).toBe("Paused");
    expect(target.textContent).toContain("Watching paused until 2026-11-01 00:00 (spend limit set in the Claude Console reached); it resumes by itself");
    (target.querySelector("#resume-watch") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/watch/resume", {});
    expect(afkDrop).toHaveBeenCalled();
    expect(L.say).toHaveBeenCalledWith("Watching goes on at its next run.");
    done();
  });
});

describe("Settings › System › Health", () => {
  it("says when a paced source is read again", () => {
    expect(pacedWord(null)).toBe("paced, retrying at the next run");
  });

  it("without the server says what needs the server, and lists nothing else", async () => {
    stub();
    answering({});
    const { target, done } = await draw(HealthList, where("settings/health"));
    expect(target.querySelector('[data-sel="eloop"]')).toBeNull();
    expect(target.querySelector(".flash strong")?.textContent).toBe("Watching's health needs the server. ");
    expect(target.querySelectorAll("li.row").length).toBe(0);
    done();
  });

  it("lists what Kranto did, the sources needing a look, runs, errors, messages and the gate", async () => {
    stub();
    hosted();
    answering({ [HEALTH_API]: D, [SOURCES_API]: SRCS });
    const { target, done } = await draw(HealthList, where("settings/health"));
    expect([...target.querySelectorAll(".grp h2")].map((h) => h.textContent)).toEqual(["Watching", "Sources needing a look", "Runs", "Model errors in the last 7 days", "Messages", "Strike gate"]);
    expect(target.querySelector('[data-sel="ecalls"] .c-meta')?.textContent).toBe("1.2M tokens · 40% of the monthly cap");
    expect(target.querySelector('[data-sel="s5"] .c-meta')?.textContent).toBe("failing 3 runs in a row · fix it or remove it · HTTP 500");
    expect(target.querySelector('[data-sel="erun:r1"] .r-title')?.textContent).toBe("2 new observations");
    expect(target.querySelector('[data-sel="emsg:7"] .c-meta')?.textContent).toBe("Something moved in local-first sync.");
    expect(target.querySelector(".grade")).toBeNull(); // a message has no grade
    expect(target.querySelector('[data-sel="edec:3"] .c-meta')?.textContent).toBe("0.300 / 0.500 · below threshold");
    done();
  });

  it("words each run: its job in words, a skip with its reason, never the job's id or the state twice (QA B8)", async () => {
    stub();
    hosted();
    const run = (kind: string, status: string, summary: Record<string, unknown>) => ({ run_uuid: kind, kind, status, started_at: NOW, finished_at: NOW, error: null, tokens: null, summary });
    answering({ [HEALTH_API]: { ...D, runs: [run("invest.mark", "skipped", { why: "halted" }), run("news.brief", "skipped", { briefs: 0, not_due: [3] }), run("toot.weekly", "skipped", {})] }, [SOURCES_API]: SRCS });
    const { target, done } = await draw(HealthList, where("settings/system"));
    const rows = [...target.querySelectorAll('[data-sel^="erun:"]')];
    expect(rows.map((r) => [r.querySelector(".r-title")?.textContent, r.querySelector(".kindtag")?.textContent])).toEqual([
      ["skipped: halted", "A feature that left Kranto"], ["skipped: nothing was due", "News: brief"], ["skipped: nothing to do", "Toot: weekly"]]);
    expect(target.querySelector("#h-runs")?.textContent).not.toMatch(/\b[a-z]+\.[a-z_]+\b/);
    done();
  });

  it("runs ingest now from the pane with nothing selected", async () => {
    const L = stub();
    const hostForm = vi.fn(async () => null), afkDrop = vi.fn();
    Object.assign(L, { hostForm, afkDrop });
    hosted();
    answering({ [HEALTH_API]: D });
    const { target, done } = await draw(HealthPane, where("settings/health"));
    expect(target.querySelector(".dt")?.textContent).toBe("What Kranto did");
    (target.querySelector("#run-ingest") as HTMLButtonElement).click();
    expect(dialogShown()?.title).toBe("Run ingest now?");
    expect(hostForm).not.toHaveBeenCalled();             // it spends: the dialog says so first
    answerDialog(true);
    await settle();
    expect(hostForm).toHaveBeenCalledWith("/run/ingest");
    expect(afkDrop).toHaveBeenCalled();
    expect(L.say).toHaveBeenCalledWith("Started an ingest run: Activity shows it while it runs.");
    done();
  });

  it("opens a run with its sources, and a message in the old module's pane", async () => {
    const L = stub();
    Object.assign(L, { sticky: vi.fn((el: HTMLElement, id: string) => { el.id = id; return el; }) });
    hosted();
    answering({ [HEALTH_API]: D });
    const run = await draw(HealthPane, where("settings/health", "erun:r1"));
    expect(run.target.querySelector(".dt")?.textContent).toBe("ingest " + NOW.replace("T", " ").slice(0, 16));
    expect(run.target.querySelector("details#run-r1 .ctx .n")?.textContent).toBe("paced, retrying at the next run");
    run.done();
    // 2b: under the doors a run is Settings › System's row (sel=erun:…), its trace one click on
    stub();
    hosted();
    const sys = await draw(HealthPane, where("settings/system", "erun:r1"));
    expect(sys.target.querySelector("#run-trace")?.getAttribute("href")).toBe("#/afk/r1/trace");
    sys.done();
    // a message's pane is Needs you's (pages/front/MessagePane), with its delivery and no link to Health
    stub();
    hosted();
    const { target, done } = await draw(HealthPane, where("settings/health", "emsg:7"));
    expect(target.querySelector(".pane-in")?.getAttribute("data-title")).toBe("A strike");
    expect(target.querySelector(".gh, .grade")).toBeNull();
    expect(target.querySelector("#s-delivery p")?.textContent).toBe("on: ntfy");
    expect(target.querySelector("p.mt")).toBeNull();
    done();
  });
});

describe("memory and the read in progress (MEM)", () => {
  const P = { run_uuid: "r9", started_at: NOW, sources: 8, source_index: 3, source: "www.inkandswitch.com", items: 40, item: 12, done_items: 52, kept: 5 };
  const HIGH = { ...D.memory, level: "high" as const, used_mb: 2765, words: "Kranto uses 2.7 GB of its 3.0 GB MemoryHigh (kranto.service); above it the system slows kranto down" };

  it("lists the memory row, and the read in progress while there is one", async () => {
    stub();
    hosted();
    answering({ [HEALTH_API]: { ...D, ingest_progress: P }, [SOURCES_API]: SRCS });
    const { target, done } = await draw(HealthList, where("settings/health"));
    expect(target.querySelector('[data-sel="ememory"] .c-meta')?.textContent).toBe("980 MB of 3.0 GB (the high mark; 4.0 GB at most)");
    expect(target.querySelector('[data-sel="ereading"] .c-meta')?.textContent).toBe("source 3 of 8, www.inkandswitch.com · 12 of 40 items · 5 kept so far");
    expect(target.querySelector("#mem-high")).toBeNull();
    done();
  });

  it("says when memory is high, at the top of System", async () => {
    stub();
    hosted();
    answering({ [HEALTH_API]: { ...D, memory: HIGH }, [SOURCES_API]: SRCS });
    const { target, done } = await draw(HealthList, where("settings/health"));
    expect(target.querySelector("#mem-high")?.textContent).toBe("Memory is high. " + HIGH.words);
    expect(target.querySelector('[data-sel="ememory"] .gl')?.getAttribute("title")).toBe("High");
    expect(target.querySelector('[data-sel="ereading"]')).toBeNull();
    done();
  });

  it("the memory pane gives the figures and how to change the caps", async () => {
    stub();
    hosted();
    answering({ [HEALTH_API]: { ...D, memory: HIGH }, [SOURCES_API]: SRCS });
    const { target, done } = await draw(HealthPane, where("settings/health", "ememory"));
    expect(target.querySelector(".big")?.textContent).toBe("2.7 GB of 3.0 GB (the high mark; 4.0 GB at most)");
    expect(target.querySelector(".note.c-amber")?.textContent).toBe(HIGH.words);
    expect(target.textContent).toContain("systemctl --user edit Kranto");
    done();
  });
});
