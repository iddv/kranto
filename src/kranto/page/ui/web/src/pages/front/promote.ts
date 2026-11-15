// Promote to stable (the owner, 2026-10-24: "Stable is always a choice that we
// make"). The gate writes the candidate (the server's GET /api/update, `candidate`, on the
// maintainer's install only); Today's Needs you draws one row from it: facts, never a countdown.
// What is in it (the PRs since the last stable, the big ones named, the settings that stay off
// on stable), the health checks, and the press when nothing blocks. Time on nightly is shown as
// plain information. The press opens the shell's one dialog, read back, and only its Promote
// writes (POST /api/update/promote); the gate's unit cuts, checks and releases.
import { read } from "../../lib/reads.svelte";
import { plural, stamp } from "../../lib/format";
import { UPD_API } from "../settings/updates";

export interface ReleaseCheck { name: string; ok: boolean | null; said: string }
export interface ReleasePR { number: number; title: string; repo?: string | null }
export interface OffOnStable { key: string; default?: unknown; default_stable?: unknown }
export interface Candidate {
  state: string;
  said?: string | null;
  stable?: string | null;
  tag?: string | null;
  version?: string | null;
  to?: string | null;
  installed?: string | null;
  nightly_since?: string | null;
  prs?: Record<string, ReleasePR[]>;
  count?: number;
  big?: ReleasePR[];
  off_on_stable?: OffOnStable[];
  checks?: ReleaseCheck[];
  blocking?: string[];
  blind?: string[];
  step?: string | null;
  reason?: string | null;
  log?: string | null;
  promoted?: { tag?: string; at?: string } | null;
}

export const PROMOTE_API = "/api/update/promote";
/** the candidate, when this is the maintainer's install and the gate wrote one */
export function candidateRead(host: unknown): Candidate | null {
  if (!host) return null;
  const d = read<{ candidate?: Candidate | null }>(UPD_API, 60000).data;
  return d?.candidate || null;
}

const v = (tag: string | null | undefined): string => String(tag || "").replace(/^v/, "");
const STEPS: Record<string, string> = { cutting: "cutting it from {from}", rc_check: "rc_check against {stable}", releasing: "releasing it" };

/** what stays off on stable: "shell.layout stays classic on stable" */
export const offLine = (o: OffOnStable): string => `${o.key} stays ${String(o.default_stable)} on stable`;
/** the big changes, by title and number */
export const bigLine = (big: ReleasePR[]): string => (big.length ? `${plural(big.length, "big change")}: ${big.map((b) => `${b.title} (#${b.number})`).join(", ")}` : "no big change");
/** each check's word: what it found, or that it could not read */
export function checkLine(c: ReleaseCheck): string {
  return c.ok === null ? `${c.name}: could not read` : c.said;
}

export interface PromoteRow { kind: "candidate" | "blocked" | "promoting" | "promoted" | "failed"; title: string; detail: string[]; press: boolean; counts: boolean }

/** the row for each state of the candidate; null when there is nothing to say */
export function promoteRow(c: Candidate | null): PromoteRow | null {
  if (c && c.state === "promoted" && c.promoted?.tag) return { kind: "promoted", title: `${v(c.promoted.tag)} is stable`, detail: [`released ${stamp(c.promoted.at)} UTC`, "every stable install is offered it at its next check"], press: false, counts: false };
  if (!c || !c.tag) return null;
  const from = v(c.tag), to = v(c.to), stable = v(c.stable);
  const facts = [
    `${plural(c.count || 0, "pull request")} since ${stable || "the last stable"}`,
    // the row says how many; their titles are in the confirm (on live this row was 416 words)
    (c.big || []).length ? plural((c.big || []).length, "big change") : "no big change",
    ...(c.off_on_stable || []).map(offLine),
  ];
  const checks = (c.checks || []).map(checkLine);
  const info = [...(c.blind || []), ...(c.nightly_since ? [`on nightly since ${stamp(c.nightly_since)} UTC`] : [])];
  if (c.state === "candidate" && !(c.blocking || []).length)
    return { kind: "candidate", title: `Nightly ${from} can become stable ${to}`, detail: [...facts, ...checks, ...info], press: true, counts: true };
  if (c.state === "blocked" || (c.blocking || []).length)
    return { kind: "blocked", title: `Nightly ${from} is not promoted: ${(c.blocking || [])[0] || "a health check blocks it"}`, detail: [...(c.blocking || []).slice(1), ...facts, ...info], press: false, counts: true };
  if (c.state === "promoting")
    return { kind: "promoting", title: `Promoting ${to}`, detail: [(STEPS[c.step || ""] || "the gate is on it").replace("{from}", from).replace("{stable}", stable), "about an hour; nothing to do"], press: false, counts: true };
  if (c.state === "failed")
    return { kind: "failed", title: `${to}'s promotion stopped at ${c.step || "a step"}`, detail: [c.reason || "see the log", ...(c.log ? [`log: ${c.log}`] : []), `${to} stays held: no stable install is offered it`], press: false, counts: true };
  return null;
}

/** the confirm's words, read back before anything happens (no press is a write without it) */
export function confirmWords(c: Candidate): { title: string; body: string[] } {
  const to = v(c.to), stable = v(c.stable);
  const body = [
    `It reaches every install on the stable channel at its next check, or tonight when idle. It carries ${plural(c.count || 0, "pull request")} since ${stable || "the last stable"}` +
      ((c.big || []).length ? `, including ${bigLine(c.big || [])}.` : "; none is labelled big."),
  ];
  const off = c.off_on_stable || [];
  if (off.length) body.push(`Off on stable until you change their default: ${off.map(offLine).join("; ")}.`);
  body.push(`The gate cuts ${to} from nightly ${v(c.tag)}, runs rc_check against ${stable || "the last stable"} and releases it; about an hour. If a step fails, ${to} stays held and this row says where it stopped.`);
  return { title: `Promote ${v(c.tag)} to stable as ${to}?`, body };
}
