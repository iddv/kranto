// Settings › System › Updates: the version, what is on offer, automatic updates,
// the channel, the last updates. the server's /api/update holds the cache, the settings, the
// history and what is busy; Restart to update asks Kranto's helper, which backs up, installs,
// restarts and checks itself, rolling back on its own. The header's pill and Needs you's row use
// the app's updApply/updRollback for the presses.
import { rel } from "../../lib/format";

export const UPD_API = "/api/update";
export const UPD_BUSY: Record<string, string> = {
  requested: "starting", draining: "waiting for a job to finish", backing_up: "backing up", stopping: "stopping Kranto",
  installing: "installing", starting: "starting the new version", verifying: "checking the new version", rolling_back: "rolling back",
};
export const AUTO_WORDS: Record<string, string> = { off: "off: you click Restart to update", idle: "when idle, inside the quiet window" };
// the two lines (the owner 2026-10-24): stable is what the maintainer chose to
// release as stable, never a matter of time; nightly is every build from main. The old rc reads
// as nightly (the server maps it), so it is no choice here.
export const CHANNEL_WORDS: Record<string, string> = {
  stable: "stable: releases the maintainer made stable",
  nightly: "nightly: a new version from main, several a day",
  main: "main: every merge (from git)",
};
export const CHANNEL_HINT =
  "stable is what the maintainer released as stable once the work in it was done, and fixes as soon as they are checked; new installs start on stable. " +
  "nightly is a new version from main, several a day: new features arrive here first, it may break, a version whose pages fail on your data rolls itself back, and you click to update (nothing installs by itself). " +
  "main follows every merge from git and suits a development machine. " +
  "Moving from nightly to stable never downgrades: you stay on your version until a newer stable is released.";
/** a release's tag from its version: 0.6.2 → v0.6.2, 0.7.0.dev12 → v0.7.0-dev12, 0.5.27rc1 → v0.5.27-rc1 */
export const tagOf = (version: string): string =>
  "v" + version.replace(/^v/, "").replace(/\.dev(\d+)$/, (_m, n: string) => "-dev" + n).replace(/rc(\d+)$/, (_m, n: string) => "-rc" + n);
/** "nightly build 12 toward 0.7.0" for a nightly's version (0.7.0.dev12), else null */
export function buildLine(version: string | null | undefined): string | null {
  const m = /^(\d+\.\d+\.\d+)\.dev(\d+)$/.exec(version || "");
  return m ? `nightly ${m[2]} toward ${m[1]}` : null;
}
/** what Save says after a channel change: what the next check does, and that nothing is downgraded */
export function channelReadback(chosen: string, installed: { version: string; channel: string }): string {
  if (chosen === "nightly") return "channel nightly: the next check offers the newest version";
  if (chosen === "stable" && installed.channel === "nightly")
    return `channel stable: you stay on ${installed.version} until a newer stable is released; nothing is downgraded`;
  return `channel ${chosen}`;
}

export interface Apply {
  state?: string;
  to?: string;
  detail?: string | null;
  reason?: string | null;
  finished?: string | null;
  log?: string | null;
  unit?: string | null;
}
export interface UpdateState {
  ok: boolean;
  error?: string | null;
  checked_at?: string | null;
  available?: string | null;
  staged?: { version: string } | null;
  stage_error?: string | null;
  installed: { version: string; channel: string };
  settings: { auto: string; quiet_window: string; channel: string };
  apply?: Apply;
  history?: { from: string; to: string; state: string; reason?: string | null; detail?: string | null; finished?: string | null }[];
  latest?: { version?: string; notes?: string[]; notes_url?: string | null };
  previous?: { version?: string } | null;
  busy?: { builds?: number; fixes?: number; job?: string | null };
  can_apply: boolean;
}

export const busyOf = (a: Apply | null | undefined): boolean => !!(a && a.state && UPD_BUSY[a.state]);
export const badOf = (a: Apply | null | undefined): boolean => !!(a && (a.state === "rolled_back" || a.state === "failed"));
/** an ISO time as seconds, for rel() */
export const secs = (s: string | null | undefined): number | null => (s ? Date.parse(s) / 1000 : null);
/** "up to date, checked 3 min ago", "0.3.58 available, staged", "check failed …" */
export function latestLine(d: UpdateState, now: number = Date.now()): string {
  if (!d.checked_at) return "not checked yet";
  if (!d.ok) return `check failed ${rel(secs(d.checked_at), now)}: ${d.error}`;
  if (!d.available) return `up to date, checked ${rel(secs(d.checked_at), now)}`;
  return `${d.available} available` + (d.staged && d.staged.version === d.available ? ", staged" : d.stage_error ? `, not staged: ${d.stage_error}` : "");
}
