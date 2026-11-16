// The glossary's sentences: each state says what it means, each verb what
// happens, and nothing is called "skipped" or "round".
import { describe, expect, it } from "vitest";
import { ago, cut, EFFECT, kTok, saidSaved, SETTING_WORDS, tokShort, tokSum, tokText } from "./words";

describe("tokens and times in words", () => {
  it("tokens, never dollars", () => {
    expect(kTok(49680662)).toBe("49.7M");
    expect(kTok(95832)).toBe("96k");
    expect(kTok(1500)).toBe("1.5k");
    expect(kTok(999)).toBe("999");
    expect(tokText({ in: 1000, out: 500 })).toBe("1.5k tokens");
    expect(tokText(null)).toBe("");
    expect(tokShort(undefined)).toBe("–");
    expect(tokSum([{ in: 1, out: 2 }, null, { in: 3, out: 4 }])).toEqual({ in: 4, out: 6 });
    expect(tokSum([null])).toBeNull();
  });
  it("cuts a line short, and says how long ago", () => {
    expect(cut("a long first line\nsecond", 7)).toBe("a long…");
    expect(cut("short", 10)).toBe("short");
    expect(ago(1000, 1000 + 20)).toBe("now");
    expect(ago(1000, 1000 + 600)).toBe("10 min");
    expect(ago(1000, 1000 + 3 * 3600)).toBe("3 h");
    expect(ago(1000, 1000 + 48 * 3600)).toBe("2 d");
    expect(ago(null)).toBe("");
  });
});

