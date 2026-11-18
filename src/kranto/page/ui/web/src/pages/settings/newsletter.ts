// Settings › Accounts › Newsletter: the server's /api/newsletter, generated from its
// web/types.py (api/afk.gen.ts). The platform's name comes from the server; nothing here names one.
import type { Newsletter } from "../../api/afk.gen";
import type { St } from "../../ui/settings";
export type { Newsletter, NewsletterPlatform } from "../../api/afk.gen";

export const NEWSLETTER_API = "/api/newsletter";

/** the newsletter's state: ready, connected but missing something, needs you, none */
export function nlSt(d: Newsletter): St {
  if (!d.platform) return ["open", "grey", "Not connected"];
  if (d.connection?.state && d.connection.state !== "connected") return ["warn", "amber", "Needs you"];
  if (d.ready && !d.missing.length) return ["check", "green", "Ready"];
  return d.connection ? ["warn", "amber", "Missing something"] : ["open", "grey", "Not connected"];
}

/** the Accounts row's line: the platform and what it waits for, or how to start */
export function nlLine(d: Newsletter | null): string {
  if (!d) return "Connect a provider";
  if (!d.platform) return "No platform connected · Connect a provider";
  return [d.name, d.audience, d.missing[0] || (d.ready ? "ready" : "")].filter(Boolean).join(" · ");
}
