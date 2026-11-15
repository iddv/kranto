// First run (PLAN.md section 1.5; UI-v4.md 1.4, 2.5) and Add topic (WORKSPACE.md 2.13). Before
// setup a fresh install opens on #/hello (the splash, whose one button is Set up Kranto); #/welcome
// is setup's three steps, drawn in the stage layout without the panes: the
// model key (Settings › Watching's form), the first topic (Add topic, which is Topics › Add topic
// too) and Ready (Claude Code for the console, the cost, usage reports, Start reading). Add
// topic's form is kept across draws and between the two places it is drawn (TOPIC): the words,
// the topic made from them, the scout's proposals and the ticks.
import type { ScoutResult, SourceRow, SourceValidation } from "../../api/afk.gen";
import type { App } from "../../lib/app";
import { Product } from "../../lib/product";

/** setup's steps: [the route's second part, the step's name]. "How
 * you write" (F-13) is the screen Start reading opens, while kranto reads: it adds nothing to the
 * time to the first brief, and it can be skipped */
export const STEPS: [string, string][] = [["", "Model"], ["topics", "First topic"], ["finish", "Ready"], ["voice", "How you write"]];
/** step 1's ways in, in the order they are drawn. The owner's F-3 (the Claude
 * Code login first when found) is not answered: the login stays last, as the owner's D2 placed it,
 * and the change is this one line, ["login", "key"] */
export type Way = "key" | "login";
export const WAYS: Way[] = ["key", "login"];
/** the steps drawn now */
export const stepsNow = (): [string, string][] => STEPS;
/** where Topics' Continue and Skip go: the next step */
export const afterTopics = (): string => "welcome/finish";
/** the step a route opens (welcome, welcome/topics, welcome/finish), 0 when it names none */
export const stepAt = (sub: string | undefined): number => Math.max(0, stepsNow().findIndex((s) => s[0] === (sub || "")));
/** a step's tick: only when what it sets is set (the key, a topic, Ready's Start reading), never
 * for having passed it (QA B13: Watching was ticked with no key) */
export const stepDone = (i: number, s: { key?: { set?: boolean } | null; topics?: number; done?: boolean } | null): boolean =>
  !!s && (i === 0 ? !!s.key?.set : i === 1 ? (s.topics || 0) > 0 : i === 2 ? !!s.done : false);
/** where Start reading goes: How you write, while the first read runs (F-13) */
export const afterReady = (): string => "welcome/voice";

export const SUGGEST: [string, string][] = [
  ["AI developer tooling", "Tools developers use to build with and alongside AI: coding agents and harnesses, IDE integrations, MCP servers and other integration surfaces, agent skills and plugin packs, evals and prompt tooling."],
  ["LLM tooling and infrastructure", "Running and operating language models: local inference servers, serving and routing, observability and cost control, fine-tuning and evaluation tooling, and the open-source projects and vendors that ship them."],
  ["Local-first software", "Software that keeps working offline and keeps the user's data on their own devices: CRDTs, sync engines, conflict resolution, and the products and business models built on them."],
  ["Small organisations that run on spreadsheets", "Clubs, schools, clinics and small businesses that run on spreadsheets, paper and group chats: what they keep track of, where it breaks, and the tools that replace it."],
  ["Lab tools", "How biology gets done at the bench and how that is changing: lab automation, open hardware, CRISPR and other editing tools, protocols, and software that makes experiments cheaper, faster or reproducible."],
  ["Energy access", "Getting reliable electricity to people and businesses the grid serves badly: off-grid and pay-as-you-go solar, mini-grids, batteries, and the financing and distribution models that make them work."],
  ["Indie game tooling", "Tools small game studios and solo developers use: engines, asset pipelines, level editors, playtesting and storefront tooling."],
];

/** a scout's proposal and what the scout found (the server's /api/topics/<id>/scout, generated) */
export type Proposal = SourceRow;
export type Scouted = ScoutResult;
/** Add topic's form: the words, the topic made from them, the proposals and the ticked ones (a
 * plain Set: a tick is read at the next draw, as the old page did) */
export interface TopicStep {
  name: string;
  desc: string;
  id: number | null;
  rows: Proposal[];
  ticked: Set<number>;
  message: string | null;
  invalid: number;
}
export const newStep = (): TopicStep => ({ name: "", desc: "", id: null, rows: [], ticked: new Set(), message: null, invalid: 0 });
export const TOPIC = $state<{ t: TopicStep | null }>({ t: null });

/** items a day from these sources, before filtering: their rate, else a 30-day test fetch's */
export const perDay = (rows: { items_per_day?: number | null; validation?: SourceValidation | null }[]): number =>
  rows.reduce((a, s) => a + (s.items_per_day != null ? s.items_per_day : (s.validation?.recent || 0) / 30), 0);
export const about = (n: number): string => (n >= 10 ? String(Math.round(n)) : n.toFixed(1));
/** a place's fit to the topic in words, never its score */
export const fitWords = (sim: number | null | undefined): string => (sim == null ? "" : sim >= 0.5 ? "fits well" : sim >= 0.3 ? "fits" : "fits loosely");
/** what kind of place, in words ("Any website" said "a website") */
export const placeWords = (site: unknown): string => (typeof site !== "string" || !site ? "" : /^any website$/i.test(site) ? "a website" : site);
export const budgetLine = (b: number | null | undefined): string =>
  b == null ? "Model calls have no monthly cap (Settings › Spend)." : "Model calls stop at the monthly cap set under Settings › Spend.";
/** Claude Code for the console, the line to install it */
export const CONSOLE_INSTALL = "curl -fsSL https://claude.ai/install.sh | bash"; // Claude Code's own installer: Kranto never asks for Node (as kranto setup and kranto doctor say it)
/** Start reading's flash, by what the first read did (Ready) */
export const STARTED: Record<string, string> = {
  started: `${Product} is reading. The first brief comes in a few minutes; the home shows the first hour.`,
  no_sources: "Set up. No source is watched yet: tick the topic's proposals and choose Watch these, and Kranto starts reading.",
  no_scheduler: "Set up. This server runs without its scheduler (--no-scheduler): run kranto serve with its scheduler (kranto up) to read now.",
  busy: "Kranto is busy with a job; the first read follows it. The topic's page shows its first hour.",
};

interface Job {
  state: string;
  elapsed_s?: number;
  error?: string | null;
  result?: unknown;
}
/** the server's model-backed work runs in the background (no request waits on a model): the press
 * answers with {job}; this polls it every 1.5 s, saying how long it has run ("Scouting… (20 s)"),
 * and returns its result once done. An answer without a job is the result itself. */
export async function afkJob<T>(L: App, r: unknown, poll: string, label: string, say: (w: string) => void, wait = 1500): Promise<T> {
  const first = r as { job?: Job } | null;
  if (!first || !first.job) return r as T;
  let job = first.job;
  const t0 = Date.now() - (job.elapsed_s || 0) * 1000;
  while (job.state === "running") {
    say(`${label}… (${Math.round((Date.now() - t0) / 1000)} s)`);
    await new Promise((res) => setTimeout(res, wait));
    job = ((await L.api(poll)) as { job: Job }).job;
  }
  if (job.state !== "done") throw new Error(job.error || `${label} failed`);
  return job.result as T;
}
