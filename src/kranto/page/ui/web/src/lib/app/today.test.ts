// Needs you's and Updates' parts of the app (chrome.ts, route.ts, data.ts): the navigator's Needs
// you count, Needs you's pane beside any list, the header's pill at each step of an update and the
// 5 s watch while one runs.
import { afterEach, describe, expect, it, vi } from "vitest";
import "../../pages"; // the pages, registered as the shell does
import { obsQuery } from "../../pages/library/library";
import { onPageLoaded } from "../pages.svelte";
import { parse } from "../router";
import { chromeFacts, navTree } from "./chrome";
import { loadHost } from "./data";
import { render } from "./route";
import { card, frame, hostStatus, tick, unframe } from "./testing";

afterEach(unframe);
onPageLoaded(() => { if (typeof document !== "undefined" && document.getElementById("rows")) render(); }); // a page's chunk arrives: drawn again (main.ts), while the frame is there
const TODAY = { since: null, ingest: { last: null, judge_calls_24h: 0, judge_errors_24h: 0, sources: 1, topics: 1, observations: 10 },
  topics: [{ id: 1, name: "Clinics", new_kept: 0, proposed: 2, proposed_ticked: [] }],
  messages: [{ id: 5, title: "A strike", kind: "strike", body: "", evidence_ids: [], created_at: "2026-11-01T08:00:00Z" }], sources_failing: [] };
const upd = (o: object) => hostStatus({ update: { ...hostStatus().update, ...o } });
/** no update running: the 5 s watch an earlier frame started is stopped */
async function idle(): Promise<void> {
  await frame();
  await loadHost();
}

describe("Needs you in the frame", () => {
  it("counts Needs you's rows on the navigator", async () => {
    await frame({ host: upd({ available: "0.3.75" }), reads: { "/api/today": TODAY, "/api/ideas?embedding=ref": { ideas: [card(1)] } } });
    navTree(parse());
    await tick();
    // the idea cards (one row), the update, a topic's proposals and a message
    expect(navTree(parse()).rows.find((x) => x.to === "needs" && !x.head)?.n).toBe(4);
  });

  it("draws a message's row in Needs you's pane beside any list, and a card away from its home", async () => {
    await frame({ hash: "#/needs?sel=m5", reads: { "/api/today": TODAY, "/api/ideas?embedding=ref": { ideas: [card(1)] } } });
    render();
    await vi.waitFor(() => expect(document.querySelector("#dscroll")?.textContent).toContain("A strike"));
    history.replaceState(null, "", "#/needs?sel=i1");
    render();
    await vi.waitFor(() => expect(document.querySelector("#dscroll .dt")?.textContent).toBe("Card 1"));
  });

  it("filters the library by a Parallax theme", () => {
    expect(obsQuery({ theme: "L1" }).path).toBe("/api/observations?theme=L1&sort=new&limit=100&offset=0");
  });
});

describe("an update in the frame", () => {
  it("says each step of a running update on the header's pill", async () => {
    const steps: Record<string, string> = { requested: "starting", draining: "waiting for a job to finish", backing_up: "backing up", stopping: "stopping Kranto",
      installing: "installing", starting: "starting the new version", verifying: "checking the new version", rolling_back: "rolling back" };
    for (const [state, word] of Object.entries(steps)) {
      await frame({ host: upd({ state, to: "0.3.75" }) });
      expect(chromeFacts(parse())?.header.update).toMatchObject({ word: "Updating", detail: word });
    }
    await idle();
  });

  it("reads the server's status every 5 s while an update runs, and stops once it is over", async () => {
    await idle();
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    try {
      const net = await frame({ host: upd({ state: "installing", to: "0.3.75" }) });
      await loadHost(); // the first read after the frame finds the update running
      const reads = () => net.calls.filter(([u]) => u === "/api/status").length;
      const before = reads();
      vi.advanceTimersByTime(5000);
      await tick();
      expect(reads()).toBe(before + 1);
      net.answer["/api/status"] = upd({ state: "done" });
      vi.advanceTimersByTime(5000);
      await tick();
      expect(reads()).toBe(before + 2);
      vi.advanceTimersByTime(15000);
      await tick();
      expect(reads()).toBe(before + 2);
    } finally {
      vi.useRealTimers();
    }
  });
});
