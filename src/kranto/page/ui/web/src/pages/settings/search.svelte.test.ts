import { afterEach, describe, expect, it } from "vitest";
import type { Facts } from "../../lib/app";
import { ui } from "../../lib/shell.svelte";
import { answering, draw, settle, stub, where } from "../testing.svelte";
import SearchList from "./SearchList.svelte";
import WatchingPane from "./WatchingPane.svelte";
import { CALLERS_API, callersLine, SEARCH_API, SEARCH_FORM, searchWords, weeksValue, type SearchSetup } from "./search.svelte";

// The server's /api/setup/search (SearchSetup is generated from its web/types.py): Exa's free mode
const NO = "no live search: results are from model memory and may be stale";
const S: SearchSetup = {
  provider: "exa", web: "exa", web_label: "Exa, free mode (rate-limited, no account)", free_mode: true, free: ["hackernews", "github", "arxiv"], note: null,
  monthly_usd: null, callers: { scout: "on", cards: "on", editor: "on", research: "agent", resolve: "failed_lines", pitch: "on", evolve: "on", sources: "on" }, failing: {},
  choices: [{ provider: "exa", label: "Exa", key_env: "EXA_API_KEY", key_set: false }, { provider: "brave", label: "Brave Search", key_env: "BRAVE_API_KEY", key_set: false },
    { provider: "tavily", label: "Tavily", key_env: "TAVILY_API_KEY", key_set: false }, { provider: "anthropic", label: "Anthropic web search (the watcher's Claude API key)", key_env: null, key_set: null },
    { provider: "none", label: "None: no live search", key_env: null, key_set: null }],
  free_mode_words: "Exa's free mode: rate-limited, no account; add a key from a free Exa account ($10 of credit a month) for your own limits",
  recent_weeks: 12, cache_hours: 24, month: {}, no_search: NO,
};
const hosted = () => { ui.facts = { header: { host: { paused: false } } } as unknown as Facts; };
afterEach(() => {
  ui.facts = null;
  SEARCH_FORM.provider = null;
  SEARCH_FORM.callers = {};
  SEARCH_FORM.weeks = null;
});
const pick = (el: Element | null, v: string) => {
  const s = el as HTMLSelectElement;
  s.value = v;
  s.dispatchEvent(new Event("change", { bubbles: true }));
};

