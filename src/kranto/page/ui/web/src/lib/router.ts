// The hash routes, as data: nodes.json is every route the app has, read by the
// page and by the Python tests. A route is #/<node path>[/<object>][?filters][&sel=<key>]. The
// node path picks the navigator's entry and the list; an object segment (ideas/<id>,
// library/o/<id>, ...) picks the object's home node and draws the object in the detail pane. sel=
// names a row's object that is shown away from its home (an observation on a topic's page, a card
// on Needs you); parse() takes it out of the filters.
import NODES_JSON from "./nodes.json";

export interface Node {
  route: string;
  node?: string;
  list?: string;
  object?: string;
  redirect?: string;
  stage?: boolean;
  sel?: string;
  by_sel?: Record<string, string | undefined>;
  doors?: string;
  doors_by_sel?: Record<string, string | undefined>;
  said?: string;
  gone?: boolean;
}
/** Every route, the first match wins: ":x" is one segment; "stage" routes draw without the
 * panes; "redirect" routes are replaced, filters and the selection kept (by_sel: where a page
 * split, the selection's prefix picks the page it moved to; sel: the selection when none is
 * named); "sel" is the row a page opens with when none is named (a settings page's main group);
 * "doors" is where the route went in the doors (shell.doors): replaced only while they are on
 * ("doors_by_sel": where a selection of a page went, by its prefix: a repo's pane on Settings ›
 * Publishing was Build › Repos'). "said": what a redirect of a page that left says where it
 * lands ("Builds are not part of Kranto any more."). "gone": a redirect of a page that left the
 * product, which drops the old filters and selection (they named its objects, not the target's).
 * Anything else is Not found. */
export const NODES: readonly Node[] = NODES_JSON;

export interface Route {
  path: string[];
  q: Record<string, string>;
  sel: string | null;
}
export interface Match extends Omit<Node, "list"> {
  node: string;
  list: string[];
  id: string | null;
  base: string[];
}

export function parse(hash: string = location.hash): Route {
  const [p = "", qs] = hash.replace(/^#\/?/, "").split("?");
  const q: Record<string, string> = Object.fromEntries(new URLSearchParams(qs || ""));
  const sel = q.sel || null;
  delete q.sel;
  return { path: p.split("/").filter(Boolean).map(decodeURIComponent), q, sel };
}

export function href(path: string, q?: Record<string, string | number | null | undefined | false>): string {
  const s = new URLSearchParams();
  for (const k in q || {}) {
    const v = q?.[k];
    if (v) s.set(k, String(v));
  }
  const t = s.toString();
  return "#/" + path + (t ? "?" + t : "");
}

export const go = (path: string, q?: Record<string, string>): void => {
  location.hash = href(path, q);
};

/** The entry a path matches, its parameters filled in: {node, list, object, id (the first
 * parameter), base (the path up to it: an object's own route, without a section)}. */
export function matchRoute(path: string[]): Match | null {
  for (const n of NODES) {
    const pat = n.route ? n.route.split("/") : [];
    if (pat.length !== path.length || !pat.every((p, i) => p[0] === ":" || p === path[i])) continue;
    const at = pat.findIndex((p) => p[0] === ":");
    const params = pat.map((p, i) => (p[0] === ":" ? path[i] : null)).filter((x): x is string => x != null);
    let k = 0;
    const fill = (s: string | undefined) => s && s.replace(/:\w+/g, () => params[k++] ?? "");
    const node = fill(n.node) || "";
    k = 0;
    return {
      ...n,
      node,
      list: n.object ? (fill(n.list) || "").split("/") : path,
      id: params[0] || null,
      base: at >= 0 ? path.slice(0, at + 1) : path,
    };
  }
  return null;
}

/** sel= keys: a letter for the object's home, then its id (sel=o665 is #/library/o/665). */
export const SELS: Readonly<Record<string, string>> = {
  i: "ideas", o: "library/o", c: "library/clusters",
  s: "settings/sources", n: "settings/connections",
};

export function selCode(path: string[]): string | null {
  for (const [k, p] of Object.entries(SELS)) {
    const ps = p.split("/");
    if (path.length === ps.length + 1 && ps.every((x, i) => x === path[i])) return k + path[ps.length];
  }
  return null;
}

export function selPath(code: string | null | undefined): string[] | null {
  if (!code || code.length < 2) return null;
  const home = SELS[code[0] as string];
  return home ? [...home.split("/"), code.slice(1)] : null;
}

/** where an old route goes while the doors are on: nodes.json's doors with its
 * ":x" filled from the path by name ("topics/:id/evidence" → "watch/topic/:id/evidence"), its
 * filters under the route's own, and the selection kept unless the target names one (an object's
 * own route becomes its list with sel=: "ideas/:id" → "ideas?sel=i:id"). null: it stays. */
export function doorsOf(n: Pick<Node, "route" | "doors" | "doors_by_sel">, path: string[], q: Record<string, string>, sel: string | null): { path: string; q: Record<string, string>; sel: string | null } | null {
  const by = sel && n.doors_by_sel ? Object.entries(n.doors_by_sel).filter((e): e is [string, string] => !!e[1] && sel.startsWith(e[0])).sort((a, b) => b[0].length - a[0].length)[0] : undefined;
  const target = by ? by[1] : n.doors;
  if (!target) return null;
  const pat = n.route.split("/"), named: Record<string, string> = {};
  pat.forEach((p, i) => {
    if (p[0] === ":") named[p.slice(1)] = path[i] || "";
  });
  const to = target.replace(/:(\w+)/g, (_, k: string) => encodeURIComponent(named[k] ?? ""));
  const [p = "", qs] = to.split("?"), tq: Record<string, string> = Object.fromEntries(new URLSearchParams(qs || ""));
  const s = tq.sel || sel;
  delete tq.sel;
  return { path: p, q: { ...q, ...tq }, sel: s };
}

/** where a redirect route goes: its page (by_sel's, for a selection that moved elsewhere) and the
 * selection, kept, or the route's own when none was named */
export function redirectOf(m: Pick<Node, "redirect" | "sel" | "by_sel">, sel: string | null): { path: string; sel: string | null } {
  const s = sel || m.sel || null;
  const to = s && m.by_sel ? Object.entries(m.by_sel).filter(([k, v]) => v && s.startsWith(k)).sort((a, b) => b[0].length - a[0].length)[0] : undefined;
  return { path: (to && to[1]) || m.redirect || "", sel: s };
}
