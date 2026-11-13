import { afterEach, describe, expect, it, vi } from "vitest";
import type { Facts } from "../../lib/app";
import { ui } from "../../lib/shell.svelte";
import { answering, draw, settle, stub, where } from "../testing.svelte";
import SpendList from "./SpendList.svelte";
import SpendPane from "./SpendPane.svelte";
import { CAPS, capValue, otherRows, planWords, searchLine, TOPICS, WATCH } from "./spend.svelte";

const T = { total_usd: 2, budget_usd: 10, topics: [{ id: 2, name: "Local-first", usd: 1.25, calls: 40 }], broad: { usd: 0, calls: 0 }, other: [], compacted_usd: 0 };
const W = { spent_usd: 2, monthly_usd: 10, alarm: false, alarm_fraction: 0.8, config: "/h/kranto.yaml", deep_dive: { daily_usd: 0.05, enabled: true } };
const hosted = () => { ui.facts = { header: { host: { paused: false } } } as unknown as Facts; };
afterEach(() => {
  for (const k of Object.keys(CAPS)) delete CAPS[k];
  ui.facts = null;
});

describe("Settings › Spend (the server's alone)", () => {
  it("reads a cap: dollars above 0, empty for none", () => {
    expect(capValue("x", 5)).toBe(5);
    expect(capValue("x", null)).toBeNull();
    CAPS.x = " 12.5 ";
    expect(capValue("x", 5)).toBe(12.5);
    CAPS.x = "-1";
    expect(() => capValue("x", 5)).toThrow("A cap is a number of dollars above 0, or empty for no cap.");
  });

  // the features that left (Invest, the radar) keep old rows in the ledger: never their raw names
  it("words other purposes: known ones, the retired ones as one row, an unknown one plainly", () => {
    const rows = otherRows([{ purpose: "news_brief", usd: 0.5, calls: 2 }, { purpose: "radar_propose", usd: 0.25, calls: 1 },
      { purpose: "invest_card", usd: 0.5, calls: 3 }, { purpose: "invest_event", usd: 0.25, calls: 1 }, { purpose: "some_new_thing", usd: 0.1, calls: 1 }]);
    expect(rows.map((r) => [r.word, r.usd, r.calls])).toEqual([["News briefs", 0.5, 2], ["Features that left Kranto", 1, 5], ["Some new thing", 0.1, 1]]);
    expect(JSON.stringify(rows.map((r) => r.word))).not.toMatch(/invest|radar|_/i);
  });

  it("says what live search cost this month, a line per backend, the free ones free", () => {
    const lines = [{ backend: "exa", label: "Exa, free mode (rate-limited, no account)", searches: 41, usd: 0, free: true },
      { backend: "hackernews", label: "Hacker News", searches: 1, usd: 0, free: true }];
    expect(searchLine({ monthly_usd: null, spent_usd: 0, capped: false, prices_as_of: "2026-10-17", lines }))
      .toBe("Exa, free mode (rate-limited, no account) 41 searches, free · Hacker News 1 search, free. Paid search $0.00 this month, no cap.");
    expect(searchLine({ monthly_usd: 5, spent_usd: 5.6, capped: true, prices_as_of: "2026-10-17", lines: [{ backend: "brave", label: "Brave Search", searches: 1120, usd: 5.6, free: false }] }))
      .toBe("Brave Search 1120 searches, $5.60. Paid search $5.60 this month: the cap of $5.00 is reached, so paid search waits until the first of next month.");
    expect(searchLine({ monthly_usd: null, spent_usd: 0, capped: false, prices_as_of: "2026-10-17", lines: [] })).toBeNull();
  });

  it("lists where it went by topic first, then watching's four caps in one group", async () => {
    stub();
    hosted();
    answering({ [TOPICS]: T, [WATCH]: W });
    const { target, done } = await draw(SpendList, where("settings/spend"));
    expect([...target.querySelectorAll(".grp h2")].map((h) => h.textContent)).toEqual(["By topic", "Caps"]);
    expect([...target.querySelectorAll(".grp .ghd .n")].map((n) => n.textContent)).toEqual(["$2.00 of $10.00", "4"]);
    expect(target.querySelector('[data-sel="t2"] .c-num')?.textContent).toBe("$1.25");
    expect([...target.querySelectorAll('[data-sel^="ecap:"] .r-title')].map((r) => r.textContent)).toEqual(
      ["Watching a month", "X a month", "Live search a month", "Deep dives a day"]);
    expect(target.querySelector('[data-sel="ecap:watch"] .c-meta')?.textContent).toBe("$10.00");
    expect(target.querySelector('[data-sel="ecap:x"] .c-meta')?.textContent).toBe("no cap · X is not connected");
    expect(target.textContent).not.toMatch(/\b[Bb]uilds?\b|[Pp]roject/);
    expect(target.querySelector("input")).toBeNull();
    done();
  });

  it("without the server says spend is the server's, and lists no cap", async () => {
    stub();
    answering({});
    const { target, done } = await draw(SpendList, where("settings/spend"));
    expect(target.querySelector("#sp-topic")?.closest("section")?.querySelector("p.more")?.textContent).toBe("Spend is the server's, which is not hosting this page.");
    expect(target.querySelectorAll('[data-sel^="ecap:"]').length).toBe(0);
    done();
  });

  it("with nothing selected, the pane is this month's totals", async () => {
    stub({ host: { spend_this_month_usd: 2, budget_usd: 10 } });
    hosted();
    answering({ [WATCH]: W });
    const { target, done } = await draw(SpendPane, where("settings/spend"));
    expect(target.querySelector(".toc")).toBeNull(); // one section: no outline
    expect([...target.querySelectorAll(".sec h3")].map((a) => a.textContent)).toEqual(["This month"]);
    expect(target.querySelector(".big")?.textContent).toBe("$2.00 of $10.00 this month");
    done();
  });

  it("saves watching's cap to the server and reads its status again; Undo writes it back; an old selection opens its cap", async () => {
    const L = stub({ host: { spend_this_month_usd: 2, budget_usd: 10 }, answer: { monthly_usd: null, config: "/h/kranto.yaml" } });
    Object.assign(L, { afkDrop: vi.fn(), loadHost: vi.fn(async () => {}) });
    hosted();
    answering({ [WATCH]: W });
    const { target, done } = await draw(SpendPane, where("settings/spend", "ecaps:watch"));
    expect(target.querySelector(".dt")?.textContent).toBe("Watching a month");
    expect(target.querySelector(".meter")?.getAttribute("aria-label")).toBe("20% of watching's monthly cap used");
    const month = target.querySelector("#cap-watch") as HTMLInputElement;
    month.value = "-1";
    month.dispatchEvent(new Event("input", { bubbles: true }));
    (target.querySelector("#save-cap") as HTMLButtonElement).click();
    await settle();
    expect(L.api).not.toHaveBeenCalled(); // a cap that is not one is refused
    month.value = "";
    month.dispatchEvent(new Event("input", { bubbles: true }));
    (target.querySelector("#save-cap") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith(WATCH, { monthly_usd: null });
    expect(L.loadHost).toHaveBeenCalled();
    expect(L.toast).toHaveBeenCalledWith("Saved: watching a month, no cap. Applies at once.", expect.any(Function));
    (L.toast.mock.lastCall![1] as () => void)();
    await settle();
    expect(L.api).toHaveBeenLastCalledWith(WATCH, { monthly_usd: 10 });
    expect(target.querySelector("#spend-x")).toBeNull(); // no X: no X line
    done();
  });

  it("shows X's reads as an estimate, and saves X's cap on its own", async () => {
    const L = stub({ host: { spend_this_month_usd: 2, budget_usd: 10 }, answer: { monthly_usd: 10, config: "/h/kranto.yaml" } });
    Object.assign(L, { afkDrop: vi.fn(), loadHost: vi.fn(async () => {}) });
    hosted();
    const x = { monthly_usd: null, spent_usd: 1.234, reads: 240, requests: 12, capped: false, connected: true, prices_as_of: "2026-10-17" };
    answering({ [WATCH]: { ...W, x } });
    const { target, done } = await draw(SpendPane, where("settings/spend", "ecap:x"));
    expect(target.querySelector("#spend-x")?.textContent).toBe("X reads: $1.23 this month (240 reads; an estimate at X's list price of 2026-10-17, the Developer Console is the bill), no cap.");
    const cap = target.querySelector("#cap-x") as HTMLInputElement;
    expect(cap.value).toBe("");
    cap.value = "30";
    cap.dispatchEvent(new Event("input", { bubbles: true }));
    (target.querySelector("#save-cap") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith(WATCH, { x_monthly_usd: 30 });
    done();
  });

  it("says a cap of what left is no cap at all", async () => {
    stub();
    hosted();
    answering({ [WATCH]: W });
    const { target, done } = await draw(SpendPane, where("settings/spend", "ecap:daily"));
    expect(target.querySelector(".pane-empty p")?.textContent).toBe("No such cap.");
    done();
  });

  it("says when the X cap holds X sources back", async () => {
    const { xLine } = await import("./spend.svelte");
    expect(xLine({ monthly_usd: 5, spent_usd: 5.1, reads: 1020, requests: 60, capped: true, connected: true, prices_as_of: "2026-10-17" }))
      .toContain("The cap of $5.00 is reached: X sources wait until the first of next month.");
    expect(xLine({ monthly_usd: null, spent_usd: 0, reads: 0, requests: 0, capped: false, connected: false, prices_as_of: "2026-10-17" })).toBeNull();
  });
});

describe("calls billed to a Claude plan", () => {
  it("say how many and what they would cost, and that the dollar cap leaves them out", () => {
    expect(planWords({ calls: 1234, equiv_usd: 9.8, last_limit_at: null })).toBe(
      "Your Claude plan is billed by usage, not dollars: this month 1,234 calls through Claude Code, about $9.80 at API list prices, included in your plan. The monthly cap counts dollars only.");
    expect(planWords({ calls: 2, equiv_usd: 0.004, last_limit_at: "2026-10-16T15:45:00Z" })).toContain(
      "A usage window last closed 2026-10-16 15:45 UTC; watching paused until it reopened.");
  });
});
