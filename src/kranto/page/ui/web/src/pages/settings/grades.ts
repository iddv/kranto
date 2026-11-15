// Settings › System › Your grades (once Learning): the server's GET
// /api/grades/summary, what your grades changed: taste (the cards they moved, the themes the next
// ideas run cards in their order) and the source rule. Ratings steer gathering; no model decides.

export const GRADES_API = "/api/grades/summary";

// The next ideas run's themes, kept short ("four short sections"): the first
// THEMES_SHOWN in the run's order and every one it skips, still in that order.
export const THEMES_SHOWN = 5;
export function topThemes<T extends { skip?: boolean | null }>(themes: T[], n = THEMES_SHOWN): T[] {
  let kept = 0;
  return themes.filter((t) => t.skip || kept++ < n);
}
