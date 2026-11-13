import { afterEach, describe, expect, it } from "vitest";
import { customNow, customTokens, lookNow, themeNow } from "../../lib/theme";
import { draw, settle, stub, where } from "../testing.svelte";
import AppearanceList from "./AppearanceList.svelte";
import AppearancePane from "./AppearancePane.svelte";
import { CUSTOM_SEED, DRAFT } from "./appearance.svelte";

afterEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.removeAttribute("data-look");
  document.documentElement.removeAttribute("style");
  DRAFT.c = null;
});

describe("Settings › Appearance", () => {
  it("lists the theme and the custom theme, each with what is in use", async () => {
    stub();
    const { target, done } = await draw(AppearanceList, where("settings/appearance"));
    expect([...target.querySelectorAll("li.row .c-meta")].map((m) => m.textContent)).toEqual(["Kranto · auto: follows this device", "five colours of your own"]);
    expect(target.querySelector('[data-sel="etheme"] .gl')?.getAttribute("title")).toBe("Default");
    expect(target.querySelector("input")).toBeNull();
    done();
  });

  it("picks light or dark and a theme at once, and keeps them in this browser", async () => {
    const L = stub();
    const { target, done } = await draw(AppearancePane, where("settings/appearance", "etheme"));
    expect(target.querySelector(".dt")?.textContent).toBe("Theme");
    (target.querySelector('[data-theme-choice="dark"]') as HTMLButtonElement).click();
    expect(themeNow()).toBe("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    const cards = [...target.querySelectorAll<HTMLButtonElement>(".look")];
    expect(cards.map((c) => c.tabIndex).filter((t) => t === 0).length).toBe(1);
    (target.querySelector('[data-look-choice="fern"]') as HTMLButtonElement).click();
    expect(lookNow()).toBe("fern");
    expect(localStorage.getItem("kranto.look")).toBe("fern");
    expect(L.render).toHaveBeenCalledTimes(2);
    done();
  });

  it("moves through the cards with the arrows", async () => {
    stub();
    const { target, done } = await draw(AppearancePane, where("settings/appearance", "etheme"));
    const first = target.querySelector<HTMLButtonElement>('[data-look-choice="kranto"]') as HTMLButtonElement;
    first.focus();
    first.dispatchEvent(new KeyboardEvent("keydown", { key: "End", bubbles: true }));
    expect(document.activeElement?.getAttribute("data-look-choice")).toBe("contrast");
    done();
  });

  it("checks a custom theme's pairs and saves it only when every pair reads", async () => {
    const L = stub();
    const { target, done } = await draw(AppearancePane, where("settings/appearance", "ecustom"));
    const save = target.querySelector("#save-custom") as HTMLButtonElement;
    expect(target.querySelectorAll(".ctx li").length).toBe(customTokens(CUSTOM_SEED).checks.length);
    expect(save.disabled).toBe(!customTokens(CUSTOM_SEED).ok);
    const text = target.querySelector('[data-custom="text"]') as HTMLInputElement;
    text.value = "#3f0f40"; // the sidebar's own colour: it cannot read
    text.dispatchEvent(new Event("input", { bubbles: true }));
    await settle();
    expect(save.disabled).toBe(true);
    expect(target.querySelector(".ctx + p")?.textContent).toBe("Save waits until every pair reads: change the colours marked ✕.");
    text.value = "#f6eef6";
    text.dispatchEvent(new Event("input", { bubbles: true }));
    await settle();
    save.click();
    expect(customNow()?.in).toEqual(CUSTOM_SEED);
    expect(lookNow()).toBe("custom");
    expect(document.documentElement.style.getPropertyValue("--c-side-bg")).toBe("#3f0f40");
    expect(L.say).toHaveBeenCalledWith("Custom theme saved and in use, in this browser.");
    done();
  });
});
