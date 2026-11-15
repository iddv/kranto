import { flushSync, mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Listing, Session } from "./api";
import { socketUrl, TermSocket, type SocketEvent } from "./socket";
import TerminalPanel from "./TerminalPanel.svelte";
import { clampTermw, loadTermw, setTermw, TERMW_KEY, TERMW_MIN, termwNow } from "./TermSplit.svelte";

describe("the terminal's socket", () => {
  it("sits under the page's own prefix, ws or wss as the page, with the ticket", () => {
    const at = (href: string) => ({ href, protocol: new URL(href).protocol }) as Location;
    // the document drawn at / under Kranto's server: the socket keeps the page's prefix
    expect(socketUrl("c3f1a9e2", "a/b", at("http://localhost:18765/#/ideas"), "/brb/")).toBe(
      "ws://localhost:18765/brb/term/ws/c3f1a9e2?ticket=a%2Fb",
    );
    // The page's small server alone: its prefix is /
    expect(socketUrl("c3f1a9e2", "t", at("https://h.example/"), "/")).toBe(
      "wss://h.example/term/ws/c3f1a9e2?ticket=t",
    );
  });

  it("sends keys and sizes as JSON and tells exit, dropped and bytes apart", () => {
    const sent: string[] = [];
    const fake = { readyState: 1, send: (s: string) => sent.push(s), close() {} } as unknown as WebSocket & {
      onmessage: (m: { data: unknown }) => void;
    };
    const got: SocketEvent[] = [];
    const s = new TermSocket("ws://x", (e) => got.push(e), () => fake);
    s.open();
    s.input("ls\r");
    s.resize(80, 24);
    expect(sent.map((x) => JSON.parse(x))).toEqual([
      { t: "in", d: "ls\r" },
      { t: "resize", cols: 80, rows: 24 },
    ]);
    fake.onmessage({ data: new Uint8Array([104, 105]).buffer });
    fake.onmessage({ data: '{"t":"dropped"}' });
    fake.onmessage({ data: '{"t":"exit","code":0}' });
    expect(got[0]).toEqual({ kind: "data", bytes: new Uint8Array([104, 105]) });
    expect(got.slice(1)).toEqual([{ kind: "dropped" }, { kind: "exit", code: 0 }]);
  });
});

const listing = (over: Partial<Listing> = {}, sessions: Session[] = []): Listing => ({
  sessions,
  enabled: true,
  available: true,
  why: null,
  sandboxed: true,
  max_sessions: 3,
  running: 0,
  socket: true,
  ...over,
});

const ended = (over: Partial<Session> = {}): Session => ({
  tid: "c3f1a9e2",
  subject: { kind: "idea", id: "3" },
  title: "Card 3",
  state: "ended",
  reason: "idle",
  words: "Ended after 60 minutes idle",
  usd: 0.12,
  tokens: { in: 1, out: 1 },
  sandboxed: true,
  cwd: "/x",
  branch: "term/c3f1a9e2",
  session: "s",
  net: { allowed: [], asked: [] },
  proposals: [],
  ...over,
});

function draw(answers: Record<string, unknown>) {
  const posts: { path: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "POST") posts.push({ path, body: JSON.parse(String(init.body)) });
      const key = Object.keys(answers).find((k) => path.startsWith(k));
      return new Response(JSON.stringify(key ? answers[key] : {}), { status: 200 });
    }),
  );
  const target = document.createElement("div");
  document.body.append(target);
  const c = mount(TerminalPanel, { target, props: { subject: { kind: "idea", id: "3" }, title: "Card 3" } });
  return { target, posts, done: () => unmount(c) };
}

const settle = async () => {
  for (let i = 0; i < 5; i++) await new Promise((r) => setTimeout(r, 0));
  flushSync();
};

afterEach(() => vi.unstubAllGlobals());

