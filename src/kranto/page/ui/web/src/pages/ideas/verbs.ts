// The decision on an open idea card, the same everywhere (Ideas, a topic's Ideas, the
// card's sheet): Pass asks why (one chip) and grades it not useful; Later puts it off for a
// week. Both are the server's: Pass is the grade, Later is ``idea.later``
// (POST /api/ideas/<n>/later). ⌘K and a row's menu take them as items (ideaItems).
import type { MenuItem } from "../../lib/app";
import { app } from "../../lib/shell.svelte";
import { GRADED, gkey } from "../../ui/grades.svelte";
import { popWith } from "../../ui/pop";
import ReasonPop from "../../ui/ReasonPop.svelte";
import { canDecide, cardNo, ideaTitle, type Idea } from "./ideas";

type Sent = Pick<Idea, "id" | "title"> & Partial<Idea>;

/** a small popover of reasons (a chip, a to f, or a few words typed), then onPick(why) */
export function reasonPop(anchor: HTMLElement, title: string, chips: string[], onPick: (why: string) => void): void {
  const L = app();
  if (!L) return;
  let done = false;
  const pick = (why: string): void => {
    if (done || !why) return;
    done = true;
    L.closePop();
    onPick(why);
  };
  const el = popWith(anchor, title, ReasonPop, { title, chips, pick });
  if (!el) return;
  el.addEventListener("keydown", (e) => {
    if ((e.target as HTMLElement).tagName === "INPUT") return;
    const n = "abcdef".indexOf(e.key);
    if (n >= 0 && n < chips.length) {
      e.preventDefault();
      pick(chips[n]!);
    }
  });
  (el.querySelector("button.chip") as HTMLElement | null)?.focus();
}

/** Pass's chips: the words a person reads, and the key the server keeps (feedback.CHIPS["idea"]) */
const IDEA_CHIPS: [string, string][] = [["not my topic", "not_my_topic"], ["already exists", "already_exists"], ["thin evidence", "thin_evidence"],
  ["not doable", "not_buildable"], ["wrong user", "wrong_user"]];
/** Pass: why (a chip or a few words), then the grade, the server's (H1: the card moves to
 * Passed with your reason) */
export function passIdea(btn: HTMLElement, i: Idea): void {
  const L = app();
  if (!L) return;
  const title = ideaTitle(i), card = i.card && i.card.number != null && !!L.host();
  reasonPop(btn, "Why pass?", IDEA_CHIPS.map((c) => c[0]), (why) => void L.act(btn, async () => {
    if (!card) throw new Error("Passing on a card needs the server: open Kranto through it.");
    // a grade like any other (feedback), with its chip as the reason
    const chip = IDEA_CHIPS.find((c) => c[0] === why)?.[1] || null;
    await L.api("/api/feedback", { target: "idea", target_id: String(i.card!.number), value: "not_useful", reasons: chip ? [chip] : [], note: chip ? null : "pass: " + why,
      origin: "ui", context: { route: location.hash.slice(1, 120), via: "pass" } });
    GRADED[gkey("idea", i.card!.number!)] = { value: "not_useful", reasons: chip ? [chip] : [] };
  }, () => {
    L.afkStale("/api/ideas");
    L.say(`Passed on "${title}" (${why}). It moves to Passed, kept with your reason.`);
  }));
}
/** the card number behind an idea: its own (a card's id is its number) */
const numberOf = (i: Sent): number | null => cardNo(i.id) ?? (i.card && i.card.number != null ? Number(i.card.number) : null);
/** Later: put a card off for a week (``idea.later``, the server: H1); it moves to Later and
 * comes back by itself. days 0 brings it back now */
export function laterIdea(btn: HTMLElement | null, i: Sent, days = 7): Promise<void> {
  const L = app();
  if (!L) return Promise.resolve();
  const n = numberOf(i);
  return L.act(btn, async () => {
    if (n == null) throw new Error("Only an idea card can be put off.");
    return L.api(`/api/ideas/${n}/later`, { days });
  }, (r) => {
    L.afkStale("/api/ideas");
    if (!days) {
      L.flash(`"${ideaTitle(i as Idea)}" is back in Waiting.`);
      L.render();
      return;
    }
    const iso = (r as { later_until?: string | null } | null)?.later_until;
    const until = new Date(iso ? Date.parse(iso) : Date.now() + days * 86400000).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "short" });
    L.flash(`"${ideaTitle(i as Idea)}" moves to Later until ${until}, then comes back by itself.`);
    L.render();
  });
}
/** an idea's verbs as items of ⌘K and a row's menu: Pass (p), Later (l), Open in Claude Code (c) */
export function ideaItems(i: Idea): MenuItem[] {
  const out: MenuItem[] = [];
  const at = (a: HTMLElement | null | undefined): HTMLElement => a || (document.getElementById("dscroll") as HTMLElement);
  if (canDecide(i)) out.push(
    { label: "Pass", key: "p", title: "Grade it not useful, say why, and close it (p)", run: (a) => passIdea(at(a), i) },
    { label: "Later", key: "l", title: "Put it off for a week: not waiting for you (l)", run: () => void laterIdea(null, i) });
  out.push({ label: "Open in Claude Code", key: "c", title: "The real Claude Code, in its own folder, with Kranto's context and tools (c)", run: () => app()?.openClaude("idea", i.id, i.title) });
  return out;
}
