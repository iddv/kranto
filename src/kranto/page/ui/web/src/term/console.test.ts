// The console's place in a browser: the first visit follows Settings › Assistant's
// "open when Kranto opens"; after a choice the browser keeps its own; ⌘J opens it from anywhere.
import { beforeEach, describe, expect, it } from "vitest";
import { action, keyName } from "../lib/keys";
import { consoleUi, firstPlace, inConsole, loadPlace, pressed, setPlace, toggleConsole } from "./console.svelte";
import type { ConsoleSettings } from "./console.svelte";

const settings = (open: boolean): ConsoleSettings => ({
  open, harness: null, model: {}, permission: "auto", config: "own", daily_usd: null,
});

function store(start: Record<string, string> = {}) {
  const m = new Map(Object.entries(start));
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), m };
}

describe("the console's place", () => {
  beforeEach(() => {
    consoleUi.place = "open";
    consoleUi.known = false;
    consoleUi.focusN = 0;
  });

  it("follows the setting on a first visit", () => {
    loadPlace(store());
    firstPlace(settings(false));
    expect(consoleUi.place).toBe("rail");
    consoleUi.known = false;
    firstPlace(settings(true));
    expect(consoleUi.place).toBe("open");
  });

  // in Classic the docked console left Needs you a 320 px list ("Add …", "Sho…")
  it("starts on the rail in Classic narrower than 1400 px, docked from 1400 and in New", () => {
    firstPlace(settings(true), { classic: true, width: 1280 });
    expect(consoleUi.place).toBe("rail");
    for (const screen of [{ classic: true, width: 1400 }, { classic: false, width: 1280 }]) {
      consoleUi.known = false;
      firstPlace(settings(true), screen);
      expect(consoleUi.place).toBe("open");
    }
    // a phone starts minimized: ✦ in the bar of doors opens the read-and-approve sheet
    for (const classic of [true, false]) {
      consoleUi.known = false;
      firstPlace(settings(true), { classic, width: 390 });
      expect(consoleUi.place).toBe("min");
    }
    consoleUi.known = false;
    setPlace("open", store());                       // your own press keeps it docked
    firstPlace(settings(true), { classic: true, width: 1280 });
    expect(consoleUi.place).toBe("open");
  });

  // F-11: before setup is done nothing starts Claude Code; the console waits on its
  // rail (minimized on a phone), whatever this browser kept, until a press opens it
  it("waits on its rail before setup is done, whatever the browser kept, until a press", () => {
    pressed.v = false;
    loadPlace(store({ "kranto.console": "open" }));
    firstPlace(settings(true), { classic: false, width: 1400 }, true);
    expect(consoleUi.place).toBe("rail");
    firstPlace(settings(true), { classic: false, width: 390 }, true);
    expect(consoleUi.place).toBe("min");
    setPlace("open", store());
    firstPlace(settings(true), { classic: false, width: 1400 }, true);
    expect(consoleUi.place).toBe("open");
    pressed.v = false;
  });

  it("keeps the browser's own choice after one", () => {
    const s = store({ "kranto.console": "min" });
    loadPlace(s);
    firstPlace(settings(true));
    expect(consoleUi.place).toBe("min");
    setPlace("rail", s);
    expect(s.m.get("kranto.console")).toBe("rail");
    loadPlace(store({ "kranto.console": "nonsense" }));
    expect(consoleUi.place).toBe("rail");
  });

  it("⌘J opens it and asks for the keys", () => {
    setPlace("min", store());
    toggleConsole();
    expect(consoleUi.place).toBe("open");
    expect(consoleUi.focusN).toBe(1);
    const k = keyName({ key: "j", ctrlKey: true, metaKey: false, altKey: false, shiftKey: false });
    expect(k).toBe("⌘J");
    expect(action(k, { typing: true, chord: null, rows: false, focused: false, pageKeys: new Set() })).toEqual({ run: "console" });
  });

  it("knows a key from inside its terminal", () => {
    const aside = document.createElement("aside"), screen = document.createElement("div"), box = document.createElement("textarea");
    aside.id = "console";
    screen.className = "screen";
    screen.append(box);
    aside.append(screen);
    document.body.append(aside);
    expect(inConsole(box)).toBe(true);
    expect(inConsole(document.body)).toBe(false);
  });
});
