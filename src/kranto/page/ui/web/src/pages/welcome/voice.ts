// Welcome's "How you write": the server's prose profile (GET /api/prose,
// docs/prose.md), the four switches Welcome offers, the samples as pasted, and the first read's
// line on top (/api/home's `first`).
import type { HomeFirst } from "../../api/afk.gen";
import { Product } from "../../lib/product";

export const PROSE_API = "/api/prose";
/** the part of GET /api/prose this screen reads */
export interface Prose {
  voice: string;
  switches: Record<string, string | number>;
  switch_choices: Record<string, (string | number)[]>;
  switch_words: Record<string, string>;
  samples: { id: string; site: string | null; words: number; start: string }[];
}
/** the four Welcome offers (the rest are Settings › Posting › Voice's) */
export const SWITCH_SHOWN = ["length", "register", "opinions", "emoji"] as const;
const LABELS: Record<string, string> = { length: "How long", register: "How formal", opinions: "Opinions", emoji: "Emoji" };
export const switchLabel = (k: string): string => LABELS[k] || k;
/** the pasted text as samples: split on a line of three dashes, each at least 20 characters, at most five */
export function splitSamples(text: string): string[] {
  return text.split(/^\s*-{3,}\s*$/m).map((s) => s.trim()).filter((s) => s.length >= 20).slice(0, 5);
}
/** the samples line under the box: how many are kept, and those left out and why (Gemini 14:
 * a short sample was dropped without a word) */
export function samplesLine(text: string): string {
  const parts = text.split(/^\s*-{3,}\s*$/m).map((s) => s.trim()).filter(Boolean);
  const kept = splitSamples(text).length;
  if (!parts.length) return "Three to five is best.";
  const short = parts.filter((s) => s.length < 20).length;
  const over = Math.max(0, parts.length - short - 5);
  const out = [`${kept} of 3 to 5 pasted.`];
  if (short) out.push(`${short} left out: under 20 characters.`);
  if (over) out.push(`${over} left out: five at most.`);
  return out.join(" ");
}
/** the read as it goes, in one line: "Kranto is reading · source 2 of 5 · 4 kept of 19 read · the
 * first brief in about 3 minutes"; once enough are kept, that it is being written */
export function firstLine(f: HomeFirst | null | undefined): string {
  if (!f || f.error || !f.topic) return "";
  const parts = [`${Product} is reading`];
  if (f.read) {
    parts.push(`source ${f.read.source_index} of ${f.read.sources}`);
    parts.push(`${f.read.kept} kept of ${f.read.judged} read`);
  }
  if (f.brief_minutes != null) parts.push(`the first brief in about ${f.brief_minutes} minute${f.brief_minutes === 1 ? "" : "s"}`);
  else if (f.read && f.early_kept && f.read.kept >= f.early_kept) parts.push("the first brief is being written");
  return parts.join(" · ");
}
