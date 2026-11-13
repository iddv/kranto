// Where a route draws and the draw (route.ts).
import { afterEach, describe, expect, it, vi } from "vitest";
import { parse } from "../router";
import { ui } from "../shell.svelte";
import { closePop, popover } from "../../ui/popover";
import { termUi } from "../../term/state.svelte";
import { backHref, boot, hasView, openClaude, pageKey, pageKeys, paneSelHref, render, routeNow, runPageKey, selTarget, topicAt, typing, where } from "./route";
import { card, frame, hostStatus, network, tick, unframe } from "./testing";

afterEach(unframe);
const at = (hash: string) => where(parse(hash));
const IDEAS = "/api/ideas?embedding=ref";

describe("where a route draws", () => {
  it("finds the list and the object in the pane", () => {
    window.matchMedia = ((q: string) => ({ matches: false, media: q })) as never;
    expect(at("#/ideas")).toMatchObject({ node: "ideas", object: null, stage: false, missing: false, focus: null });
    expect(at("#/ideas/3")).toMatchObject({ node: "ideas", object: "idea", id: "3", obj: ["ideas", "3"], sel: false, focus: null });
    expect(at("#/hello")).toMatchObject({ stage: true, object: null });
    expect(at("#/no/such/page")).toMatchObject({ stage: true, missing: true, node: null });
  });

  it("opens a row's object away from its home, and a Needs you row that is no object's own route", () => {
    window.matchMedia = ((q: string) => ({ matches: false, media: q })) as never;
    expect(at("#/needs?sel=i3")).toMatchObject({ node: "needs", object: "idea", id: "3", obj: ["ideas", "3"], sel: true });
    // NEEDSELS: a topic's proposals, a message, the queue… are Needs you's pane's
    for (const code of ["p2", "mx", "r", "t1", "u4", "eheld"]) {
      expect(at("#/needs?sel=" + code)).toMatchObject({ object: "need", id: code, obj: ["need", code], sel: true });
    }
  });

  it("selects a settings page's main group, but not on a phone; Health's message and Add source's preset select theirs", () => {
    window.matchMedia = ((q: string) => ({ matches: false, media: q })) as never;
    expect(at("#/settings/appearance").r.sel).toBe("etheme");
    expect(at("#/settings/system?message=m9").r.sel).toBe("emsg:m9");
    expect(at("#/settings/sources/new?preset=hn").r.sel).toBe("epreset:hn");
    expect(at("#/settings/sources/new?review=4").r.sel).toBe("ereview:4");
    expect(at("#/settings/spend").r.sel).toBe(null);
    window.matchMedia = ((q: string) => ({ matches: q.includes("759px"), media: q })) as never;
    expect(at("#/settings/appearance").r.sel).toBe(null);
  });

  it("opens Watching with nothing selected without the server (the provider is the server's)", async () => {
    await frame({ host: null });
    expect(at("#/settings/watching").r.sel).toBe(null);
  });
});

