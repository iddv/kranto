// Feedback (FB): the issue the sheet writes on Kranto's release repository, as the person who
// sends it. This file is the sheet's logic, with no page in it: the details it adds (each shown
// before anything is sent), the scrub over them, the issue's title and body, GitHub's prefilled
// new-issue link kept under the length GitHub takes, the draft this browser keeps, and the last
// few errors the page said. Feedback.svelte draws the sheet; src/kranto/page/feedback.py files.
//
// The scrub is the one Kranto's telemetry and Report to Kranto use (the server scrub.py,
// src/kranto/page/report.py): tokens and keys, e-mail addresses, phone numbers, @handles, card
// numbers, paths under a home (the home, the loop's, the tasks' become <home>, <loop>,
// <tasks>), the host name and the gh login. The details get two more: the names of what the
// person keeps in Kranto (topics, ideas, builds, projects) become [topic] and [title], and
// anything an error quoted becomes […]; an address in the page becomes its route's pattern.
// Filing scrubs again on the server and refuses what this did not catch, so nothing leaves
// without being shown.
import { NODES } from "../lib/router";

export const ISSUE_API = "api/feedback/issue";
/** an error's report (the server's GET /api/errors/<id>, RCA B3) */
export const REPORT_API = (id: string): string => `/api/errors/${encodeURIComponent(id)}`;
export interface ErrorReport { id: string; title: string; body: string; url: string }
export const MAX_URL = 6000;
export const KINDS = [["bug", "Bug"], ["idea", "Idea"], ["question", "Question"]] as const;
export type Kind = (typeof KINDS)[number][0];
export const kindWord = (k: Kind): string => (KINDS.find((x) => x[0] === k) || KINDS[0])[1];
export const LABEL = "feedback";

/** GET api/feedback/issue */
export interface FeedbackStatus {
  repo: string;
  gh: "ready" | "missing" | "signed_out" | "no_access" | "unknown";
  login: string | null;
  reachable: boolean;
  can_file: boolean;
  line: string;
  version: string;
  places: [string, string][];
  host: string;
}

// -- the scrub ---------------------------------------------------------------------------------
// the server scrub.py's secret patterns, in its order (secrets first, then the looser ones)
const SECRETS: RegExp[] = [
  /-----BEGIN [A-Z ]{0,20}PRIVATE KEY-----[\s\S]{0,20000}?-----END [A-Z ]{0,20}PRIVATE KEY-----/g,
  /\bsk-(?:or-v1-|ant-|proj-)?[A-Za-z0-9_-]{20,200}/g,
  /\bxai-[A-Za-z0-9]{20,200}/g,
  /\btvly-(?:dev-|prod-)?[A-Za-z0-9]{20,200}/g,
  /\bBSA[A-Za-z0-9_-]{24,200}/g,
  /\b(?:AKIA|ASIA)[0-9A-Z]{16}\b/g,
  /\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_.-]{16,4000}/g,
  /\bgithub_pat_[A-Za-z0-9_]{20,255}\b/g,
  /\bxox[abprs]-[A-Za-z0-9-]{10,255}\b/g,
  /\bAIza[0-9A-Za-z_-]{35}\b/g,
  /\beyJ[A-Za-z0-9_-]{8,2000}\.eyJ[A-Za-z0-9_-]{8,2000}\.[A-Za-z0-9_-]{8,2000}/g,
  /\bya29\.[A-Za-z0-9_-]{20,2000}/g,
  /\b(?:authorization|dpop)\s*[:=]\s*(?:bearer|dpop|token)?\s*[A-Za-z0-9._~+/=-]{12,4000}/gi,
  /\bbearer\s+[A-Za-z0-9._~+/=-]{20,4000}/gi,
  /\b(?:client_secret|access_token|refresh_token|code_verifier|app_password|device_code)=[^&\s"']{6,4000}/gi,
  /(?<=[?&])key=[^&\s"']{6,4000}/g,
];
const EMAIL = /[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,24}/g;
const CARD = /(?<![\d.])\b(?:\d[ -]?){12,18}\d\b(?![.\d])/g;
const SSN = /\b\d{3}-\d{2}-\d{4}\b/g;
const PHONE = /(?<![\w.])(?:\+\d{1,3}[ .-]?)?(?:\(\d{2,4}\)|\d{2,4})[ .-]\d{3,4}[ .-]\d{3,4}(?![\w.])|(?<![\w.])\+\d{9,14}(?![\w.])/g;
const USER = /(?<![\w/`])@[A-Za-z0-9_][A-Za-z0-9_.-]{1,30}[A-Za-z0-9_](?![\w.-]*\/)(?!\w)/g;
const HOME_ANY = /\/(?:home|Users)\/[A-Za-z0-9._-]+|\b[A-Za-z]:\\Users\\[A-Za-z0-9._ -]+/g;
// what an error quotes: "…", “…”, ‘…’ and '…' (not an apostrophe inside a word)
const QUOTED = /"[^"\n]{1,200}"|“[^”\n]{1,200}”|‘[^’\n]{1,200}’|(?<![\w])'[^'\n]{1,200}'(?![\w])/g;
const HASH_ROUTE = /#\/[^\s"'`)<>\]]*/g;

