// Settings › Appearance: the custom theme's five colours as they are picked, kept across redraws
// and visits until Save, and the colours a first custom theme starts from.
import type { Colours } from "../../lib/theme";

export const DRAFT = $state<{ c: Colours | null }>({ c: null });
export const CUSTOM_SEED: Colours = { side: "#3f0f40", active: "#1164a3", text: "#f6eef6", accent: "#6b2e8c", badge: "#e01e5a" };
export const CUSTOM_FIELDS: [keyof Colours, string][] = [["side", "Sidebar"], ["active", "Current row"], ["text", "Sidebar text"], ["accent", "Accent: links, buttons"], ["badge", "Badge"]];
export const BASES: [string, string][] = [["auto", "Auto"], ["light", "Light"], ["dark", "Dark"]];
