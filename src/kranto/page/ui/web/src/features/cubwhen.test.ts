import { describe, expect, it } from "vitest";
import { actionOn, headActions } from "./cub";
import type { ActionDecl, FeatureRow, SettingRow } from "./index";

// UIBUGS B1: a head never holds a button that can only refuse. An action's `when` names one of
// the feature's true-or-false settings, and the head offers it only while that is on.
const act = (kind: string, when?: string): ActionDecl => ({ kind, title: kind, doors: ["ui", "cli"], click: "click", subjects: [], says: "", fields: [], place: "head", ...(when ? { when } : {}) });
const key = (k: string, value: boolean): SettingRow => ({ key: k, value, type: "bool", default: false, choices: [], lo: null, hi: null, words: "", sensitive: false, by_hand: false, per_topic: false });
const digest = (on: boolean): FeatureRow => ({
  id: "digest", title: "Digest", says: "", version: "1.0.0", trust: "first-party", enabled: on, mode: "reads only", tickets_open: 0,
  settings: [key("digest.enabled", on)],
  manifest: { actions: [act("digest.add_item"), act("digest.run_now", "digest.enabled")], ui: { nav: [], cards: {} } },
});

describe("an action's when", () => {
  it("offers Run now and Add an item only while the feature is on", () => {
    // a feature that is off refuses every action (409): its head offers none (the server #295
    // gave the add action its when too)
    expect(headActions(digest(false)).map((a) => a.kind)).toEqual([]);
    expect(headActions(digest(true)).map((a) => a.kind)).toEqual(["digest.add_item", "digest.run_now"]);
  });
  it("takes a switch it cannot find as off, and an action with no when as on", () => {
    expect(actionOn(digest(true), { when: "digest.nope" })).toBe(false);
    expect(actionOn(digest(false), {})).toBe(true);
  });
});
