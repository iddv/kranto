import { afterEach, describe, expect, it } from "vitest";
import { ADOPTED_KEY, BROWSER_KEYS, adoptStored, newKey, oldKey, stored } from "./legacy";
import { adoptOld, customNow, themeNow } from "./theme";

describe("a browser's choices from before the rename (lib/legacy.ts)", () => {
  afterEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
    document.documentElement.removeAttribute("data-look");
  });

  it("keeps the old names apart from the new", () => {
    for (const k of BROWSER_KEYS) {
      expect(oldKey(k)).not.toBe(newKey(k));
      expect(oldKey(k).endsWith(`.${k}`)).toBe(true);
    }
  });

  it("reads the new key when it is there, and never the old one", () => {
    localStorage.setItem(newKey("theme"), "light");
    localStorage.setItem(oldKey("theme"), "dark");
    expect(stored("theme")).toBe("light");
    expect(localStorage.getItem(ADOPTED_KEY)).toBeNull();
  });

  it("copies the old key once when the new one is missing, and leaves the old one", () => {
    localStorage.setItem(oldKey("theme"), "dark");
    expect(stored("theme")).toBe("dark");
    expect(localStorage.getItem(newKey("theme"))).toBe("dark");
    expect(localStorage.getItem(oldKey("theme"))).toBe("dark");
    // set back to Auto since (the new key removed): the old one is not read again
    localStorage.removeItem(newKey("theme"));
    expect(stored("theme")).toBeNull();
    expect(themeNow()).toBe("auto");
  });

  it("says nothing when neither key holds a value", () => {
    expect(stored("layout")).toBeNull();
    expect(adoptStored()).toEqual([]);
  });

  it("copies every old key as the app loads and applies the theme and look", () => {
    const custom = { in: { side: "#112233", active: "#445566", text: "#ffffff", accent: "#3366ff", badge: "#ff3366" }, vars: { "--c-side-bg": "#112233" } };
    localStorage.setItem(oldKey("theme"), "dark");
    localStorage.setItem(oldKey("look"), "fern");
    localStorage.setItem(oldKey("look.custom"), JSON.stringify(custom));
    localStorage.setItem(oldKey("layout"), JSON.stringify({ nav: 200 }));
    localStorage.setItem(newKey("layout"), JSON.stringify({ nav: 300 })); // the new one stays
    expect(adoptOld().sort()).toEqual(["look", "look.custom", "theme"]);
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(document.documentElement.getAttribute("data-look")).toBe("fern");
    expect(customNow()?.in.side).toBe("#112233");
    expect(JSON.parse(localStorage.getItem(newKey("layout")) || "{}")).toEqual({ nav: 300 });
    expect(adoptOld()).toEqual([]); // once
  });
});