describe("Settings › Watching › Live search", () => {
  it("words the backend, the callers and the weeks", () => {
    expect(searchWords(S)).toEqual({ st: ["check", "green", "Ok"], line: "Exa, free mode (rate-limited, no account). With Hacker News, GitHub, arXiv, always free." });
    expect(searchWords({ ...S, failing: { exa: 3 } }).st[2]).toBe("Needs you");
    expect(searchWords({ ...S, web: null, web_label: null, free: [] })).toEqual({ st: ["skipped", "grey", "Off"], line: `None. Every caller says "${NO}".` });
    expect(callersLine(S.callers)).toBe("all on");
    expect(callersLine({ ...S.callers, scout: "off", research: "off" })).toBe("off: The scout, The research desk");
    expect(weeksValue(" 26 ")).toBe(26);
    expect(() => weeksValue("0")).toThrow("Recent is a whole number of weeks from 1 to 520.");
    expect(() => weeksValue("2.5")).toThrow();
  });

  it("lists three rows, no field, and nothing without the server", async () => {
    stub();
    hosted();
    answering({ [SEARCH_API]: S });
    const { target, done } = await draw(SearchList, where("settings/watching"));
    expect(target.querySelector(".grp h2")?.textContent).toBe("Live search");
    const rows = [...target.querySelectorAll("li.row")];
    expect(rows.map((r) => r.getAttribute("data-sel"))).toEqual(["esearch", "esearch:callers", "esearch:weeks"]);
    expect(rows[0]?.querySelector(".c-meta")?.textContent).toBe("Exa, free mode (rate-limited, no account). With Hacker News, GitHub, arXiv, always free.");
    expect(rows[1]?.querySelector(".c-meta")?.textContent).toBe("all on");
    expect(target.querySelector("input, select")).toBeNull();
    done();
    ui.facts = null;
    const none = await draw(SearchList, where("settings/watching"));
    expect(none.target.querySelector(".grp")).toBeNull();
    none.done();
  });

  it("tests and keeps a backend with its key once, clears the field and keeps nothing of it", async () => {
    const L = stub({ answer: { ok: true, test: { ok: true, detail: "3 results" } } });
    hosted();
    answering({ [SEARCH_API]: S });
    const { target, done } = await draw(WatchingPane, where("settings/watching", "esearch"), "#/settings/watching");
    expect(target.querySelector(".dk")?.textContent).toBe(" watching · live search");
    expect(target.querySelector("#s-now")?.textContent).toContain("Exa's free mode: rate-limited, no account");
    const key = target.querySelector("#search-key") as HTMLInputElement;
    expect(key.type).toBe("password");
    // Brave with no key set: the action waits for one
    pick(target.querySelector("#search-provider"), "brave");
    await settle();
    expect(SEARCH_FORM.provider).toBe("brave");
    (target.querySelector("#search-save") as HTMLButtonElement).click();
    expect(L.api).not.toHaveBeenCalled();
    key.value = "  a-pasted-value  ";
    (target.querySelector("#search-save") as HTMLButtonElement).click();
    expect(key.value).toBe("");
    await settle();
    expect(L.api).toHaveBeenCalledWith(SEARCH_API, { provider: "brave", key: "a-pasted-value" });
    expect(L.toast).toHaveBeenCalledWith("Saved: live search with Brave Search, 3 results; the key is kept in this workspace's .env (readable by you only). Applies at once.", expect.any(Function));
    expect(SEARCH_FORM.provider).toBeNull();
    expect(new XMLSerializer().serializeToString(target)).not.toContain("a-pasted-value");
    // Undo goes back to Exa, with no key
    L.api.mockClear();
    (L.toast.mock.calls[0]![1] as () => void)();
    await settle();
    expect(L.api).toHaveBeenCalledWith(SEARCH_API, { provider: "exa" });
    done();
  });

  it("None says the sentence; Exa needs no key", async () => {
    const L = stub({ answer: { ok: true, test: { ok: true, detail: "no live search" } } });
    hosted();
    answering({ [SEARCH_API]: S });
    const { target, done } = await draw(WatchingPane, where("settings/watching", "esearch"), "#/settings/watching");
    (target.querySelector("#search-save") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith(SEARCH_API, { provider: "exa" });
    pick(target.querySelector("#search-provider"), "none");
    await settle();
    expect(target.querySelector("#search-key")).toBeNull();
    expect(target.textContent).toContain(`Every caller then says "${NO}".`);
    done();
  });

  it("writes the callers' switches", async () => {
    const L = stub({ answer: { ok: true } });
    hosted();
    answering({ [SEARCH_API]: { ...S, recent_weeks: 26 } });
    const c = await draw(WatchingPane, where("settings/watching", "esearch:callers"), "#/settings/watching");
    expect([...c.target.querySelectorAll("select")].map((s) => s.id)).toEqual(["search-scout", "search-cards", "search-editor", "search-research", "search-resolve", "search-pitch", "search-evolve", "search-sources"]);
    pick(c.target.querySelector("#search-scout"), "off");
    await settle();
    (c.target.querySelector("#search-callers-save") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith(CALLERS_API, { callers: { ...S.callers, scout: "off" } });
    expect(L.toast).toHaveBeenCalledWith("Saved: who searches, off: The scout. From the next run.", expect.any(Function));
    c.done();
  });

  it("writes the weeks, and goes back to the default", async () => {
    const L = stub({ answer: { ok: true } });
    hosted();
    answering({ [SEARCH_API]: { ...S, recent_weeks: 26 } });
    const w = await draw(WatchingPane, where("settings/watching", "esearch:weeks"), "#/settings/watching");
    const weeks = w.target.querySelector("#search-weeks") as HTMLInputElement;
    expect(weeks.value).toBe("26");
    weeks.value = "8";
    weeks.dispatchEvent(new Event("input", { bubbles: true }));
    (w.target.querySelector("#search-weeks-save") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenLastCalledWith(CALLERS_API, { recent_weeks: 8 });
    expect(L.toast).toHaveBeenLastCalledWith("Saved: recent means the last 8 weeks. From the next run.", expect.any(Function));
    (w.target.querySelector('[data-act="default"]') as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenLastCalledWith(CALLERS_API, { recent_weeks: 12 });
    w.done();
  });
});
