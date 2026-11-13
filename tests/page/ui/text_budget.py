"""The helper-text budget, in a browser: visit the 54 pages of the plan's
harvest, count the words of always-visible helper text on each (sub-lines, group blurbs, hints,
notes, empty states, the sign-in box, the status bar's hint; content such as a hold's reason, a
build's one-liner, a lede or a tally is left out), and hold each page to its budget in
text_budget.json (the plan's "after" + 10%). Not part of the suite: CI has no browser. Run it on a
scratch copy of real data, read-only (every non-GET request is refused at the browser):

    python tests/page/ui/text_budget.py http://127.0.0.1:8766 [--write out.json]

Needs Playwright. The routes name objects of the owner's data (topic 2, card 114, the builds
Beliefline, Nextread, Driftwatch, NoteHatch); a page whose object is missing is skipped.
Raising a budget needs a reason in the PR."""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
BUDGET = json.loads((HERE / "text_budget.json").read_text())
ROUTES = {
    "today": "today", "today-sel-build": "today?sel=bnextread", "today-sel-source": "today?sel=s3", "review": "review", "topics": "topics",
    "topics-new": "topics/new", "topic-overview": "topics/2", "topic-evidence": "topics/2/evidence", "topic-evidence-sel": "topics/2/evidence?sel=o8335",
    "topic-themes": "topics/2/themes", "topic-ideas": "topics/2/ideas", "topic-builds": "topics/2/builds", "topic-sources": "topics/2/sources",
    "ideas": "ideas", "ideas-new": "ideas/new", "idea-open-card": "ideas/card:114", "idea-built": "ideas/i76b3867a",
    "builds": "builds", "build-held-ready": "builds/beliefline", "build-held": "builds/nextread", "build-public": "builds/driftwatch",
    "build-logs": "builds/notehatch/logs", "build-files": "builds/driftwatch/files?f=REPORT.md",
    "library": "library", "library-obs": "library/o/8335", "library-map": "library/map", "library-clusters": "library/clusters",
    "library-cluster": "library/clusters/0", "library-rollups": "library/rollups",
    "settings-sources": "settings", "settings-source": "settings/sources/1", "settings-add-source": "settings/sources/new", "settings-connections": "settings/connections",
    "settings-connection-github": "settings/connections/github", "settings-keys": "settings/keys", "settings-rules": "settings/rules", "settings-models": "settings/models",
    "settings-prompts": "settings/prompts", "settings-capabilities": "settings/capabilities", "settings-spend": "settings/spend", "settings-maintenance": "settings/maintenance",
    "settings-learning": "settings/learning", "settings-health": "settings/health", "settings-updates": "settings/updates", "settings-access": "settings/access",
    "settings-appearance": "settings/appearance", "welcome": "welcome", "hello": "hello",
}
# what counts: the plan's harvest selectors; content (a hold's reason, a one-liner, a lede, a
# tally, a fact) is left out by its element, and by its words where it shares a class with help
HARVEST = r"""() => {
  const words = s => (s || "").trim().split(/\s+/).filter(Boolean).length;
  const vis = el => { const r = el.getBoundingClientRect(), cs = getComputedStyle(el); return r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && cs.display !== "none"; };
  const HELP = ["#list .lsub", ".ghd .muted", ".lede", ".hint", "p.hint", ".note", ".flash", "p.muted", "p.small", ".empty", ".more", ".quiet-topics",
    ".pane-empty p", ".sec > p.muted", ".sec > p.small", ".box-b p.muted", ".composer .hint", ".keys", ".ph-meta", ".mark-empty p", ".tbn > span:first-child", ".field .hint", "#bar .hint"];
  // #s-claims: NG's claims check (2026-10-11, after the plan's baseline) says what the build's words claim: data
  const CONTENT = ".lede, .flash:not(#signin), .note, .r-meta.fail, .q-line, #judged, .kv, .facts, .ctx, .readme, .prose, pre, table, .clampw, #s-claims, .qcard p.mono";            // .qcard p.mono: a review item's facts (source, signal, date)
  const DATA = [/^\d[\d,]* of \d+ flows work/, /^all \d+ checks passed/, /^\d+ (new|sources?|topics?|builds?|ideas?|rollups?|observations?)\b/, /^(Held|Ready|Failed|Public) ·/,
    /^So far: /, /^in the last 24 hours$/, /^since /, /^mapped /, /^the map of /, /^the last \d+/, /^\d+(\.\d+)? (kept a day|of \d+)/, /^up to date/, /^Updated to /,
    /^Set in /, /^Needs: /, /^licence: /, /^The loop is /, /^about \d+ minutes? left/, /^\d+ of \d+$/, /stories, /, /^Topic: /, /^watching via /,
    /^Why( kept)?: /, /^resolves by /, /^hard checks only$/, /^\d+ of \d+ agree$/, /^last poll /, /^No update (running|yet)/, /^\d[\d.]* available/,
    /^[a-z0-9.+-]+(, [a-z0-9.+-]+){3,}$/,                                                  // a row of tags
    /^(Not read|Could not|The re-check failed)/];                                             // an error, as it is
  const seen = new Set(), out = [];
  for (const sel of HELP) for (const el of document.querySelectorAll(sel)) {
    if (!vis(el) || seen.has(el) || [...seen].some(s => s.contains(el))) continue;
    seen.add(el);
    const t = el.innerText.replace(/\s+/g, " ").trim();
    if (!t || words(t) < 3) continue;
    const content = !!(el.closest(CONTENT) || el.querySelector(CONTENT)) || DATA.some(r => r.test(t));
    out.push({ sel, text: t.slice(0, 300), words: words(t), content });
  }
  return out;
}"""


def run(base: str):
    res = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1360, "height": 900}, color_scheme="light")
        ctx.route("**/*", lambda r: r.abort() if r.request.method not in ("GET", "HEAD") else r.continue_())
        pg = ctx.new_page()
        for name, route in ROUTES.items():
            pg.goto(f"{base}/brb/#/{route}")
            try:
                pg.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            pg.wait_for_timeout(1500)
            if pg.locator("#dscroll .pane-empty .empty").filter(has_text="No such").count():
                res[name] = None
                continue
            items = pg.evaluate(HARVEST)
            res[name] = {"helper": sum(x["words"] for x in items if not x["content"]),
                         "content": sum(x["words"] for x in items if x["content"]), "items": items}
        b.close()
    return res


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8766"
    res = run(base)
    over, total = [], {"helper": 0, "plan_before": 0, "plan_after": 0}
    for name, r in res.items():
        bud = BUDGET.get(name)
        if r is None or not bud:
            print(f"{name:28s} skipped")
            continue
        total["helper"] += r["helper"]; total["plan_before"] += bud["before"]; total["plan_after"] += bud["after"]
        mark = "OVER" if r["helper"] > bud["budget"] else "ok"
        if mark == "OVER":
            over.append(name)
        print(f"{name:28s} helper {r['helper']:4d}  budget {bud['budget']:4d}  plan {bud['before']:4d} → {bud['after']:4d}  {mark}")
    cut = 1 - total["helper"] / total["plan_before"] if total["plan_before"] else 0
    print(f"total helper words {total['helper']} against the plan's {total['plan_before']} before and {total['plan_after']} after: {cut:.0%} fewer")
    if "--write" in sys.argv:
        Path(sys.argv[sys.argv.index("--write") + 1]).write_text(json.dumps({"total": total, "pages": res}, indent=1))
    if over:
        print("over budget:", ", ".join(over))
    sys.exit(1 if over else 0)


if __name__ == "__main__":
    main()
