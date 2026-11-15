// Settings › System › Health: the build loop, and the server's /api/health (its runs, model errors,
// messages, the strike gate) with the watched sources that need a look. The shapes are
// the server's, generated from its web/types.py (api/afk.gen.ts).
import type { Health, Message, Source } from "../../api/afk.gen";
import { nextRead, plural, stamp } from "../../lib/format";
export { stamp };
import type { St } from "../../ui/settings";
export type { Decision, Health, HealthRun as Run, Message, ModelError, RunSourceReport as RunSource, Source, Sources } from "../../api/afk.gen";

export const HEALTH_API = "/api/health";
export const SOURCES_API = "/api/sources";

export const RUN_ST: Record<string, St> = { ok: ["check", "grey", "Ok"], failed: ["x", "red", "Failed"], skipped: ["skipped", "grey", "Skipped"], stopped: ["warn", "amber", "Stopped"], running: ["running", "blue", "Running"] };
export const runSt = (s: string): St => RUN_ST[s] || ["warn", "amber", s];
/* status: always an icon and a word (section 4) */
export const SRC_ST: Record<string, St> = { ok: ["check", "grey", "Ok"], paced: ["warn", "amber", "Paced"], failing: ["x", "red", "Failing"], needs_login: ["warn", "amber", "Needs an account"],
  proposed: ["open", "grey", "Proposed"], retired: ["closed", "grey", "Retired"], new: ["dot", "grey", "Not fetched yet"], invalid: ["x", "grey", "Could not be fetched"], imported: ["dot", "grey", "Imported label"] };
export const srcSt = (k: string): St => SRC_ST[k] || ["dot", "grey", "Not fetched yet"];
/* a paced source (a 429, a 503, a timeout) is not failing: it is read again when its host
   allows, or at the next run (sources.pacing in the server) */
export const pacedWord = (at: string | null | undefined, now = Date.now()): string =>
  "paced, retrying " + (at && Date.parse(at) > now ? "at " + nextRead(at) : "at the next run");
export const msgWord = (m: Message): St =>
  m.kind === "alarm" ? ["warn", "red", "Alarm"] : m.kind === "strike" ? ["check", "blue", "Strike"] : ["dot", "grey", (m.kind[0] || "").toUpperCase() + m.kind.slice(1)];
export const words = (s: string | null | undefined): string => (s || "").replace(/_/g, " ");
/** a run's job in words: a feature's job "news.brief" is "News: brief", a core job its word
 * ("ingest") (QA B8: the Runs rows showed the job's id); an old run of a feature that left Kranto
 * (Invest's, the radar's: their rows stay in the history) says only that */
export function runKind(kind: string): string {
  const [f, ...rest] = kind.split(".");
  if (f === "invest" || f === "radar") return "A feature that left Kranto";
  if (!rest.length) return words(kind);
  return `${f![0]!.toUpperCase()}${words(f!.slice(1))}: ${words(rest.join(" "))}`;
}
/** a run's title: its error, what it added, else what happened, a skip with its reason (the job
 * says why it skipped: "skipped: halted"), never the state's word twice ("Skipped · Skipped") */
export function runTitle(x: { status: string; error?: string | null; summary?: Record<string, unknown> | null }): string {
  const sm = x.summary || {};
  if (x.error) return x.error;
  if (sm.contributed != null) return plural(Number(sm.contributed), "new observation");
  if (x.status === "skipped") {
    const why = typeof sm.why === "string" && sm.why ? sm.why : sm.not_due != null ? "nothing was due" : "nothing to do";
    return "skipped: " + why;
  }
  return x.status === "ok" ? "finished" : runSt(x.status)[2].toLowerCase();
}
/** the share of the monthly cap used, 100 with no cap */
export const capUsed = (d: Health): number => (d.budget.monthly_usd ? Math.min(100, d.spent_usd / d.budget.monthly_usd * 100) : 100);
/** the watched sources that are paced or failing */
export const needingLook = (xs: Source[]): Source[] => xs.filter((s) => s.review === "approved" && ["paced", "failing", "needs_login"].includes(s.status));
/* Kranto's memory (the server's memory.py): past 80% of its lowest cap is high */
export const MEM_ST: Record<string, St> = { ok: ["check", "grey", "Ok"], high: ["warn", "amber", "High"], uncapped: ["dot", "grey", "No cap"] };
export const memSt = (level: string): St => MEM_ST[level] || ["dot", "grey", level];
export const mb = (x: number | null | undefined): string => (x == null ? "not set" : x >= 1024 ? (x / 1024).toFixed(1) + " GB" : x + " MB");
