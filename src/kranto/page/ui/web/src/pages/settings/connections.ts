// Settings › Sources › Accounts (phases C and D): the server's /api/connections (your
// accounts, each with the sources that read with it; every provider with its flow, steps, fields
// and what it reads; how tokens are kept), its sign-ins (/connections/<key>/start leaves for the
// provider by navigation, never a form post; GitHub's device flow) and its pasted secrets
// (/api/connections/<key>/credentials). /api/connections is generated from the server's
// web/types.py (api/afk.gen.ts). A pasted secret is never kept: not here, not in any state, not
// after its request.
import type { ConnectionAccount as Account, ConnectionProvider as Provider } from "../../api/afk.gen";
import { dt, plural, rel } from "../../lib/format";
import { app } from "../../lib/shell.svelte";
import type { St } from "../../ui/settings";
export type { ConnectionAccount as Account, Connections, ConnectionProvider as Provider, ProviderField as Field } from "../../api/afk.gen";
export { CONNECTIONS_API } from "./sources.svelte";

/* How each provider connects (the server's PROVIDER_INFO.flow). */
export const HOW: Record<string, string> = { browser: "sign in", both: "sign in or app password", paste: "paste a token", client: "your own app" };
/* how each flow signs in, for What it reads */
export const SIGNIN: Record<string, string> = { browser: "Authorization code with PKCE and a single-use state that expires in 10 minutes. The token is exchanged by the server, encrypted, and never shown.",
  both: "AT Protocol OAuth as a loopback client: a pushed authorization request, PKCE, a single-use state, and a DPoP key of the server's own that every request is signed with. Or an app password, used once; only the session is kept.",
  paste: "Pasted, tested with one call, then encrypted. Never shown again, not even in part.",
  client: "Your own client (a Google Desktop app, an X Native App); authorization code with PKCE and a single-use state. The refresh token is encrypted and never shown." };
/* the hosts a browser sign-in can come back to (the site sends the browser back there) */
export const LOOPBACK = ["localhost", "127.0.0.1"];
/* what a provider's sign-in asks first: [its field, its label, a placeholder] */
export const ASKS: Record<string, [string, string, string]> = { mastodon: ["instance", "Instance", "mastodon.social"], bluesky: ["handle", "Handle", "name.bsky.social"] };

/** how a provider connects, in words: its flow, or that it is not offered */
export const howWord = (p: Provider): string => (p.state === "available" ? HOW[p.flow || ""] || p.flow || "" : "not offered");
/** an account's row: Needs you (the token was refused) or Connected, and its line */
export function acctWords(a: Account): { st: St; meta: string } {
  if (a.state === "needs_login") return { st: ["warn", "amber", "Needs you"], meta: (a.note || "The token was refused.") + ` Connect again to resume ${plural(a.sources.length, "source")}.` };
  return { st: ["check", "green", "Connected"], meta: [a.account, plural(a.sources.length, "source"), a.last_used_at ? "last used " + rel(dt(a.last_used_at)) : "not used yet"].join(" · ") };
}
/** a provider's row state: not offered, connected (n), its own client saved (YouTube's project,
 * X's app), not connected */
export function provSt(p: Provider, n: number): St {
  return p.state === "not_offered" ? ["closed", "grey", "Not offered"]
    : n ? ["check", "green", n > 1 ? `${n} connected` : "Connected"] : p.flow === "client" && p.client_set ? ["open", "blue", "Client saved"] : ["open", "grey", "Not connected"];
}
/** what a client provider's saved client is, in words: an id, or an id and a secret */
export const clientWords = (p: Provider): [string, string] =>
  (p.fields || []).some((f) => f.secret) ? ["Client id and secret saved, encrypted. ", "Remove them"] : ["Client id saved, encrypted. ", "Remove it"];
/** what the sign-in's return says (?connected= or ?error= on the way back from a provider) */
export const backWords = (q: Record<string, string>): { text: string; kind?: string } | null =>
  q.connected ? { text: `Connected ${q.connected}. Its sources are read with it from the next ingest run.` } : q.error ? { text: "Not connected: " + q.error, kind: "red" } : null;

/** what was typed in a sign-in's first field (Mastodon's instance, Bluesky's handle), by provider;
 * kept across draws until the sign-in leaves */
export const INSTANCE: Record<string, string> = {};

/* GitHub's device flow: the code to type at GitHub, then a poll no faster than GitHub's interval. */
export interface Device {
  key: string;
  verification_uri: string;
  user_code: string;
  interval: number;
  expires_in?: number;
  timer?: ReturnType<typeof setTimeout>;
}
export const DEVICE: { d: Device | null } = { d: null };
export function devicePoll(key: string): void {
  const D = DEVICE.d;
  if (!D || D.key !== key) return;
  clearTimeout(D.timer);
  D.timer = setTimeout(() => void pollOnce(key), Math.max(D.interval || 5, 1) * 1000 + 250);
}
/** one poll: pending (again after GitHub's interval), connected, declined or expired */
async function pollOnce(key: string): Promise<void> {
  const L = app();
  if (!DEVICE.d || location.hash !== "#/settings/connections/" + key || !L) {
    DEVICE.d = null;
    return;
  }
  try {
    const x = (await L.api(`/connections/${key}/device/poll`, {})) as { state: string; interval: number; account?: string };
    if (x.state === "pending") {
      if (DEVICE.d) DEVICE.d.interval = x.interval;
      devicePoll(key);
      return;
    }
    DEVICE.d = null;
    L.afkDrop();
    L.say(x.state === "connected" ? `Connected GitHub ${x.account}.` : x.state === "denied" ? "Not connected: you declined at GitHub." : "Not connected: the code expired. Start again.", x.state === "connected" ? "blue" : "red");
  } catch (e) {
    DEVICE.d = null;
    L.say((e as Error).message, "red");
  }
}