// Settings' words: one name per concept, and every Save says when it applies
describe("Settings' words", () => {
  it("pins the names the pages use", () => {
    expect(SETTING_WORDS).toMatchObject({ watching: "Watching", cap: "cap", noCap: "no cap", needsYou: "Needs you", judge: "Judge", reasoner: "Reasoner", usageReports: "Usage reports", yourSettings: "your settings" });
    expect(SETTING_WORDS).not.toHaveProperty("buildTools");
  });

  it("ends every Save with one of the effect sentences", () => {
    expect(Object.values(EFFECT)).toEqual(["Applies at once.", "From the next check.", "From the next run.", "After a restart (kranto down, kranto up)."]);
    expect(saidSaved("a cap of 200k tokens a day", "now")).toBe("Saved: a cap of 200k tokens a day. Applies at once.");
    expect(saidSaved("the schedule.", "run")).toBe("Saved: the schedule. From the next run.");
  });

  it("every confirm is the house dialog, never the browser's confirm() (UC D12)", () => {
    const files = import.meta.glob(["../**/*.svelte", "../**/*.ts", "!../**/*.test.ts"], { query: "?raw", import: "default", eager: true }) as Record<string, string>;
    const bad = Object.entries(files).filter(([, t]) => !/function confirm\(/.test(t) && /(?<![\w.$])confirm\(|window\.confirm/.test(t)).map(([f]) => f);
    expect(bad).toEqual([]);
  });

  it("no page says press: a button says its action, an approval is an approval (the owner: “No idea what Press means”)", () => {
    const files = import.meta.glob(["../**/*.svelte", "../**/*.ts", "!../**/*.test.ts", "!../**/*.gen.ts", "!../**/testing*.ts"], { query: "?raw", import: "default", eager: true }) as Record<string, string>;
    const word = /\bpress(es|ed|ing)?\b/i;
    const bad: string[] = [];
    for (const [f, raw] of Object.entries(files)) {
      // comments are the code's own words (a prepared item's route is still /press)
      const text = raw.replace(/\/\*[\s\S]*?\*\//g, "").replace(/<!--[\s\S]*?-->/g, "").replace(/(^|[^:"'`\\])\/\/.*$/gm, "$1");
      const shown: string[] = [];
      {
        for (const m of text.matchAll(/"([^"\n]*)"|`([^`\n]*)`/g)) shown.push((m[1] ?? m[2] ?? "").replace(/\$\{[^}]*\}/g, " "));
        // a component's markup between its tags (its script and style aside)
        if (f.endsWith(".svelte")) for (const m of text.replace(/<script[\s\S]*?<\/script>|<style[\s\S]*?<\/style>/g, "").matchAll(/>([^<>{}]+)</g)) shown.push(m[1]!);
      }
      for (const s of shown) {
        // a name of the code ("press", "-press", "/press") is no word a person reads
        if (/^[\w/.-]*$/.test(s.trim()) || /press (release|kit)/i.test(s)) continue;
        if (word.test(s.replace(/aria-pressed/g, ""))) bad.push(`${f}: ${s.trim().slice(0, 90)}`);
      }
    }
    expect(bad).toEqual([]);
  });

  // the strings a page shows, as the press test reads them: quoted text and a component's markup
  const shownIn = (f: string, raw: string): string[] => {
    const text = raw.replace(/\/\*[\s\S]*?\*\//g, "").replace(/<!--[\s\S]*?-->/g, "").replace(/(^|[^:"'`\\])\/\/.*$/gm, "$1");
    const shown: string[] = [];
    for (const m of text.matchAll(/"([^"\n]*)"|`([^`\n]*)`/g)) shown.push((m[1] ?? m[2] ?? "").replace(/\$\{[^}]*\}/g, " "));
    if (f.endsWith(".svelte")) for (const m of text.replace(/<script[\s\S]*?<\/script>|<style[\s\S]*?<\/style>/g, "").matchAll(/>([^<>{}]+)</g)) shown.push(m[1]!);
    // a name of the code is no word a person reads; a capitalised word alone is a label ("Dry")
    return shown.filter((s) => !/^[\w/.:?=&${}-]*$/.test(s.trim()) || /^[A-Z][a-z]+$/.test(s.trim()));
  };

  it("no page says ticket or dry: a cub asks, an approval in practice sends nothing (SEND, the owner: “Not sure what 'ticket #1 is expired' means”)", () => {
    const files = import.meta.glob(["../**/*.svelte", "../**/*.ts", "!../**/*.test.ts", "!../**/*.gen.ts", "!../**/testing*.ts"], { query: "?raw", import: "default", eager: true }) as Record<string, string>;
    const word = /\b(tickets?|dry)\b/i;
    // names of the code a person never reads: the routes, the console socket's ticket, the CLI's
    // kranto cub dry; and another feature's own dry run (the weekly editor's, Settings › Editor)
    const ok = /\/api\/tickets\S*|ticket=|kranto cub dry|"live" : "dry"/g;
    const bad: string[] = [];
    for (const [f, raw] of Object.entries(files)) {
      for (const s of shownIn(f, raw)) if (word.test(s.replace(ok, ""))) bad.push(`${f}: ${s.trim().slice(0, 90)}`);
    }
    expect(bad).toEqual([]);
  });

  it("an ask's dialog and its rows say no cub: the cub's name, its verb, where it stands (SEND)", () => {
    const files = import.meta.glob(["../features/cub/AskDialog.svelte", "../features/cub/AskLine.svelte", "../features/ask.ts", "../ui/ReadBack.svelte"], { query: "?raw", import: "default", eager: true }) as Record<string, string>;
    expect(Object.keys(files).length).toBe(4);
    const bad = Object.entries(files).flatMap(([f, raw]) => shownIn(f, raw).filter((s) => /\bcubs?\b/i.test(s)).map((s) => `${f}: ${s.trim().slice(0, 90)}`));
    expect(bad).toEqual([]);
  });

  it("a feature's page, its crumb and its Settings say feature, never cub (the owner: plain words, no house jargon)", () => {
    const files = import.meta.glob(["../features/cub/CubPage.svelte", "../features/cub/CubObjectPage.svelte", "../features/cub/CubPane.svelte", "../features/cub/CubControls.svelte",
      "../features/cub.ts", "../pages/settings/FeaturePage.svelte", "../pages/settings/FeaturePane.svelte", "../pages/settings/NewsletterPane.svelte"], { query: "?raw", import: "default", eager: true }) as Record<string, string>;
    expect(Object.keys(files).length).toBe(8);
    // names of the code a person never reads: routes and ids (cub/<id>, cub-sheet, ?cub=), a key's
    // name drawn from parts (cubs.<id>.<cap>), a property read inside a nested template (j.cub.diff)
    const code = /[\w-]*\bcubs?[-/=][\w${}/.=-]*|[\w-]+-cubs?\b|\bcubs\.(?=[\s.]|$)[ .]*|[\w$]+\.cubs?\b/g;
    const bad = Object.entries(files).flatMap(([f, raw]) => shownIn(f, raw).filter((s) => /\bcubs?\b/i.test(s.replace(code, ""))).map((s) => `${f}: ${s.trim().slice(0, 90)}`));
    expect(bad).toEqual([]);
  });

  it("no page says monitoring, a budget, or a file name where it means watching, a cap or your settings", () => {
    const files = import.meta.glob(["../**/*.svelte", "../**/*.ts", "!../**/*.test.ts", "!../**/*.gen.ts", "!./words.ts"], { query: "?raw", import: "default", eager: true }) as Record<string, string>;
    const bad: string[] = [];
    for (const [f, text] of Object.entries(files)) {
      // the strings a page shows: quoted text on one line, not comments, keys or field names
      for (const m of text.matchAll(/"([^"\n]*)"|`([^`\n]*)`/g)) {
        const s = (m[1] ?? m[2] ?? "").replace(/\$\{[^}]*\}/g, "");
        if (/\bmonitoring\b/i.test(s) || (/ /.test(s) && /\b[Bb]udget\b(?![._])/.test(s)) || /\b(Written to|in) (the server|Kranto|loop)\.yaml\b/.test(s)) bad.push(`${f}: ${s.slice(0, 90)}`);
      }
    }
    expect(bad).toEqual([]);
  });
});
