// The Grade keys (keys.json: 1 2 0, a–f), on any page that draws a grade control: the focused row,
// else the page head. Bulk grading (Select, the ticks, 1 2 0 on ticked rows) went with (the
// owner's D-3: one control, on cards and evidence only).
import { chipsOf, gkey, gradeOf, toggleChip, WHYCUR } from "./grades.svelte";

/** The Grade keys (keys.json: 1 2 0, a–f), on any page that draws a grade control and has not
 * taken the key for its own verb (keys: the page's keys, set again on every draw): the row
 * focused with j/k (row), else the page head's control; a–f press a why chip on the page head
 * once it is graded */
export function gradeKeys(view: Element, keys: Record<string, () => void>, row: () => Element | null): void {
  if (!view.querySelector(".grade")) return;
  const target = (): Element | null => row()?.querySelector(".grade") || document.querySelector("#dscroll .gh .grade, #rows .gh .grade");
  for (const [key, v] of [["1", "useful"], ["2", "not_useful"], ["0", "skip"]] as const) {
    if (keys[key]) continue;
    keys[key] = () => {
      const g = target();
      if (!g) return;
      const b = v === "skip" ? g.querySelector<HTMLElement>("button[aria-pressed=true]") : g.querySelector<HTMLElement>(`button[data-v="${v}"]`);
      if (b && !(v !== "skip" && b.getAttribute("aria-pressed") === "true")) b.click();
    };
  }
  if (!view.querySelector(".gh[data-why-target]")) return;
  "abcdef".split("").forEach((key, i) => {
    if (keys[key]) return;
    keys[key] = () => {
      const g = document.querySelector<HTMLElement>("#dscroll .gh[data-why-target]") || document.querySelector<HTMLElement>("#rows .gh[data-why-target]");
      if (!g) return;
      const t = g.dataset.whyTarget || "", id = g.dataset.whyId || "", c = chipsOf(t)[i], now = gradeOf(t, id, WHYCUR[gkey(t, id)]);
      if (c && now) void toggleChip(t, id, c.key, { current: now });
    };
  });
}
