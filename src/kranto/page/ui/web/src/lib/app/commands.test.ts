// ⌘K's items (commands.ts) and Settings › Prompts' preview subjects.
import { afterEach, describe, expect, it } from "vitest";
import "../../pages"; // the pages, registered as the shell does
import { render } from "./route";
import { palItems, previewSubjects } from "./commands";
import { card, frame, hostStatus, tick, unframe } from "./testing";

afterEach(unframe);
const titles = (xs: { title: string }[]) => xs.map((x) => x.title);
const IDEAS = "/api/ideas?embedding=ref";

describe("the commands, with nothing typed", () => {
  it("go to every page, scout a topic, Pause, the themes, the layout and the keys", async () => {
    await frame();
    const c = palItems("", null);
    expect(c.every((x) => x.g === "Commands" && x.score === 1)).toBe(true);
    const t = titles(c);
    for (const w of ["Go to Needs you", "Go to Topics", "Add topic", "Go to Clinics", "Go to Clinics › Sources", "Go to Clinics › Map", "Go to Appearance",
                     "Scout more for Clinics", "Pause", "Switch to dark", "Theme: Plum", "Theme: Custom", "Layout: collapse the navigator", "Keyboard shortcuts"]) expect(t).toContain(w);
    for (const w of ["Go to Builds", "Go to Projects", "New idea", "Settings › Publishing › GitHub"]) expect(t).not.toContain(w);
    expect(c.find((x) => x.title === "Go to Needs you")).toMatchObject({ go: "#/needs", keys: "g t" });
    expect(c.find((x) => x.title === "Pause")?.detail).toBe("reading sources and writing ideas");
    expect(t).not.toContain("Mark all seen"); // only where the page has ⇧a
  });

  it("find a topic's own Sources by the word", async () => {
    await frame();
    const found = palItems("sources clin", null).filter((x) => x.title.includes("› Sources"));
    expect(found.map((x) => [x.title, x.go])).toEqual([["Go to Clinics › Sources", "#/topics/1/sources"]]);
  });

  it("name the selected card's verbs, as ⋯ and its keys have them", async () => {
    await frame({ hash: "#/ideas/3", reads: { [IDEAS]: { ideas: [card(3)] } } });
    render();
    await tick();
    const t = titles(palItems("", null));
    expect(t).toContain("Card 3: Pass");
    expect(t).toContain("Card 3: Open in Claude Code");
  });

  it("offer Post and no Arrange or Cubs: the home is one order, the cubs are Post's", async () => {
    const shell = { layout: "new", pins: [], hidden: [], needs_cap: 3, new_cap: 4, pins_max: 6, cubs: [] };
    await frame({ hash: "#/needs", reads: { "/api/shell": { ...shell, widgets: [{ n: 0, id: "needs", known: true }], custom: false } } });
    palItems("", null);
    await tick();
    const c = titles(palItems("", null));
    expect(c).toContain("Post");
    expect(c).not.toContain("Arrange the home");
    expect(c).not.toContain("Add a widget");
    expect(c).not.toContain("Cubs");
  });

  it("say Resume while paused, and run it", async () => {
    await frame({ host: hostStatus({ paused: "by hand" }) });
    const r = palItems("", null).find((x) => x.title === "Resume")!;
    expect(r.detail).toBe("reading sources and writing ideas");
    expect(typeof r.run).toBe("function");
  });
});

describe("a search", () => {
  it("finds the cards and topics, and the server's evidence and sources a step under", async () => {
    await frame({ reads: { [IDEAS]: { ideas: [card(1, "waiting", { title: "Plotting tool" })] } } });
    palItems("plot", null);
    await tick();
    const srv = { query: "plot", results: [{ kind: "observation", id: 5, title: "Plot charts", detail: "hn", score: 0.5 }, { kind: "source", id: 3, title: "Plot feed", detail: "rss" }] };
    const items = palItems("plot", srv);
    const g = (x: string) => items.filter((i) => i.g === x);
    expect(g("Ideas")[0]).toMatchObject({ title: "Plotting tool", detail: "#1 · Waiting", go: "#/ideas/1" });
    expect(g("Evidence")[0]).toMatchObject({ title: "Plot charts", detail: "#5 · hn", go: "#/library/o/5" });
    expect(g("Sources")[0]).toMatchObject({ go: "#/settings/sources/3" });
    expect(items.some((i) => i.g === "Builds" || i.g === "Projects")).toBe(false);
    // The server's half for another query is not mixed in
    expect(palItems("plot", { query: "plo", results: srv.results }).some((i) => i.g === "Evidence")).toBe(false);
  });
});

describe("the prompts' preview subjects", () => {
  it("are the cards, the topics and the newest observations", async () => {
    await frame({
      reads: { [IDEAS]: { ideas: [card(4)] }, "/api/observations?limit=20&sort=new": { results: [{ id: 9, summary: "A long first sentence about clinics. And more." }] } },
    });
    previewSubjects({ id: "card", subject: "idea" });
    await tick();
    expect(previewSubjects({ id: "card", subject: "idea" })).toEqual([["4", "#4 Card 4"]]);
    expect(previewSubjects({ id: "judge", subject: "topic" })).toEqual([["1", "Clinics"], ["2", "Local-first"]]);
    previewSubjects({ id: "judge", subject: "observation" });
    await tick();
    expect(previewSubjects({ id: "judge", subject: "observation" })).toEqual([["9", "#9 A long first sentence about clinics."]]);
    expect(previewSubjects({ id: "x", subject: "none" })).toEqual([]);
  });
});