function luhn(digits: string): boolean {
  let total = 0;
  const parity = digits.length % 2;
  for (let i = 0; i < digits.length; i++) {
    let d = Number(digits[i]);
    if (i % 2 === parity) {
      d *= 2;
      if (d > 9) d -= 9;
    }
    total += d;
  }
  return total % 10 === 0;
}
const esc = (s: string): string => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** what this machine is to the scrub: its paths, its name, the gh login (from the status) */
export interface Machine {
  places: [string, string][];
  host: string | null;
  login: string | null;
}
/** the names of what the person keeps in Kranto: never in the details */
export interface Names {
  topics: string[];
  titles: string[];
}

/** report.scrub's: secrets, personal data, paths, the host and the login */
export function scrub(text: string, m: Machine): string {
  let out = text || "";
  for (const p of SECRETS) out = out.replace(p, "[secret]");
  out = out.replace(EMAIL, "[email]");
  out = out.replace(CARD, (s) => (luhn(s.replace(/\D/g, "")) ? "[card]" : s));
  out = out.replace(SSN, "[ssn]");
  out = out.replace(PHONE, "[phone]");
  out = out.replace(USER, "[user]");
  for (const [path, label] of [...(m.places || [])].sort((a, b) => b[0].length - a[0].length)) if (path && path !== "/") out = out.split(path).join(label);
  out = out.replace(HOME_ANY, "<home>");
  if (m.host && m.host.length > 2) out = out.replace(new RegExp(`(?<![\\w.-])${esc(m.host)}(?![\\w-])`, "g"), "<host>");
  if (m.login && m.login.length > 1) out = out.replace(new RegExp(`(?<![\\w-])${esc(m.login)}(?![\\w-])`, "g"), "<you>");
  return out;
}

/** the route's pattern: #/topics/:id/ideas for #/topics/7/ideas, #/ideas?sel=… for
 * #/ideas?sel=icard:3 (the query's keys, never their values; no id) */