describe("the draw", () => {
  it("replaces a redirect keeping its filters and selection, and says Not found where there is no page", async () => {
    await frame({ hash: "#/overview?q=x&sel=i3" });
    render();
    expect(location.hash).toBe("#/home?q=x&sel=i3");
    history.replaceState(null, "", "#/nope/route");
    render();
    const rows = document.getElementById("rows")!;
    expect(rows.textContent).toContain("There is no page at #/nope/route. It may have moved in this version.");
    expect(rows.querySelector("a.btn")?.getAttribute("href")).toBe("#/");
    expect(document.title).toBe("Not found · Kranto");
    expect(document.getElementById("dscroll")?.textContent).toBe(""); // a stage: no pane
  });

  it("lands an old build's address on the home and says why once", async () => {
    await frame({ hash: "#/builds/plots" });
    render();
    expect(location.hash).toBe("#/home");
  });

  it("replaces a redirect in the history, so back does not bounce", async () => {
    await frame({ hash: "#/settings/watches" });
    const push = vi.spyOn(history, "pushState"), replace = vi.spyOn(history, "replaceState");
    render();
    expect(location.hash).toBe("#/watch"); // watches are retired (WT): Watch's Topics
    expect(replace).toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
    push.mockRestore();
    replace.mockRestore();
  });

  it("keeps a list's scroll for coming back to it, and opens another list at its top", async () => {
    await frame({ hash: "#/ideas" });
    const rows = document.getElementById("rows")!;
    let top = 0;
    Object.defineProperty(rows, "scrollTop", { configurable: true, get: () => top, set: (v: number) => { top = v; } });
    render();
    top = 240;
    history.replaceState(null, "", "#/library");
    render();
    expect(top).toBe(0);
    history.replaceState(null, "", "#/ideas");
    render();
    expect(top).toBe(240);
    top = 300;
    history.replaceState(null, "", "#/ideas/3"); // its pane opens beside the same list: kept
    render();
    expect(top).toBe(300);
  });

  it("says nothing is selected beside a list", async () => {
    await frame({ hash: "#/library" });
    render();
    expect(document.body.classList.contains("focus")).toBe(false);
    expect(document.getElementById("dscroll")?.textContent).toBe("Nothing selected.");
  });

  it("gives every draw fresh page keys, and c on a card's pane opens Claude Code", async () => {
    await frame({ hash: "#/ideas/3", reads: { [IDEAS]: { ideas: [card(3)] } } });
    render();
    await tick();
    pageKey("x", () => {});
    render();
    expect(pageKeys()).toContain("c");
    expect(pageKeys()).not.toContain("x");
    termUi.enabled = false;
    termUi.why = "Open in Claude Code is off on this machine.";
    runPageKey("c");
    expect(ui.facts?.head.flash?.text).toBe("Open in Claude Code is off on this machine.");
    termUi.why = null;
    history.replaceState(null, "", "#/ideas/99");
    render();
    await tick();
    render();
    expect(pageKeys()).not.toContain("c"); // no such card: no subject
  });

  it("keeps a flash 8 s across draws, then drops it; a the server notice (?msg=) shows once", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    try {
      await frame({ hash: "#/needs?msg=Saved." });
      render();
      expect(ui.facts?.head.flash?.text).toBe("Saved.");
      vi.setSystemTime(Date.now() + 5000);
      render();
      expect(ui.facts?.head.flash?.text).toBe("Saved.");
      vi.setSystemTime(Date.now() + 4000);
      render();
      expect(ui.facts?.head.flash).toBe(null);
    } finally {
      vi.useRealTimers();
    }
  });

  it("lands a fresh install on the splash, only from the home; a deep link is kept", async () => {
    await frame({ hash: "#/today" });
    network({ "/api/status": hostStatus(), "/api/whoami": { origin: "ann" }, "/api/setup": { needs_setup: true } });
    expect(await boot()).toBe(true);
    expect(location.hash).toBe("#/hello");
    history.replaceState(null, "", "#/ideas");
    await boot();
    expect(location.hash).toBe("#/ideas");
  });

  it("boots without a snapshot of its own: it draws at once, signed out too", async () => {
    await frame();
    network({ "/api/status": hostStatus(), "/api/whoami": { origin: null, require_token: true } });
    expect(await boot()).toBe(true);
    expect(document.getElementById("rows")?.textContent || "").not.toMatch(/Could not read Kranto/);
  });

  it("#/console opens the console beside the home (3: it was 'There is no page')", async () => {
    await frame({ hash: "#/console" });
    network({ "/api/status": hostStatus(), "/api/whoami": { origin: "ann" } });
    const { consoleUi } = await import("../../term/console.svelte");
    const before = consoleUi.focusN;
    expect(await boot()).toBe(true);
    expect(location.hash).not.toBe("#/console");
    expect(consoleUi.place).toBe("open");
    expect(consoleUi.focusN).toBe(before + 1);
  });
});

describe("links and keys", () => {
  it("opens a list's link in the pane beside it, at home as itself; filters go where they say", async () => {
    await frame({ hash: "#/needs?q=a" });
    render();
    expect(selTarget("#/ideas/3")).toBe("#/needs?q=a&sel=i3");
    expect(selTarget("#/ideas?status=waiting")).toBe(null);
    history.replaceState(null, "", "#/ideas");
    render();
    expect(selTarget("#/ideas/3")).toBe("#/ideas/3");
    history.replaceState(null, "", "#/ideas/3");
    render();
    expect(backHref(routeNow()!)).toBe("#/ideas");
    expect(paneSelHref("m7")).toBe("#/ideas?sel=m7");
  });

  it("knows the go-to keys' pages and the topics by their number", async () => {
    await frame();
    for (const v of ["needs", "review", "topics", "ideas", "library", "settings"]) expect(hasView(v)).toBe(true);
    for (const v of ["today", "builds", "projects", "chats"]) expect(hasView(v)).toBe(false);
    // every g key's page is one; g h and g n wait for their host, g 1…9 is a topic
    const { KEYMAP } = await import("../keys");
    const gone = KEYMAP.filter((m) => m.go && !["topic", "home", "news"].includes(m.go) && !hasView(m.go)).map((m) => m.keys);
    expect(gone).toEqual([]);
    expect(hasView("activity")).toBe(true);
    expect(topicAt(2)?.name).toBe("Local-first");
    expect(topicAt(9)).toBe(null);
  });

  it("is typing in a field, a dialog, the palette or a popover, never on a tick", async () => {
    await frame();
    expect(typing()).toBe(false);
    const box = document.createElement("input");
    box.type = "checkbox";
    document.getElementById("rows")!.append(box);
    box.focus();
    expect(typing()).toBe(false);
    const field = document.createElement("input");
    document.getElementById("rows")!.append(field);
    field.focus();
    expect(typing()).toBe(true);
    field.blur();
    (document.getElementById("pal") as HTMLDialogElement).setAttribute("open", "");
    expect(typing()).toBe(true);
    document.getElementById("pal")!.removeAttribute("open");
    const b = document.createElement("button");
    document.body.append(b);
    popover(b, "Why?", []);
    expect(typing()).toBe(true);
    closePop();
    expect(typing()).toBe(false);
  });

  it("opens Claude Code on the subject while it is on", async () => {
    await frame();
    termUi.enabled = true;
    openClaude("idea", "3", "Card 3");
    expect(termUi.subject).toMatchObject({ kind: "idea", id: "3" });
    expect(termUi.title).toBe("Card 3");
    termUi.enabled = false;
    termUi.subject = null;
  });
});