describe("the panel", () => {
  it("says why it is not offered", async () => {
    const d = draw({ "api/term": listing({ available: false, why: "needs a Claude token" }) });
    await settle();
    expect(d.target.textContent).toContain("needs a Claude token");
    d.done();
  });

  it("asks before it bills the watcher's API key, and Use the API key keeps the choice", async () => {
    const why = "Claude Code here would bill your Claude API key (the watcher's). Run `claude setup-token` to use your Claude plan, or choose Use the API key.";
    const d = draw({ "api/term": listing({ available: false, why, ask: "api_key" }) });
    await settle();
    expect(d.target.textContent).toContain(why);
    (d.target.querySelector("#term-use-key") as HTMLButtonElement).click();
    await settle();
    expect(d.posts).toEqual([{ path: "api/term/settings", body: { key: "term.allow_api_key", value: true } }]);
    d.done();
    const plain = draw({ "api/term": listing({ available: false, why: "needs a Claude token" }) });
    await settle();
    expect(plain.target.querySelector("#term-use-key")).toBeNull();
    plain.done();
  });

  it("says what a session runs on and the Claude API's refusal", async () => {
    const d = draw({ "api/term": listing({}, [ended({ on: "on your Claude API key (the watcher's), Sonnet 5", refused: "Credit balance is too low" })]) });
    await settle();
    expect(d.target.querySelector("#term-on")?.textContent).toBe("· on your Claude API key (the watcher's), Sonnet 5");
    expect(d.target.querySelector("#term-refused")?.textContent?.replace(/\s+/g, " ")).toBe(
      "The Claude API refused this session's last request: Credit balance is too low");
    d.done();
  });

  it("says brb ui alone has no terminal", async () => {
    const d = draw({ "api/term": listing({ socket: false }) });
    await settle();
    expect(d.target.textContent).toContain("needs Kranto itself");
    d.done();
  });

  it("offers Open again for an ended session, with its words and cost in the head", async () => {
    const d = draw({ "api/term": listing({}, [ended()]) });
    await settle();
    expect(d.target.textContent).toContain(
      "Ended after 60 minutes idle. Open again resumes the conversation.",
    );
    expect(d.target.textContent).toContain("$0.12");
    expect(d.target.textContent).toContain("about Card 3");
    // 2c: its trace is a click away before it is opened again
    expect(d.target.querySelector("#term-trace")?.getAttribute("href")).toBe("#/sessions/c3f1a9e2/trace");
    d.done();
  });

  it("says why a session ended when it was killed", async () => {
    const words = "The session was stopped unexpectedly (signal 9)";
    const d = draw({ "api/term": listing({}, [ended({ reason: "exit", words })]) });
    await settle();
    expect(d.target.textContent).toContain(`${words}. Open again resumes the conversation.`);
    d.done();
  });

  it("shows a proposal as a card, the session's words fenced, and Confirm answers it", async () => {
    const p = {
      n: 1, kind: "close", title: "Close", confirm_class: true,
      subject: { kind: "idea", id: "3" }, fields: { reason: "done" },
      why: "the README says so", status: "proposed", result: null,
    } as const;
    const d = draw({ "api/term/answer": { proposal: p }, "api/term": listing({}, [ended({ proposals: [p] })]) });
    await settle();
    const card = d.target.querySelector(".term-card")!;
    expect(card.textContent).toContain("Close");
    expect(card.textContent).toContain("can't be taken back");
    expect(card.querySelector(".why")!.textContent).toContain("The session says:");
    expect(card.querySelector(".fields")!.textContent).toContain('"reason": "done"');
    (card.querySelector("button.primary") as HTMLButtonElement).click();
    await settle();
    expect(d.posts).toEqual([{ path: "api/term/answer", body: { tid: "c3f1a9e2", n: 1, confirm: true } }]);
    d.done();
  });

  it("asks about a host the session was refused, for this session only", async () => {
    const d = draw({ "api/term/net": ended(), "api/term": listing({}, [ended({ net: { allowed: [], asked: ["pypi.org"] } })]) });
    await settle();
    const allow = [...d.target.querySelectorAll("button")].find((b) => b.textContent?.includes("Allow pypi.org"))!;
    allow.click();
    await settle();
    expect(d.posts[0]).toEqual({ path: "api/term/net", body: { tid: "c3f1a9e2", host: "pypi.org", allow: true } });
    d.done();
  });

  it("warns in one line when the machine has no sandbox", async () => {
    const d = draw({ "api/term": listing({}, [ended({ sandboxed: false })]) });
    await settle();
    expect(d.target.querySelector(".term-warn")!.textContent!.replace(/\s+/g, " ")).toContain("without Kranto's sandbox");
    d.done();
  });
});

describe("the focus split's splitter", () => {
  afterEach(() => { localStorage.clear(); document.documentElement.style.removeProperty("--termw"); });
  it("keeps the width within 360 px and 70% of the window, per browser, as one CSS variable", () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 1400 });
    expect(clampTermw(100)).toBe(TERMW_MIN);
    expect(clampTermw(5000)).toBe(980);
    expect(termwNow()).toBe(560); // 40% until dragged
    setTermw(700, false);
    expect(document.documentElement.style.getPropertyValue("--termw")).toBe("700px");
    expect(localStorage.getItem(TERMW_KEY)).toBeNull(); // a drag in progress saves nothing
    setTermw(720, true);
    expect(localStorage.getItem(TERMW_KEY)).toBe("720");
    document.documentElement.style.removeProperty("--termw");
    loadTermw();
    expect(termwNow()).toBe(720);
    setTermw(null, true); // a double-click: back to 40%
    expect(localStorage.getItem(TERMW_KEY)).toBeNull();
    expect(termwNow()).toBe(560);
  });
});
