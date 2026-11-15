// the server's JSON has a version: the server's /api/status answers
// host_api, and this page was built against HOST_API_VERSION (api/afk.gen.ts, generated from
// the server's web/types.py). When the two differ the list's head says so in one line; an older
// the server answers none, which counts as v0. Not hosted (brb ui on its own): nothing to say.
import { HOST_API_VERSION } from "../api/afk.gen";

/** the line to show, or null when the server answers the version this page expects (``host``:
 * its /api/status as the app keeps it, Status in afk.gen.ts) */
export function hostApiLine(host: Record<string, unknown> | null | undefined, expects: number = HOST_API_VERSION): string | null {
  if (!host) return null;
  const n = typeof host.host_api === "number" ? host.host_api : 0;
  if (n === expects) return null;
  const v = typeof host.version === "string" && host.version ? host.version : "(unknown version)";
  return `the server ${v} answers API v${n}; this page expects v${expects}: update both with kranto update.`;
}