export function routePattern(hash: string): string {
  const [p = "", qs = ""] = hash.replace(/^#\/?/, "").split("?");
  const path = p.split("/").filter(Boolean);
  const keys = [...new Set([...new URLSearchParams(qs).keys()].filter((k) => /^[a-z_]{1,20}$/.test(k)))].sort();
  const q = keys.length ? "?" + keys.map((k) => k + "=…").join("&") : "";
  if (!path.length) return "#/" + q;
  for (const n of NODES) {
    const pat = n.route ? n.route.split("/") : [];
    if (pat.length === path.length && pat.every((x, i) => x[0] === ":" || x === safeDecode(path[i]!))) return "#/" + n.route + q;
  }
  return "#/" + (/^[a-z-]{1,30}$/.test(path[0]!) ? path[0] : "…") + (path.length > 1 ? "/…" : "") + q; // not a route: its first word only
}
function safeDecode(s: string): string {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
}

/** the scrub, then the person's names and what was quoted: what the details say */
export function scrubDetail(text: string, m: Machine, n: Names): string {
  let out = scrub(text, m).replace(HASH_ROUTE, (h) => routePattern(h));
  const swap = (list: string[], label: string) => {
    const words = [...new Set(list.map((x) => (x || "").trim()).filter((x) => x.length >= 3))].sort((a, b) => b.length - a.length);
    for (let i = 0; i < words.length; i += 200) {
      const re = new RegExp(words.slice(i, i + 200).map(esc).join("|"), "gi");
      out = out.replace(re, label);
    }
  };
  swap(n.topics, "[topic]");
  swap(n.titles, "[title]");
  return out.replace(QUOTED, "[…]");
}

// -- the details -------------------------------------------------------------------------------
/** "Firefox 131", "Chrome 142", "Safari 26" */
export function browserOf(ua: string): string {
  const m = /Edg\/(\d+)/.exec(ua) || /OPR\/(\d+)/.exec(ua);
  if (m) return (ua.includes("Edg/") ? "Edge " : "Opera ") + m[1];
  for (const [re, w] of [[/Firefox\/(\d+)/, "Firefox"], [/Chrom(?:e|ium)\/(\d+)/, "Chrome"], [/Version\/(\d+)[.\d]* .*Safari\//, "Safari"]] as const) {
    const x = re.exec(ua);
    if (x) return `${w} ${x[1]}`;
  }
  return "another browser";
}
/** the OS family only: Linux, macOS, Windows, Android, iOS, ChromeOS */
export function osOf(ua: string): string {
  if (/Android/.test(ua)) return "Android";
  if (/iPhone|iPad|iPod/.test(ua)) return "iOS";
  if (/CrOS/.test(ua)) return "ChromeOS";
  if (/Windows/.test(ua)) return "Windows";
  if (/Mac OS X|Macintosh/.test(ua)) return "macOS";
  if (/Linux|X11/.test(ua)) return "Linux";
  return "another OS";
}

/** an error the page said, kept for the details (this tab only, never stored) */
export interface Seen { at: number; text: string }
const SEEN: Seen[] = [];
export const SEEN_MAX = 5;
export function noteError(text: string, at: number = Date.now()): void {
  const t = String(text || "").trim();
  if (!t) return;
  SEEN.push({ at, text: t.slice(0, 500) });
  if (SEEN.length > SEEN_MAX) SEEN.splice(0, SEEN.length - SEEN_MAX);
}
export const seenErrors = (): readonly Seen[] => SEEN;
export const forgetErrors = (): void => void SEEN.splice(0);

/** what the details are made of, before the scrub */
export interface Facts {
  version: string;
  layout: string;
  hash: string;
  ua: string;
  update: { checked_at?: string | null; ok?: boolean; error?: string | null; available?: string | null } | null;
  errors: readonly Seen[];
}
const hhmm = (t: number): string => new Date(t).toISOString().slice(11, 16);

/** the details block as it is sent; drop: the oldest errors left out to fit GitHub's link (said
 * in a line). The words Kranto writes (the version, the layout, the route's pattern, the browser)
 * are its own; what came from elsewhere (an update's error, the errors) is scrubbed with the
 * names too, and the whole block once more with the scrub, as the server does when it files. */
export function details(f: Facts, m: Machine, n: Names, drop = 0): string {
  const u = f.update;
  const free = (t: string) => scrubDetail(t.replace(/\s+/g, " ").trim(), m, n);
  const upd = !u ? "not known here" : !u.checked_at ? "not checked yet"
    : `last checked ${u.checked_at.slice(0, 16).replace("T", " ")} UTC: ${u.ok === false ? "failed: " + free(u.error || "no reason given") : u.available ? u.available.replace(/[^\w.+-]/g, "") + " available" : "up to date"}`;
  const errs = f.errors.slice(drop);
  const lines = [
    "### Details Kranto added",
    `- Kranto: ${f.version.replace(/[^\w.+() -]/g, "")}`,
    `- layout: ${f.layout}`,
    `- page: \`${routePattern(f.hash)}\``,
    `- browser: ${browserOf(f.ua)} on ${osOf(f.ua)}`,
    `- updates: ${upd}`,
    `- recent errors on this page: ${errs.length || drop ? "" : "none"}`.trimEnd(),
    ...errs.map((e) => `  - ${hhmm(e.at)} UTC: ${free(e.text)}`),
  ];
  if (drop) lines.push(`(trimmed to fit GitHub's link: the ${drop === 1 ? "oldest error" : `${drop} oldest errors`} left out)`);
  return scrub(lines.join("\n"), m);
}

// -- the issue ---------------------------------------------------------------------------------
export interface Draft { kind: Kind; text: string; include: boolean }
export interface Issue { title: string; body: string; details: string; labels: string[] }

/** "Bug: the brief's Run now did nothing" (the first line, at most 80 characters) */
export function titleOf(kind: Kind, text: string, m: Machine): string {
  const first = scrub((text || "").trim().split("\n")[0] || "", m).replace(/\s+/g, " ").trim();
  const cut = first.length > 80 ? first.slice(0, 79).replace(/\s+\S*$/, "") + "…" : first;
  return `${kindWord(kind)}: ${cut || "(no words)"}`;
}
/** the issue; report: an error's report Kranto kept (Send this error, RCA B3: the server wrote it
 * from Kranto's own words and code lines; scrubbed here once more), sent whether or not the details
 * are */
export function issue(d: Draft, f: Facts, m: Machine, n: Names, drop = 0, report: string | null = null): Issue {
  const det = d.include ? details(f, m, n, drop) : "";
  const rep = report ? scrub(report.trim(), m) : "";
  const body = [scrub(d.text.trim(), m), `**Kind:** ${kindWord(d.kind)} · sent with Feedback in Kranto`, rep, det].filter(Boolean).join("\n\n") + "\n";
  return { title: titleOf(d.kind, d.text, m), body, details: det, labels: [LABEL, d.kind] };
}

/** the release repository's issue form for it (the server .github/ISSUE_TEMPLATE/feedback.yml): its
 * one field's id is body, so the link fills it; the repository takes no blank issue */
export const TEMPLATE = "feedback.yml";
/** GitHub's new-issue page, prefilled: the form, the title, the body and the labels */
export function issueUrl(repo: string, title: string, body: string, labels: string[]): string {
  return `https://github.com/${repo}/issues/new?template=${TEMPLATE}&title=${encodeURIComponent(title)}&body=${encodeURIComponent(body)}&labels=${encodeURIComponent(labels.join(","))}`;
}
export const CUT_NOTE = "\n\n(the rest did not fit GitHub's link: paste it here)";

/** the issue as the link carries it, under MAX_URL: the oldest errors go first, then the person's
 * words are cut (both said) */
export function fitted(d: Draft, f: Facts, m: Machine, n: Names, repo: string, limit = MAX_URL, report: string | null = null): { issue: Issue; url: string; trimmed: string | null } {
  let x = issue(d, f, m, n, 0, report);
  let url = issueUrl(repo, x.title, x.body, x.labels);
  if (url.length <= limit) return { issue: x, url, trimmed: null };
  for (let drop = 1; d.include && drop <= f.errors.length; drop++) {
    x = issue(d, f, m, n, drop, report);
    url = issueUrl(repo, x.title, x.body, x.labels);
    if (url.length <= limit) return { issue: x, url, trimmed: `The link to GitHub holds about ${limit.toLocaleString("en")} characters: the ${drop === 1 ? "oldest error" : `${drop} oldest errors`} were left out of the details.` };
  }
  // still too long: the person's words, cut at a word with a line saying so
  let text = d.text;
  while (url.length > limit && text.length > 40) {
    text = text.slice(0, Math.floor(text.length * 0.85)).replace(/\s+\S*$/, "");
    x = issue({ ...d, text: text + CUT_NOTE }, f, m, n, d.include ? f.errors.length : 0, report);
    x.title = titleOf(d.kind, d.text, m);
    url = issueUrl(repo, x.title, x.body, x.labels);
  }
  return { issue: x, url, trimmed: `The link to GitHub holds about ${limit.toLocaleString("en")} characters: your words were cut (the rest is in your draft, to paste on GitHub) and the errors left out.` };
}

// -- the draft ---------------------------------------------------------------------------------
export const DRAFT_KEY = "kranto.feedback.draft";
const EMPTY: Draft = { kind: "bug", text: "", include: true };
export function loadDraft(): Draft {
  try {
    const d = JSON.parse(localStorage.getItem(DRAFT_KEY) || "null") as Partial<Draft> | null;
    if (!d || typeof d !== "object") return { ...EMPTY };
    return { kind: KINDS.some((k) => k[0] === d.kind) ? (d.kind as Kind) : "bug", text: typeof d.text === "string" ? d.text : "", include: d.include !== false };
  } catch {
    return { ...EMPTY };
  }
}
export function saveDraft(d: Draft): void {
  try {
    if (!d.text.trim() && d.kind === "bug" && d.include) localStorage.removeItem(DRAFT_KEY);
    else localStorage.setItem(DRAFT_KEY, JSON.stringify(d));
  } catch {
    /* a browser that keeps nothing: the draft lives while the sheet is open */
  }
}
export function clearDraft(): void {
  try {
    localStorage.removeItem(DRAFT_KEY);
  } catch {
    /* nothing kept */
  }
}
/** an error's Tell us: the draft says what went wrong (scrubbed as the details are), added to
 * what was already written */
export function withError(d: Draft, error: string, m: Machine, n: Names): Draft {
  const line = "Something went wrong: " + scrubDetail(error.trim(), m, n);
  if (d.text.includes(line)) return d;
  return { ...d, kind: "bug", text: (d.text.trim() ? d.text.trim() + "\n\n" : "") + line + "\n\nWhat I was doing: " };
}
