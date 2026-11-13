// One count for Needs you: the top bar's chip, Needs you's head and the home's
// sentence read the same rows (needsCount, with the cubs' asks as Needs you reads them), so the
// three never say different numbers (Gemini's G8: the home and Needs you named different drafts).
import { features } from "../../features/index";
import { arrangement } from "../../features/shell";
import { cubReadRows, rowCubs, uniqueRows, type HomeRow } from "./home";
import { needsCount, type Host } from "./needs";

/** the cubs' asks (their tickets: Confirm), as Needs you and the home list them */
export function cubAsks(H: Host | null): HomeRow[] {
  const f = features(!!H), a = arrangement(!!H);
  return uniqueRows(rowCubs(f, a, "needs_you").flatMap((x) => cubReadRows(x, "needs_you")));
}
/** how many things wait for you: the one number every place says */
export function needsTotal(H: Host | null): number {
  const cubs = cubAsks(H);
  return needsCount(H, cubs.length, cubs.map((r) => r.href));
}
/** "1 thing waits for you", "4 things wait for you", "Nothing waits for you." */
export const waitsWords = (n: number): string => (n === 1 ? "1 thing waits for you" : n ? `${n} things wait for you` : "Nothing waits for you.");
