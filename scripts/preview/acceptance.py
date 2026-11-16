#!/usr/bin/env python3
"""The preview's acceptance check (the first process change;).

Plays the owner's Gate A lines against a running preview, read-only: it signs in with a one-time
link from ``kranto-preview open`` (or ``--link``), every request but a GET is aborted in the page,
and nothing is pressed. Then the word test (with "cub") and the counts for the pages
 fixed. Exits 1 when a line fails; a line that needs a press, a model key or a person (Later
on a card, Write draft writing, a real send, the console's answer) is "skip", with why, and does
not fail.

    acceptance.py [--port 8766] [--link URL] [--fresh-port 8767 --fresh-link URL] [--topic Padel]
                  [--out FILE] [--arch-before FILE] [--only arch,tfix,...]

the lines run ``kranto archive --out <a temporary folder>`` and ``kranto doctor`` with the
preview's own install, and read its databases read-only.

Needs Playwright with Chromium (the server's dev extra; set PLAYWRIGHT_BROWSERS_PATH where they
are). Wave 3's tracks add their lines beside these (one function each, returning Results) and
call it from ``main``.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# the preview's folder (KRANTO_PREVIEW_ROOT, else ~/kranto-preview) and its command, the one in its
# bin/ (an older preview's folder keeps its own name for both)
ROOT = os.path.expanduser(os.environ.get("KRANTO_PREVIEW_ROOT") or "~/kranto-preview")
PREVIEW = next((str(c) for c in sorted(Path(ROOT, "bin").glob("*")) if os.access(c, os.X_OK)),
               os.path.join(ROOT, "bin", "kranto-preview"))
LAYOUTS = [("new-light", 1400, 900, "light"), ("new-dark", 1400, 900, "dark"),
           ("phone-light", 390, 844, "light"), ("phone-dark", 390, 844, "dark")]
NEW, PHONE = LAYOUTS[0], LAYOUTS[2]
# the word test, and the nouns for a person
WORDS = re.compile(
    r"\b(build(?:s|ing)?|built|projects?|repos?|repositor(?:y|ies)|publish(?:ing|ed)?|"
    r"pitch(?:es)?|invest|radar|broker|extension|pairing|shop|cubs?|tickets?|"
    r"practice run|classic|arrange)\b", re.I)
GONE_DOORS = re.compile(r"\b(Build|Projects|Repos|Cubs|Invest|Browser)\b")
COUNT = r"""(root) => {
  const el = document.querySelector(root) || document.body;
  // a control inside a closed <details> keeps its boxes in Chromium but is not seen: only the
  // closed one's own summary is
  const folded = (e) => {
    const shut = (x) => x && x.closest('details:not([open])');
    for (let d = shut(e); d; d = shut(d.parentElement)) {
      const s = [...d.children].find((c) => c.tagName === 'SUMMARY');
      if (!(s && s.contains(e))) return true;
    }
    return false;
  };
  const vis = (e) => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden'
    && !folded(e);
  const words = (el.innerText || '').split(/\s+/).filter((w) => /\w/.test(w)).length;
  const sel = 'a[href], button, input, select, textarea, summary';
  const ctl = [...el.querySelectorAll(sel)].filter(vis);
  const prim = [...el.querySelectorAll('.btn.primary')].filter(vis);
  // a button off the screen (the review's check); a link in a subnav that scrolls sideways is not
  const off = [...el.querySelectorAll('button, a.btn')].filter(vis)
    .filter((e) => e.getBoundingClientRect().right > innerWidth + 1)
    .map((e) => (e.innerText || e.id || '').trim().slice(0, 40));
  return { words, controls: ctl.length, primaries: prim.length, offscreen: off };
}"""
ROWS = r"""() => [...document.querySelectorAll('section[aria-labelledby=topic-start] li.row')]
  .map((r) => {
    const m = r.querySelector('.c-meta'), a = r.querySelector('.c-age');
    const t = r.querySelector('.r-title');
    return { title: t ? t.innerText : '', words: m ? m.innerText : '',
             shown: !!m && m.getClientRects().length > 0 && m.getBoundingClientRect().width > 0,
             age: a ? a.innerText : '', cut: !!a && a.scrollWidth > a.clientWidth + 1 };
  })"""
DOORS = r"""() => {
  const t = document.querySelector('#topbar, header.top, header');
  const b = document.querySelector('#doors-bottom, nav[aria-label="Doors"], #tabbar');
  return (t ? t.innerText : '') + ' | ' + (b ? b.innerText : '');
}"""
STRIP = r"""() => {
  const s = document.querySelector('#preview-strip');
  return s ? { text: s.innerText, cut: s.scrollWidth > s.clientWidth + 1 } : null;
}"""


@dataclass
class Result:
    line: str
    words: str
    state: str                       # pass, fail, skip; info is told and never fails
    said: str = ""
    seen: dict[str, Any] = field(default_factory=dict)


class Preview:
    """One signed-in browser on a preview's port; every non-GET aborted and counted."""

    def __init__(self, pw: Any, port: int, link: str):
        self.port, self.base = port, f"http://127.0.0.1:{port}"
        self.b = pw.chromium.launch()
        ctx = self.b.new_context()
        pg = ctx.new_page()
        pg.goto(link)
        pg.wait_for_load_state("networkidle")
        self.state = ctx.storage_state()
        ctx.close()
        self.aborted: list[str] = []
        self.errors: list[str] = []

    def page(self, layout: tuple, console: str = "min") -> tuple[Any, Any]:
        name, w, h, scheme = layout
        phone = w < 600
        ctx = self.b.new_context(viewport={"width": w, "height": h}, color_scheme=scheme,
                                 storage_state=self.state, is_mobile=phone, has_touch=phone)
        pg = ctx.new_page()
        pg.add_init_script(f"localStorage.setItem('kranto.console', '{console}')")
        pg.on("pageerror", lambda e: self.errors.append(f"{name}: {str(e)[:200]}"))

        def guard(route: Any) -> Any:
            r = route.request
            if r.method in ("GET", "HEAD"):
                return route.continue_()
            self.aborted.append(f"{r.method} {r.url[len(self.base):].split('?')[0]}")
            return route.abort()
        pg.route("**/*", guard)
        return ctx, pg

    def go(self, pg: Any, route: str, wait: int = 2500) -> None:
        pg.goto(self.base + "/" + route)     # the page at / (an older tree redirects / to /brb/)
        end = time.monotonic() + 20
        while time.monotonic() < end:
            try:
                if pg.evaluate("() => document.body && document.body.innerText.trim()"
                               ".length >= 40"):
                    break
            except Exception:  # noqa: BLE001 - the page is still loading
                pass
            pg.wait_for_timeout(200)
        # then the page's own reads: a busy preview answers in more than the wait below, and a
        # line must never measure "Loading…" (the skeleton rows) as the page
        end = time.monotonic() + 20
        while time.monotonic() < end:
            try:
                if not pg.evaluate("() => !!document.querySelector('#app .loading')"):
                    break
            except Exception:  # noqa: BLE001 - the page is still loading
                pass
            pg.wait_for_timeout(250)
        pg.wait_for_timeout(wait)

    def api(self, pg: Any, path: str) -> Any:
        r = pg.request.get(self.base + path)
        try:
            return r.json() if r.ok else {"_status": r.status}
        except Exception:  # noqa: BLE001 - not JSON
            return {"_status": r.status, "_text": r.text()[:200]}

    def close(self) -> None:
        self.b.close()


def _text(pg: Any, sel: str = "body") -> str:
    return str(pg.evaluate(
        "(s) => (document.querySelector(s) || document.body).innerText || ''", sel))


def _root(pg: Any) -> str:
    for sel in ("#list", "#welcome", "main", "#app"):
        if pg.query_selector(sel):
            return sel
    return "body"


def ok(line: str, words: str, good: bool, said: str, **seen: Any) -> Result:
    return Result(line, words, "pass" if good else "fail", said, seen)


def skip(line: str, words: str, why: str) -> Result:
    return Result(line, words, "skip", why)


def _counted(c: dict[str, Any]) -> str:
    return f"{c['words']} words, {c['controls']} controls, {c['primaries']} primaries"


# -- the owner's Gate A lines, as far as a copy without a model key plays them ---------

def prev_lines(p: Preview) -> list[Result]:
    out = []
    ctx, pg = p.page(NEW)
    st = p.api(pg, "/api/status")
    pv = st.get("preview") or {}
    p.go(pg, "#/home")
    bar = _text(pg, "#bar") if pg.query_selector("#bar") else _text(pg)
    out.append(ok("PREV-1", "I open the link and see my Kranto; the bar says it is a preview and "
                  "nothing is posted",
                  "Preview" in bar and "Nothing is posted" in bar and bool(st.get("topics")),
                  pv.get("line") or "no preview line", topics=len(st.get("topics") or [])))
    ctx.close()
    ctx, pg = p.page(PHONE)
    p.go(pg, "#/home")
    strip = pg.evaluate(STRIP)
    out.append(ok(" phone", "on my phone the strip says it whole",
                  bool(strip) and not strip["cut"], strip["text"] if strip else "no strip"))
    ctx.close()
    out.append(skip("PREV-2", "On Post I choose Send: \"This is the preview: nothing is sent.\"",
                    "a press (Send); its answer is a test (tests/test_preview.py)"))
    out.append(skip("PREV-3", "live says what it said; no file of live's is newer",
                    "a listing on the machine, not a page"))
    commits = pv.get("commits") or {}
    out.append(ok("PREV-4", "kranto-preview status names the commit it runs",
                  bool(commits.get("kranto")), f"kranto {str(commits.get('kranto'))[:12]}"))
    return out


PREVIEW_PY = os.path.join(ROOT, "venv", "bin", "python")


def _prose_check(text: str, site: str) -> dict[str, Any] | None:
    """Kranto's own checker on a text (local, no model call): in process when the server imports
    here, else with the preview's own install (as the lines run its ``kranto``); None when
    neither can"""
    try:
        from kranto import prose as prose_mod
    except ImportError:
        if not os.path.exists(PREVIEW_PY):
            return None
        code = ("import json, sys; from kranto import prose; "
                "print(json.dumps(prose.check(sys.stdin.read(), sys.argv[1])))")
        try:
            r = subprocess.run([PREVIEW_PY, "-I", "-c", code, site], input=text, text=True,
                               capture_output=True, timeout=120)
            return json.loads(r.stdout) if r.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return None
    return prose_mod.check(text, site)


def hour_lines(p: Preview, topic: str) -> list[Result]:
    out = []
    ctx, pg = p.page(NEW)
    topics = p.api(pg, "/api/topics").get("topics") or []
    t = next((x for x in topics if str(x.get("name", "")).lower() == topic.lower()), None)
    if t is None:
        ctx.close()
        return [ok("HOUR-1", f"{topic}'s page shows four rows", False, f"no topic {topic}")]
    start = p.api(pg, f"/api/topics/{t['id']}/start")
    rows = start.get("rows") or []
    ctx.close()
    for layout in (NEW, PHONE):
        ctx, pg = p.page(layout)
        p.go(pg, f"#/topics/{t['id']}")
        # the rows come with the topic's start read: on a slow draw (the phone's first) wait for
        # them rather than reading an empty section
        if not start.get("done"):
            with contextlib.suppress(Exception):  # not drawn in time: the line says what it saw
                pg.wait_for_function("() => document.querySelectorAll("
                                     "'section[aria-labelledby=topic-start] li.row').length >= 4",
                                     timeout=8000)
        drawn = pg.evaluate(ROWS)
        fine = len(drawn) == 4 and all(r["shown"] and not r["cut"] for r in drawn)
        good = (start.get("done") and not drawn) or fine
        said = "; ".join(f"{r['title']}: {r['words']} {r['age']}".strip() for r in drawn)
        if not said:
            said = "its first idea exists: the rows left" if start.get("done") else "no rows"
        out.append(ok(f" {layout[0]}", f"{topic}'s page shows four rows, each with its "
                      "words and a time", bool(good), said,
                      api_rows=[(r.get("title"), r.get("state"), r.get("at")) for r in rows]))
        ctx.close()
    news = next((r for r in rows if r.get("key") == "brief"), {})
    out.append(ok(" (D8)", f"News is on for {topic}, so its first brief can come",
                  news.get("state") != "off", news.get("words") or "no brief row"))
    out.append(skip("HOUR-2", "within the hour News has its first brief",
                    "needs a model key and jobs on"))
    out.append(skip("HOUR-4", "Later on a card moves it to Later; loop.db unchanged",
                    "a press (Later)"))
    out.append(skip("HOUR-5", "Welcome in three steps, under ten minutes",
                    "timed by a person on the fresh home"))
    out.append(skip("HOUR-6", "the console names a card that is on Ideas", "a model answer"))
    return out


def post_lines(p: Preview) -> list[Result]:
    out = []
    ctx, pg = p.page(NEW)
    post = p.api(pg, "/api/post")
    drafts = post.get("drafts") or []
    issue = next((d for d in drafts if d.get("kind") == "newsletter"), None)
    out.append(ok("POST-1", "on Post the newsletter draft waits, though its two days passed",
                  issue is not None, issue.get("title", "") if issue else "none waiting"))
    if issue:
        r = pg.request.get(f"{p.base}/api/post/d/{issue['id']}.md")
        md = r.text() if r.ok else ""
        out.append(ok("POST-2", "Copy and Download give the markdown with every item and its "
                      "link, with no account", r.ok and md.count("](http") >= 1,
                      f"{len(md)} characters, {md.count('](http')} links"))
    p.go(pg, "#/post")
    head = pg.query_selector("#post-write")
    out.append(ok("POST head (fix 6a)", "Post's head has a plain Write a post", bool(head),
                  head.inner_text().strip() if head else "missing"))
    out.append(ok("POST-6", "Earlier drafts are there and still open", bool(post.get("earlier")),
                  f"{len(post.get('earlier') or [])} earlier drafts"))
    ctx.close()
    out.append(skip("POST-3", "Write draft writes a blog draft within a minute",
                    "needs a model key"))
    out.append(skip("POST-4", "the console writes a post about the open card", "a model answer"))
    out.append(skip("POST-5", "a send says \"Sent to 3 on …\"", "a real send: Gate B"))
    return out


def prose_lines(p: Preview) -> list[Result]:
    """the profile answers, the three verbs are there, a waiting
    draft's text is checked (locally, by Kranto's own checker: the walk sends GETs only)."""
    out = []
    ctx, pg = p.page(NEW)
    prof = p.api(pg, "/api/prose")
    floor = next((g for g in prof.get("guides") or [] if g.get("name") == "floor"), {})
    out.append(ok("PROSE-1", "Kranto has my prose profile: the floor always on, the checker's "
                  "rules, a template per site", bool(floor.get("always"))
                  and len(prof.get("rules") or []) >= 20 and len(prof.get("sites") or []) >= 8,
                  f"{len(prof.get('rules') or [])} rules, {len(prof.get('sites') or [])} sites, "
                  f"strictness {prof.get('strictness')}"))
    migrated = prof.get("migrated") or {}
    first = (prof.get("voice") or "").splitlines()[:1]
    out.append(ok("PROSE-2", "my old tone setting is my voice card's first line",
                  not migrated or (bool(first) and first[0].startswith("Tone:")),
                  f"migrated {sorted(migrated) or 'nothing (no tone written)'}; card starts "
                  f"{first[0][:60] if first else '(empty)'!r}"))
    kinds = {v.get("kind") for v in (p.api(pg, "/api/verbs").get("verbs") or [])}
    want = {"prose.check", "prose.voice", "prose.learn"}
    out.append(ok("PROSE-3", "my assistant can check a draft, change my voice and learn from my "
                  "edits (three verbs)", want <= kinds, f"{sorted(want & kinds)}"))
    drafts = p.api(pg, "/api/post").get("drafts") or []
    ctx.close()
    if not drafts:
        out.append(skip("PROSE-4", "a waiting draft's text shows its flags", "no draft waits"))
    else:
        ctx, pg = p.page(NEW)
        r = pg.request.get(f"{p.base}/api/post/d/{drafts[0]['id']}.md")
        got = _prose_check(r.text() if r.ok else "", "blog")
        ctx.close()
        if got is None:
            out.append(skip("PROSE-4", "a waiting draft's text shows its flags",
                            "Kranto is not importable here, nor the preview's install"))
        else:
            out.append(ok("PROSE-4", "a waiting draft's text shows its flags (the page draws "
                          "them in PR 2)", r.ok and "verdict" in got,
                          f"{drafts[0].get('title', '')[:50]}: {got['verdict']} "
                          f"(score {got['score']})"))
    out.append(skip("PROSE-5", "Welcome's \"How you write\" step is there and skippable",
                    "PROSE's PR 2 (places it)"))
    out.append(skip("PROSE-6", "Settings › Posting › Voice is within the budget",
                    "played as (the F2 draws the page)"))
    # the checker knows what a post is for, and each writer's
    # model is its own setting (unset until the owner's read chooses one)
    rules = {r.get("id") for r in prof.get("rules") or []}
    claims = {"claim.announced", "claim.caveats", "claim.no_hook", "claim.sections",
              "claim.skeleton", "claim.restates"}
    models = prof.get("writer_models")
    out.append(ok("PROSE-7", "Kranto flags a post that announces its points, catalogues what is "
                  "unknown, opens on nothing or only restates the facts", claims <= rules,
                  f"{len(claims & rules)} of {len(claims)} round-2 rules"))
    out.append(ok("PROSE-8", "each writer's model is its own setting, apart from the watcher's",
                  isinstance(models, dict) and {"blog", "toot"} <= set(models),
                  f"writer_models {models}"))
    out.append(skip("PROSE-9", "Write a post asks for my angle and proposes three",
                    "a model call (POST /api/post/angles); draws the step"))
    return out


def shell_lines(p: Preview) -> list[Result]:
    out = []
    bad: dict[str, str] = {}
    for layout in (NEW, PHONE):
        ctx, pg = p.page(layout)
        for route in ("#/home", "#/news", "#/ideas", "#/watch", "#/post", "#/settings"):
            p.go(pg, route, 1500)
            doors = pg.evaluate(DOORS)
            missing = [d for d in ("News", "Ideas", "Watch", "Post") if d not in doors]
            gone = GONE_DOORS.findall(doors)
            if missing or gone:
                bad[f"{layout[0]} {route}"] = f"missing {missing}, gone doors {gone}"
        ctx.close()
    out.append(ok("SHELL-1", "every page has News, Ideas, Watch and Post; nowhere Build, "
                  "Projects, Repos, Cubs, Invest or Browser", not bad,
                  "the doors are right everywhere" if not bad else json.dumps(bad)[:300]))
    ctx, pg = p.page(NEW)
    home = p.api(pg, "/api/home")
    ideas = p.api(pg, "/api/ideas?embedding=ref").get("ideas") or []
    waiting = sum(1 for i in ideas if i.get("state") == "waiting")
    total = (home.get("ideas") or {}).get("total")
    out.append(ok(" (fix 2)", "the home's count of new ideas is Ideas' Waiting",
                  total == waiting, f"home {total}, Ideas waiting {waiting}"))
    away = home.get("away")
    p.go(pg, "#/home")
    text = _text(pg, _root(pg))
    out.append(ok("SHELL-3", "on a copy last opened 9 days ago the home says \"You were away "
                  "for 9 days\" and one list of five", bool(away) and "You were away" in text,
                  (away or {}).get("sentence") or "not away (run: kranto-preview away 9)"))
    if away:
        p.go(pg, "#/ideas?since=" + str(away.get("since")))
        groups = pg.evaluate("() => [...document.querySelectorAll('.grp h2')]"
                             ".map((h) => h.textContent)")
        out.append(ok(" link (fix 5a)", "Everything since … opens Ideas since then",
                      len(groups) == 1 and str(groups[0]).startswith("Since"), " · ".join(groups)))
    act = p.api(pg, "/api/activity")
    inc = [i for i in act.get("incidents") or []
           if i.get("provider") == "broker" or "broker" in str(i.get("id"))]
    out.append(ok(" Needs you (fix 4)", "Needs you shows nothing of Invest", not inc,
                  "no broker incident" if not inc else inc[0].get("title", "")))
    post = p.api(pg, "/api/post")
    n_d, n_s, n_a = (len(post.get(k) or []) for k in ("drafts", "sent", "accounts"))
    out.append(ok("SHELL-4", "Post: my drafts, nothing sent, three accounts", n_d > 0 and n_a == 3,
                  f"{n_d} drafts, {n_s} sent, {n_a} accounts"))
    p.go(pg, "#/settings/accounts")
    landed = pg.url.split("#")[-1]
    p.go(pg, "#/settings")
    seven = pg.evaluate("() => [...document.querySelectorAll("
                        "'section[aria-labelledby=set-pages] li.row .r-title')]"
                        ".map((e) => e.textContent)")
    out.append(ok("SHELL-5", "Settings has seven pages; my bookmark to Settings › Accounts lands "
                  "on Posting", len(seven) == 7 and landed.startswith("/settings/posting"),
                  f"{len(seven)} pages; accounts → {landed}"))
    ctx.close()
    ctx, pg = p.page(NEW, console="open")
    p.go(pg, "#/home", 3500)
    starters = pg.evaluate("() => [...document.querySelectorAll('#console-starters .cs-q')]"
                           ".map((e) => e.textContent)")
    first = _text(pg, "#console-firstrun") if pg.query_selector("#console-firstrun") else ""
    out.append(ok("SHELL-6", "an empty console offers three questions", len(starters) == 3,
                  " · ".join(starters) + (f" (and: {first})" if first else "")))
    ctx.close()
    out.append(skip(" answer", "the first answers from my library",
                    "the owner answers Claude Code's trust prompt once, then a model answers"))
    ctx, pg = p.page(PHONE)
    p.go(pg, "#/home")
    tab = pg.query_selector("#tab-console")
    sheet = ""
    if tab:
        tab.click()
        pg.wait_for_timeout(1500)
        sheet = _text(pg, "#console")
    terminal = pg.query_selector("#console .xterm")
    shown = bool(terminal and terminal.is_visible())
    out.append(ok("SHELL-7", "on my phone ✦ shows what waits and what it last said, not a "
                  "terminal", "What it last said" in sheet and not shown,
                  sheet.replace("\n", " ")[:160]))
    ctx.close()
    return out


# -- what the two outside testers found (A: false words and dead ends; B: what left) ---------

# the owner's own site's name, which a stranger's page must never show (set it for your copy)
SITE = re.compile(os.environ.get("KRANTO_ACCEPT_SITE", r"example\.?com"), re.I)
HREFS = "() => [...document.querySelectorAll('a')].map((a) => a.getAttribute('href') || '')"


# Settings' page links and the crumbs, as SOC-7 leaves them out: (words, controls)
SETTINGS_CHROME = r"""(root) => {
  const el = document.querySelector(root) || document.body;
  const names = new Set(['Home', 'Settings', '?', 'Overview', 'Watching', 'Posting', 'Assistant',
    'Spend', 'Privacy & access', 'System', 'Appearance']);
  const ctl = [...el.querySelectorAll('a[href], button')].filter((e) =>
    e.getClientRects().length > 0 && names.has((e.textContent || '').trim()));
  const words = ctl.map((e) => (e.textContent || '').split(/\s+/).filter((w) => /\w/.test(w))
    .length).reduce((a, b) => a + b, 0);
  return { words, controls: ctl.length };
}"""


def social_lines(p: Preview) -> list[Result]:
    """SOCIAL's lines (short posts for the sites people use), as the owner's note of 13 November
    changes them: two ways only (Open, or post directly after a yes), Open first, Substack and
    LinkedIn not offered, no "copy and open" anywhere, the preview refuses every send. GETs
    only: a line that needs a write (a model answer, a ticked site) says so and is skipped."""
    out = []
    ctx, pg = p.page(NEW)
    got = p.api(pg, "/api/post/sites")
    offered = got.get("sites") or []
    gone = {g.get("id"): g for g in got.get("not_offered") or []}
    out.append(ok("SOC-0", "every site Kranto offers opens first (LinkedIn, with no Open, is "
                  "posted directly only); none is copy and open",
                  bool(offered) and all((s.get("ways") or [""])[0] == "open"
                                        or s.get("ways") == ["direct"] for s in offered)
                  and all(set(s.get("ways") or []) <= {"open", "direct"} for s in offered),
                  ", ".join(f"{s.get('name')}: {' or '.join(s.get('ways') or [])}"
                            for s in offered)))
    li = next((s for s in offered if s.get("id") == "linkedin"), {})
    out.append(ok("SOC-6", "Substack is not offered, with its reason; LinkedIn only as Post "
                  "directly", bool(gone.get("substack", {}).get("why"))
                  and li.get("ways") == ["direct"],
                  f"substack: {gone.get('substack', {}).get('why')}; linkedin: "
                  f"{' or '.join(li.get('ways') or []) or 'missing'}"))
    post = p.api(pg, "/api/post")
    short = [d for d in post.get("drafts") or [] if d.get("kind") == "short"]
    p.go(pg, "#/post")
    words = _text(pg, "#app")
    p.go(pg, "#/settings/posting")
    words += _text(pg, "#app")
    c = pg.evaluate(COUNT, _root(pg))
    # the page's own content: the crumbs and Settings' eight page links (the same on every
    # Settings page, counted by COUNT settings) are left out of SOC-7's budget
    chrome = pg.evaluate(SETTINGS_CHROME, _root(pg))
    own = {**c, "words": c["words"] - chrome["words"],
           "controls": c["controls"] - chrome["controls"]}
    ticked = sum(1 for s in offered if s.get("ticked"))
    out.append(ok("SOC-7", f"Settings › Posting fits: 80 words or fewer, 7 controls or fewer "
                  f"({ticked} sites ticked on this copy; Settings' own links left out)",
                  own["words"] <= 80 and own["controls"] <= 7, _counted(own), count=c,
                  chrome=chrome))
    add = pg.query_selector("#posting-add")
    sheet = ""
    if add:
        add.click()
        pg.wait_for_timeout(600)
        sheet = _text(pg, "#dlg") if pg.query_selector("#dlg") else ""
    out.append(ok("SOC-6 page", "Add a site lists the rest and, under Not possible today, "
                  "Substack with its reason", "Not possible today" in sheet and "Substack" in sheet,
                  sheet[:160] or "no Add a site"))
    words += sheet
    out.append(ok("SOC no copy", "no page offers copy and open", "copy and open" not in
                  words.lower(), "none" if "copy and open" not in words.lower() else "found"))
    p.go(pg, "#/settings/toot")
    landed = pg.url.split("#")[-1]
    out.append(ok("SOC redirect", "my old address for the toot's settings lands on Posting",
                  landed.startswith("/settings/posting"), landed))
    if short:
        d = p.api(pg, f"/api/post/d/{short[0]['id']}")
        out.append(ok("SOC-2", "a short post's parts are each within the site's limit, its "
                      "siblings named", all(x.get("used", 0) <= (d.get("limit") or {}).get(
                          "max", 0) for x in d.get("parts") or []) and bool(d.get("siblings")),
                      f"{d.get('site')}: " + ", ".join(str(x.get("used"))
                                                       for x in d.get("parts") or [])))
        p.go(pg, f"#/post/d/{short[0]['id']}")
        btn = pg.query_selector("#draft-open")
        off = btn is not None and (btn.get_attribute("aria-disabled") == "true"
                                   or btn.get_attribute("disabled") is not None)
        out.append(ok("SOC-4", "Open is the first button; on the preview it is off and says "
                      "nothing is posted", off and "nothing is posted" in _text(pg, "#draft-sheet"),
                      _text(pg, "#draft-verbs")[:120]))
    else:
        out.append(skip("SOC-2", "a short post's parts within the site's limit",
                        "no short post on this copy (it needs a model answer)"))
        out.append(skip("SOC-4", "Open first, off on the preview", "no short post on this copy"))
    out += reach_and_hours_lines(p, pg)
    ctx.close()
    out.append(skip("SOC-1", "Write a post › Short posts: one row naming the sites",
                    "needs a model key (the angles and the write); the scratch install's real "
                    "write is in the report"))
    out.append(skip("SOC-3", "an edit of a short post waits", "a write on the copy"))
    out.append(skip("SOC-5", "Post to Bluesky on the preview says nothing is posted",
                    "a connected posting account on the copy (tests: test_social.py)"))
    out.append(skip("SOC-11", "the console writes short posts; nothing is sent", "a model answer "
                    "(tests: test_social_routes.py)"))
    out.append(skip("SOC-12", "I posted it records posted by you, nothing sent",
                    "a write on the copy (tests: test_social.py)"))
    return out


def reach_and_hours_lines(p: Preview, pg) -> list[Result]:
    """SOC-9 and SOC-10, read-only: a sent post's numbers on Sent and the sites that give none
    said once; the Scheduled group and its Cancel. A press (Schedule, Cancel) is never made on
    the copy: the tests hold them (test_post_hours.py, test_post_reach.py)."""
    out: list[Result] = []
    post = p.api(pg, "/api/post")
    sent = post.get("sent") or []
    counted = [r for r in sent if (r.get("reach") or {}).get("words")]
    p.go(pg, "#/post")
    page = _text(pg, "[aria-labelledby=post-sent]")
    if counted:
        w = counted[0]["reach"]["words"]
        out.append(ok("SOC-9", "a sent post shows its replies, reposts and likes", w in page, w))
    else:
        out.append(skip("SOC-9", "a sent post's numbers on Sent",
                        "no sent post with numbers on this copy (tests: test_post_reach.py)"))
    gone = {r.get("site") for r in sent} & {"linkedin", "x"}
    if gone:
        foot = post.get("reach_foot") or ""
        out.append(ok("SOC-9 foot", "Sent says once which sites give no numbers",
                      bool(foot) and page.count(foot) == 1, foot[:120] or "no foot"))
    learned = p.api(pg, "/api/post/learned")
    out.append(ok("SOC-9 learned", "what was learned answers per site, nothing under 8 a side",
                  isinstance(learned.get("sites"), list) and all(
                      x.get("lines") == [] or x.get("posts", 0) >= 16
                      for x in learned.get("sites") or []),
                  ", ".join(f"{x.get('word')}: {x.get('posts')}" for x in learned.get("sites")
                            or [])))
    held = post.get("scheduled")
    out.append(ok("SOC-10 read", "Post's read has the Scheduled group", isinstance(held, list),
                  f"{len(held or [])} scheduled"))
    if held:
        g = _text(pg, "[aria-labelledby=post-scheduled]")
        out.append(ok("SOC-10", "a scheduled post shows its hour and Cancel",
                      "Cancel" in g and "Goes " in g, g[:120]))
    else:
        out.append(skip("SOC-10", "Schedule moves the row to Scheduled with Cancel; on the "
                        "preview it says nothing is posted",
                        "a press on the copy (tests: test_post_hours.py)"))
    return out


def tfix_lines(p: Preview) -> list[Result]:
    """The copy: A's items a page shows without a press, and B's words where a stranger meets
    them (? keys, ⌘K, Settings › Prompts, the site cub's name)."""
    out = []
    ctx, pg = p.page(NEW, console="open")
    st = p.api(pg, "/api/status")
    p.go(pg, "#/console")
    landed = pg.url.split("#")[-1]
    text = _text(pg)
    opened = pg.evaluate("() => document.body.classList.contains('con-open')")
    out.append(ok("TFIX-3", "#/console opens the console, never \"There is no page\"",
                  "There is no page" not in text and not landed.startswith("/console") and opened,
                  f"landed on #{landed}; console {'open' if opened else 'not open'}"))
    sel = pg.evaluate("""() => { const s = document.querySelector('.con-head select');
      if (!s) return null; const c = getComputedStyle(s); return [c.color, c.backgroundColor]; }""")
    out.append(ok(" select (G14)", "the console's select is readable in light mode",
                  sel is None or sel[0] != sel[1], f"text {sel[0]} on {sel[1]}" if sel else "none"))
    ctx.close()
    ctx, pg = p.page(NEW)
    post = p.api(pg, "/api/post")
    out.append(ok("TFIX-4", "Post keeps a failed Write a post with its reason (GET /api/post's "
                  "failed)", isinstance(post.get("failed"), list),
                  f"{len(post.get('failed') or [])} failed writes kept"))
    p.go(pg, "#/post")
    gear = pg.evaluate("() => document.querySelector('#page-gear')?.getAttribute('href')")
    out.append(ok("TFIX-9", "Post's ⚙ goes to #/settings/posting", gear == "#/settings/posting",
                  str(gear)))
    hrefs = pg.evaluate(HREFS)
    masto = [h for h in hrefs if "connections/mastodon" in h]
    # Post's accounts are one line to Settings › Posting since short posts (SOCIAL): no
    # Mastodon link on Post is fine, and any there must be the posting one
    out.append(ok("TFIX-7", "Post's Mastodon Connect leads to the posting connection",
                  all(h.endswith("mastodon_post") for h in masto),
                  ", ".join(masto) or "accounts on Settings › Posting"))
    site = SITE.findall(_text(pg, "#app"))
    p.go(pg, "#/settings/posting")
    hrefs = pg.evaluate(HREFS)
    site += SITE.findall(_text(pg, "#app"))
    out.append(ok(" Settings", "Settings › Posting offers Mastodon's posting connection, "
                  "never the read-only one",
                  not any(h.endswith("connections/mastodon") for h in hrefs),
                  ", ".join(h for h in hrefs if "mastodon" in h) or "no Mastodon link"))
    feats = p.api(pg, "/api/features").get("features") or []
    site += [str(f.get("title")) for f in feats if SITE.search(str(f.get("title")))]
    out.append(ok(" G4", "a stranger reads \"Blog\", never the owner's site name, on Post, "
                  "Settings › Posting and the features", not site, ", ".join(site) or "none"))
    p.go(pg, "#/news")
    news = _text(pg, "#app")
    stuck = st.get("scheduler") is False
    out.append(ok("TFIX-8", "with the scheduler off News says why, never \"being written\"",
                  "being written" not in news and (not stuck or "scheduler off" in news),
                  "scheduler off" if stuck else "scheduler on"))
    # B: ? keys and ⌘K, with builds off
    p.go(pg, "#/home")
    pg.keyboard.press("?")
    pg.wait_for_timeout(800)
    keys = _text(pg, "#dlg") if pg.query_selector("#dlg") else ""
    hits = [ln.strip()[:100] for ln in keys.split("\n") if WORDS.search(ln)]
    out.append(ok(" B ? keys", "? keys has no Builds, Projects, traces or Build",
                  bool(keys) and not hits, "; ".join(hits) or f"{len(keys)} characters, clean"))
    pg.keyboard.press("Escape")
    pg.keyboard.press("Control+k")
    pg.wait_for_timeout(800)
    pal = _text(pg, "#pal") if pg.query_selector("#pal") else ""
    hits = [ln.strip()[:100] for ln in pal.split("\n") if WORDS.search(ln)]
    pg.fill("#pal-q", "console")
    pg.wait_for_timeout(600)
    offers = "Console" in _text(pg, "#pal-list")
    pg.fill("#pal-q", "post")
    pg.wait_for_timeout(400)
    pg.keyboard.press("Enter")
    pg.wait_for_timeout(1200)
    to = pg.url.split("#")[-1]
    out.append(ok(" B ⌘K", "⌘K has no Builds filter or entry; \"console\" offers the "
                  "console; \"post\" and enter open Post",
                  bool(pal) and not hits and offers and to.split("?")[0] == "/post",
                  f"post → #{to}; console {'offered' if offers else 'missing'}; "
                  + ("; ".join(hits) or "clean")))
    p.go(pg, "#/settings/prompts")
    heads = pg.evaluate("() => [...document.querySelectorAll('.grp h2')].map((h) => h.textContent)")
    bad = [h for h in heads if re.search(r"invest|radar|pitch|build|maintenance", h, re.I)]
    out.append(ok(" B Prompts", "Settings › Prompts shows no group of a feature that is off",
                  not bad, " · ".join(heads)))
    ctx.close()
    out.append(skip(" press", "Write a post with no key says \"no model key is set\" and "
                    "stays on Post", "a press; tests/test_post_write.py and post.svelte.test.ts"))
    out.append(skip("TFIX-5", "kranto_outcomes reports the failed post",
                    "an MCP call; the page tests/test_mcp_tools.py"))
    out.append(skip("TFIX-6", "Pause with builds off says Paused once", "a press (Pause)"))
    out.append(skip(" updates", "Check for updates says updates are off on the preview",
                    "a press (a POST); tests/test_activity_api.py"))
    return out


def tfix_fresh(p: Preview) -> list[Result]:
    """The fresh home: signed out, / says how to sign in and nothing of builds."""
    ctx = p.b.new_context(viewport={"width": 1400, "height": 900})
    pg = ctx.new_page()
    pg.route("**/*", lambda r: r.continue_() if r.request.method in ("GET", "HEAD") else r.abort())
    pg.goto(p.base + "/")
    pg.wait_for_timeout(3000)
    text = _text(pg)
    good = "Could not read the builds" not in text and not WORDS.search(_text(pg, "#app"))
    ctx.close()
    return [ok("TFIX-1", "signed out, / says how to sign in, never \"Could not read the builds\"",
               good and ("kranto open" in text or "Sign in" in text),
               text.replace("\n", " ")[:160])]


# -- the archive, the retired settings, the words, the tables ------------------

ROOT_PREVIEW = ROOT
ARCH_WORDS = re.compile(r"\b(broker(?:s|age)?|invest|radar|(?:browser )?extension|IBKR)\b", re.I)
GONE_KINDS = ("broker.", "browser.", "f.invest.", "f.radar.")
# the counts on live's copy of 11 November (the design's acceptance line 1)
ARCH_EXPECT = {
    "builds": 12,
    "projects": 10,
    "invest_cards": 12,
    "radar_trends": 15,
    "radar_proposals": 42,
}
ARCH_DOCTOR_FAILS_OK = {"api key"}  # the copy never holds the owner's keys


def _kranto(*args: str, timeout: int = 300) -> subprocess.CompletedProcess:
    exe = os.path.join(ROOT_PREVIEW, "venv", "bin", "kranto")
    return subprocess.run(
        [exe, "--home", os.path.join(ROOT_PREVIEW, "home"), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        cwd=ROOT_PREVIEW,
    )


def _db_counts(db: str, tables: list[str]) -> dict[str, int]:
    import sqlite3

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return {
            t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables if t in have
        }
    finally:
        con.close()


def _retired_tables(db: str) -> dict[str, int]:
    import sqlite3

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        names = [
            r[0]
            for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        ]
        return {
            n: con.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0]
            for n in names
            if n.startswith(("invest_", "radar_", "browser_"))
        }
    finally:
        con.close()


def _library(data: Path) -> Path:
    """the copy's library: its name from before the rename too (kranto.legacy, from this
    checkout's source)"""
    src = str(Path(__file__).resolve().parents[2] / "src")
    if src not in sys.path:
        sys.path.append(src)          # after an installed kranto, which has the same module
    from kranto import legacy

    return legacy.db_file(data)


def arch_lines(p: Preview, before: str | None) -> list[Result]:
    """the four lines: the archive's counts equal the databases', doctor's one line about
    Invest, no broker, Invest, radar or extension where a person or an assistant reads, and
    every invest_*, radar_* and browser_* table with the rows it had."""
    import tempfile

    out: list[Result] = []
    db = str(_library(Path(ROOT_PREVIEW, "home", "data")))
    loop_db = os.path.join(ROOT_PREVIEW, "loop", "loop.db")
    with tempfile.TemporaryDirectory() as tmp:  # never in the copy's own home
        got = _kranto("archive", "--out", tmp, "--json")
        try:
            wrote = json.loads(got.stdout)["counts"]
            page = _text_file(os.path.join(tmp, "index.html"))
        except (ValueError, KeyError, OSError):
            wrote, page = None, ""
    if wrote is None:
        out.append(
            ok(
                "ARCH-1",
                "kranto archive writes a page with my builds and their "
                "repositories, projects, Invest's cards, trends and proposals",
                False,
                (got.stderr or got.stdout).strip()[-200:],
            )
        )
    else:
        mismatch = {}
        for name, counts in wrote.items():
            real = _db_counts(loop_db if name in ("builds", "projects") else db, list(counts))
            if real != counts:
                mismatch[name] = {"archive": counts, "database": real}
        seen = {
            "builds": wrote["builds"].get("ideas"),
            "projects": wrote["projects"].get("projects"),
            "invest_cards": wrote["invest"].get("invest_cards"),
            "radar_trends": wrote["radar"].get("radar_trends"),
            "radar_proposals": wrote["radar"].get("radar_proposals"),
        }
        links = len(set(re.findall(r'<a href="(https://github\.com/[^"]+)"', page)))
        heads = re.findall(r"<h2>([^<]+)</h2>", page)
        out.append(
            ok(
                "ARCH-1",
                "kranto archive writes a page that lists my 12 builds with their "
                "repositories, 10 projects, 12 Invest cards, 15 trends and 42 proposals: "
                "the databases' counts",
                not mismatch and seen == ARCH_EXPECT and links >= 1,
                f"{seen}; {links} repository links; "
                + " · ".join(heads)
                + (f"; mismatch {mismatch}" if mismatch else ""),
                counts=wrote,
            )
        )
    doc = _kranto("doctor")
    lines = doc.stdout.splitlines()
    inv = [ln for ln in lines if ln.split()[1:2] == ["invest"]]
    fails = [ln for ln in lines if ln.startswith("FAIL")]
    other = [ln for ln in fails if " ".join(ln.split()[1:3]) not in ARCH_DOCTOR_FAILS_OK]
    settings = _text_file(os.path.join(ROOT_PREVIEW, "home", "kranto.yaml"))
    still = bool(re.search(r"(?m)^invest:\s*\n(?:\s+.*\n)*?\s+enabled:\s*true", settings))
    out.append(
        ok(
            "ARCH-2",
            "the preview, whose settings still say invest.enabled: true, starts; "
            "kranto doctor says one line about Invest and exits 0",
            len(inv) == 1 and "not part of Kranto" in inv[0] and not other,
            f"exit {doc.returncode}; invest.enabled: true still in the file: {still}; "
            + (inv[0].strip()[:150] if inv else f"{len(inv)} Invest lines")
            + (
                f"; FAIL lines besides the copy's missing key: {other}"
                if other
                else f"; {len(fails)} FAIL (the copy's missing key)"
                if fails
                else ""
            ),
        )
    )
    out += arch_words(p)
    now = _retired_tables(db)
    if before and os.path.exists(before):
        then = json.loads(_text_file(before))
        then = {k: v for k, v in then.items() if k.startswith(("invest_", "radar_", "browser_"))}
        changed = {
            k: [then.get(k), now.get(k)] for k in set(then) | set(now) if then.get(k) != now.get(k)
        }
        out.append(
            ok(
                "ARCH-4",
                "every invest_*, radar_* and browser_* table has the rows it had",
                not changed,
                f"{len(now)} tables, {sum(now.values())} rows"
                + (f"; changed {changed}" if changed else ", all as before"),
                counts=now,
            )
        )
    else:
        out.append(
            skip(
                "ARCH-4",
                "every invest_*, radar_* and browser_* table has the rows it had",
                f"no --arch-before file to compare with (now: {len(now)} tables,"
                f" {sum(now.values())} rows)",
            )
        )
    return out


def _text_file(path: str) -> str:
    try:
        return open(path, encoding="utf-8").read()
    except OSError:
        return ""


def arch_words(p: Preview) -> list[Result]:
    """no broker, Invest, radar or browser extension on the pages' chrome (Settings,
    ? keys, ⌘K, Settings › Prompts), in Kranto's status, kranto --help, the verbs and features
    the page reads, and the MCP tools' names and descriptions."""
    hits: dict[str, list[str]] = {}

    def look(where: str, text: str) -> None:
        found = [ln.strip()[:120] for ln in text.split("\n") if ARCH_WORDS.search(ln)]
        if found:
            hits[where] = found[:5]

    for layout in (NEW, PHONE):
        ctx, pg = p.page(layout)
        for k in (
            "",
            "/watching",
            "/posting",
            "/assistant",
            "/spend",
            "/privacy",
            "/system",
            "/appearance",
            "/prompts",
        ):
            p.go(pg, "#/settings" + k, 1500)
            look(f"{layout[0]} #/settings{k}", _text(pg, "#app"))
        if layout is NEW:
            p.go(pg, "#/home")
            pg.keyboard.press("?")
            pg.wait_for_timeout(800)
            look("? keys", _text(pg, "#dlg") if pg.query_selector("#dlg") else "")
            pg.keyboard.press("Escape")
            pg.keyboard.press("Control+k")
            pg.wait_for_timeout(800)
            look("⌘K", _text(pg, "#pal") if pg.query_selector("#pal") else "")
            pg.keyboard.press("Escape")
            p.go(pg, "#/home", 1500)
            look("the status bar", _text(pg, "#statusbar, footer"))
            verbs = p.api(pg, "/api/verbs")
            rows = verbs.get("verbs") if isinstance(verbs, dict) else None
            gone = [
                str(v.get("kind"))
                for v in rows or []
                if isinstance(v, dict) and str(v.get("kind", "")).startswith(GONE_KINDS)
            ]
            if gone:
                hits["/api/verbs"] = gone[:8]
            feats = p.api(pg, "/api/features").get("features") or []
            look(
                "/api/features",
                "\n".join(f"{f.get('id')} {f.get('title')}" for f in feats if isinstance(f, dict)),
            )
        ctx.close()
    look("kranto --help", _kranto("--help", timeout=60).stdout)
    look("kranto status", _kranto("status", timeout=120).stdout)
    py = os.path.join(ROOT_PREVIEW, "venv", "bin", "python")
    mcp = subprocess.run(
        [
            py,
            "-I",
            "-c",
            "import json, sys; from kranto.page.mcp import tools as T; "
            "c = T.http_client(sys.argv[1]); print(json.dumps([[t['name'], t['description']] "
            "for t in T.tools(c)]))",
            p.base,
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    try:
        listed = json.loads(mcp.stdout)
        look("MCP tools", "\n".join(f"{n}: {' '.join(str(d).split())}" for n, d in listed))
        said_mcp = f"{len(listed)} MCP tools"
    except ValueError:
        said_mcp = "MCP tools not listed: " + (mcp.stderr or mcp.stdout).strip()[-120:]
        hits["MCP tools"] = [said_mcp]
    return [
        ok(
            "ARCH-3",
            "no page, tool or status line mentions a broker, Invest, the radar or a "
            "browser extension (Settings' pages and Prompts, ? keys, ⌘K, the status bar, "
            "kranto status, kranto --help, the verbs, the features, the MCP tools)",
            not hits,
            f"{said_mcp}; " + ("clean" if not hits else f"{len(hits)} places with a word"),
            hits=hits,
        )
    ]


# -- CUT: the lab and the factory leave (CUT; the rewording of line 2) ----------

KRANTO = os.path.join(ROOT, "venv", "bin", "kranto")
CUT_PAGES = ["#/home", "#/news", "#/ideas", "#/watch", "#/post", "#/settings"]
# the page server's factory routes: 404 since C2 (the page reads the server for everything else)
CUT_GONE = [
    "/brb/api/kranto",
    "/brb/api/loop",
    "/brb/api/builds",
    "/brb/api/projects",
    "/brb/api/maintain/summary",
    "/brb/api/actions",
]
# what the cut must never write: the loop's ledger, the traces' index of builds, the
# task folders and the factory's folders under the loop home
CUT_KEEP = [
    "loop/loop.db",
    "loop/trace.db",
    "home/loop/loop.db",
    "home/loop/trace.db",
    "tasks",
    "loop/projects",
    "loop/maintain",
    "loop/publish",
    "loop/chat",
    "home/loop/projects",
    "home/loop/maintain",
    "home/loop/publish",
    "home/loop/chat",
]
DOCTOR_BUILDS = re.compile(r"builds: this feature is not part of Kranto any more", re.I)
# doctor's own console check, by its name ("ok    console        ready: …"); never another line
# that mentions a console (X's "the Developer Console is the bill")
DOCTOR_CONSOLE = re.compile(r"^\s*ok\s+console\s+ready\b")


def _doctor() -> tuple[int, str]:
    """``kranto doctor`` on the preview's home (it reads; it writes nothing), about the preview's
    own unit (named after its command), never another Kranto's service on this machine."""
    unit = os.path.basename(PREVIEW) + ".service"
    got = subprocess.run(
        [KRANTO, "--home", os.path.join(ROOT, "home"), "doctor"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env={**os.environ, "KRANTO_UNIT": unit, "KRANTO_TOKENS_DIR": os.path.join(ROOT, "tokens")},
    )
    return got.returncode, got.stdout + got.stderr


def _tree_hash(path: str) -> str | None:
    """A file's sha256, or a folder's (every file's relative path and sha256); None if absent."""
    import hashlib

    if not os.path.exists(path):
        return None
    h = hashlib.sha256()
    files = (
        [path]
        if os.path.isfile(path)
        else sorted(os.path.join(d, f) for d, _, fs in os.walk(path) for f in fs)
    )
    for f in files:
        h.update(os.path.relpath(f, path).encode())
        try:
            with open(f, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
        except OSError:
            h.update(b"<unreadable>")
    return h.hexdigest()


def cut_lines(p: Preview, baseline: str | None) -> list[Result]:
    out = []
    # the pages work as before the cut; the factory's routes are gone
    bad: dict[str, str] = {}
    errors_before = len(p.errors)
    for layout in (NEW, PHONE):
        ctx, pg = p.page(layout)
        for route in CUT_PAGES:
            p.go(pg, route, 1500)
            t = _text(pg, "#app")
            if "There is no page" in t or "Could not read" in t or len(t.strip()) < 40:
                bad[f"{layout[0]} {route}"] = t.replace("\n", " ")[:120]
        ctx.close()
    new_errors = p.errors[errors_before:]
    ctx, pg = p.page(NEW)
    gone = {r: p.api(pg, r).get("_status") for r in CUT_GONE}
    kept = {
        r: p.api(pg, r).get("_status", 200)
        for r in (
            "/brb/api/activity",
            "/brb/api/term/console",
            "/brb/api/header",
            "/api/home",
            "/api/ideas",
            "/api/post",
        )
    }
    ctx.close()
    out.append(
        ok(
            "CUT-1",
            "the preview updates across the cut: the home, News, Ideas, Watch, "
            "Post and Settings work as before it, in New and on the phone",
            not bad and not new_errors and all(v == 200 for v in kept.values()),
            f"{len(CUT_PAGES)} pages × 2 layouts"
            + (f"; {bad}" if bad else "")
            + (f"; page errors {new_errors[:3]}" if new_errors else ""),
            reads=kept,
        )
    )
    out.append(
        ok(
            " routes",
            "the page's factory routes answer 404 (builds, the loop, "
            "projects, maintenance, the registry's actions)",
            all(v == 404 for v in gone.values()),
            json.dumps(gone),
        )
    )
    # the old prepared items (each "File a Kranto issue") read "no longer available",
    # with Dismiss only
    ctx, pg = p.page(NEW)
    rows = p.api(pg, "/api/prepared").get("prepared") or []
    gone = [r for r in rows if isinstance(r, dict) and r.get("available") is False]
    good = [
        r
        for r in gone
        if "no longer available" in str(r.get("title") or "") and r.get("button") == "Dismiss"
    ]
    p.go(pg, "#/needs")
    needs = _text(pg, "#app")
    ctx.close()
    if gone:
        out.append(
            ok(
                "CUT-4",
                'my old prepared items (each "File a Kranto issue") show as no '
                "longer available, with Dismiss",
                len(good) == len(gone) and "no longer available" in needs,
                f"{len(good)} of {len(gone)} no longer available with Dismiss; Needs you "
                + ("says so" if "no longer available" in needs else "does not say so"),
                titles=[r.get("title") for r in gone][:8],
            )
        )
    else:
        out.append(
            skip(
                "CUT-4",
                "my old prepared items show as no longer available, with Dismiss",
                f"no prepared item of a verb that left on this copy ({len(rows)} open)",
            )
        )
    # doctor says the console is ready; the answer itself is the owner's
    code, said = _doctor()
    line = next((ln.strip() for ln in said.splitlines() if DOCTOR_CONSOLE.search(ln)), "")
    out.append(
        ok(
            "CUT-2",
            "`kranto doctor` says the console is ready",
            bool(line),
            line or said.strip().splitlines()[-1:][0] if said.strip() else "no output",
        )
    )
    out.append(
        skip(
            " answer",
            'the console answers "what is new in Robotics?"',
            "Claude Code's trust prompt on the preview is the owner's (CUT's report has "
            "the answer from a scratch install)",
        )
    )
    # a settings file with builds.enabled: true starts, and doctor says one line
    builds_lines = [ln.strip() for ln in said.splitlines() if DOCTOR_BUILDS.search(ln)]
    cfg = os.path.join(ROOT, "home", "kranto.yaml")
    try:
        with open(cfg, encoding="utf-8") as fh:
            has_builds = bool(
                re.search(r"(?m)^builds:\s*\n(\s+.*\n)*?\s+enabled:\s*true", fh.read())
            )
    except OSError:
        has_builds = False
    if has_builds:
        out.append(
            ok(
                "CUT-5",
                "a settings file with builds.enabled: true starts, and doctor says one line",
                len(builds_lines) == 1,
                "; ".join(builds_lines) or "no line",
            )
        )
    else:
        out.append(
            skip(
                "CUT-5",
                "a settings file with builds.enabled: true starts, and doctor says one line",
                "the copy's settings have no builds.enabled: true "
                "(tests/test_config_retired.py plays it)",
            )
        )
    # loop.db, trace.db and the loop's folders byte-identical after a day of jobs
    now = {k: _tree_hash(os.path.join(ROOT, k)) for k in CUT_KEEP}
    now = {k: v for k, v in now.items() if v is not None}
    if baseline and os.path.exists(baseline):
        with open(baseline, encoding="utf-8") as fh:
            before = json.load(fh)
        changed = sorted(k for k in before.get("hashes", {}) if before["hashes"][k] != now.get(k))
        hours = (time.time() - float(before.get("at", time.time()))) / 3600
        out.append(
            ok(
                "CUT-3",
                "loop.db, trace.db and the loop's folders are byte-identical "
                "before and after a day of the preview's jobs",
                not changed,
                f"{len(now)} paths, {hours:.1f} h apart"
                + (f"; changed: {changed}" if changed else ""),
                changed=changed,
            )
        )
    else:
        if baseline:
            with open(baseline, "w", encoding="utf-8") as fh:
                json.dump({"at": time.time(), "hashes": now}, fh, indent=1)
        out.append(
            skip(
                "CUT-3",
                "loop.db, trace.db and the loop's folders byte-identical after a day",
                f"baseline of {len(now)} paths written to {baseline}; run again after a day"
                if baseline
                else "run with --cut-baseline FILE, twice",
            )
        )
    return out


# FRONT (F1) -- the first run. Played on the fresh home (the server's page, no
# model key, nothing pressed); a line that needs a model, a press or a timed walk is played on
# the own scratch install and is SKIP here with that reason.

FRONT_WORDS = re.compile(r"\b(proposed nothing|Scout sources|Scouting|Degraded|Model key)\b")


def _in_view(pg: Any, sel: str) -> bool:
    return bool(
        pg.evaluate(
            "(s) => { const e = document.querySelector(s); if (!e) return false;"
            " const r = e.getBoundingClientRect();"
            " return r.bottom <= innerHeight && r.top >= 0; }",
            sel,
        )
    )


def front_first_box(p: Preview) -> Result:
    """step 1's ways in; the Claude Code login is one press with its terms in view."""
    ctx, pg = p.page(NEW)
    found = p.api(pg, "/api/setup/provider").get("claude_code") or {}
    p.go(pg, "#/welcome")
    boxes = pg.evaluate(
        "() => [...document.querySelectorAll('.box.way h2')].map((h) => h.innerText)"
    )
    prim = pg.evaluate(
        "() => [...document.querySelectorAll('.btn.primary')].map((b) => b.id || b.innerText)"
    )
    login = pg.query_selector("#way-login #key-save")
    ctx.close()
    first = (boxes or [""])[0]
    # F-3 not answered: the login stays last; the change is welcome.svelte.ts's WAYS
    good = (
        len(prim) == 1
        and "A model key" in boxes
        and "Your Claude Code login" in boxes
        and (not found.get("offered") or login is not None)
    )
    return ok(
        "FRONT-1",
        "Welcome's step 1 offers the ways in as boxes, one primary; the Claude "
        "Code login is one press (first once the owner says F-3)",
        good,
        f"boxes {boxes}; first {first!r}; primary {prim}; login offered "
        f"{bool(found.get('offered'))}",
        press="the login's press: the scratch walk",
    )


def front_ready(p: Preview) -> list[Result]:
    """Ready is at most 131 words and Start reading is inside the first screen."""
    out = []
    for layout in (NEW, PHONE):
        ctx, pg = p.page(layout)
        p.go(pg, "#/welcome/finish")
        c = pg.evaluate(COUNT, ".narrow:has(.ready-lines)")
        seen = _in_view(pg, "#finish")
        ctx.close()
        out.append(
            ok(
                f" {layout[0]}",
                "Ready is at most 131 words, Start reading inside the first screen",
                c["words"] <= 131 and seen,
                f"{_counted(c)}; Start reading {'in view' if seen else 'below the fold'}",
                count=c,
            )
        )
    return out


def front_status(p: Preview) -> Result:
    """(the part a fresh home shows): the bar never says Degraded before a read ends,
    and /api/home carries the first hour's block."""
    ctx, pg = p.page(NEW)
    hw = (p.api(pg, "/api/today").get("ingest") or {}).get("health") or {}
    home = p.api(pg, "/api/home")
    ctx.close()
    return ok(
        " (fresh)",
        "the status bar never says Degraded on a new home; the home carries the first hour",
        hw.get("word") != "Degraded" and "first" in home,
        f"bar {hw.get('word')!r}; first {'present' if home.get('first') else 'none yet'}",
        during_read="the scratch walk",
    )


def front_console(p: Preview) -> Result:
    """nothing starts Claude Code before setup is done (no console/open posted)."""
    before = len(p.aborted)
    ctx, pg = p.page(NEW, console="open")
    for route in ("#/hello", "#/welcome", "#/welcome/topics", "#/welcome/finish"):
        p.go(pg, route, 4000)
    ctx.close()
    opened = [a for a in p.aborted[before:] if "/term/console/open" in a]
    return ok(
        "FRONT-7",
        "on a fresh home nothing starts Claude Code before setup is done",
        not opened,
        f"{len(opened)} console/open posted from the first page and Welcome "
        "(this browser kept the console open)",
    )


def front_voice(p: Preview) -> Result:
    """(the screen's words): How you write, one screen, skippable to the home."""
    ctx, pg = p.page(NEW)
    p.go(pg, "#/welcome/voice")
    c = pg.evaluate(COUNT, "#how-you-write")
    skip_el = pg.query_selector("#voice-skip")
    to = skip_el.get_attribute("href") if skip_el else None
    ctx.close()
    return ok(
        "FRONT-18",
        "after Start reading I am asked how I write, on one screen; Skip for now takes me home",
        to == "#/home" and c["words"] <= 150 and c["primaries"] == 1 and c["controls"] <= 10,
        f"{_counted(c)}; Skip for now → {to}",
        count=c,
        timing="nothing about the first brief waits for it: the scratch walk",
    )


def front_words(p: Preview) -> Result:
    found: dict[str, list[str]] = {}
    for layout in (NEW, PHONE):
        ctx, pg = p.page(layout)
        for route in (
            "#/hello",
            "#/welcome",
            "#/welcome/topics",
            "#/welcome/finish",
            "#/welcome/voice",
            "#/home",
            "#/news",
            "#/ideas",
            "#/post",
            "#/needs",
        ):
            p.go(pg, route, 1500)
            hits = [
                ln.strip()[:120] for ln in _text(pg, "#app").split("\n") if FRONT_WORDS.search(ln)
            ]
            if hits:
                found[f"{layout[0]} {route}"] = hits[:4]
        ctx.close()
    return ok(
        "FRONT words (F1)",
        "Welcome and the empty pages never say the old words (Model key, "
        "Scout sources, proposed nothing, Degraded)",
        not found,
        "none" if not found else f"{len(found)} pages",
        hits=found,
    )


def front_fresh(p: Preview) -> list[Result]:
    return [
        front_first_box(p),
        *front_ready(p),
        front_status(p),
        front_console(p),
        front_voice(p),
        front_words(p),
    ]


def front_lines(p: Preview | None = None) -> list[Result]:
    """The F1 lines a read-only walk cannot play; each with where it is played."""
    return [
        skip(
            "FRONT-2",
            'while the scout runs, step 2 says what it is doing and never "proposed nothing"',
            "a model call; addtopic.svelte.test.ts and the scratch walk",
        ),
        skip(
            "FRONT-4",
            "with the first suggestion and the Claude Code login, the first brief is "
            "on News within 8 minutes of the first page",
            "timed on the scratch install",
        ),
        skip(
            "FRONT-5",
            "Write a post on the brief's first story makes a draft within a minute",
            "a model call; tests/test_prose_writers.py and the scratch walk",
        ),
        skip("FRONT-17", "the sample day on the fresh home", "F-1 not answered"),
    ]


# -- the word test and the counts -----------------------------------------------------------

WORD_PAGES = [
    "#/home",
    "#/news",
    "#/ideas",
    "#/watch",
    "#/watch/map",
    "#/post",
    "#/settings",
    "#/settings/watching",
    "#/settings/posting",
    "#/settings/assistant",
    "#/settings/spend",
    "#/settings/privacy",
    "#/settings/system",
    "#/settings/appearance",
]
FRESH_PAGES = ["#/hello", "#/welcome", "#/welcome/topics", "#/welcome/finish", *WORD_PAGES]


def word_test(p: Preview, pages: list[str], tag: str) -> Result:
    found: dict[str, list[str]] = {}
    for layout in (NEW, PHONE):
        ctx, pg = p.page(layout)
        for route in pages:
            p.go(pg, route, 1500)
            lines = [ln.strip()[:140] for ln in _text(pg, "#app").split("\n") if WORDS.search(ln)]
            if lines:
                found[f"{layout[0]} {route}"] = lines[:6]
        ctx.close()
    said = f"{len(pages)} pages, New and phone"
    if found:
        said += f": {len(found)} with a word"
    return ok(
        f"WORDS {tag}",
        'the word test (with "cub"): no word of builds, cubs or the broker',
        not found,
        said,
        hits=found,
    )


def counts(p: Preview) -> list[Result]:
    out = []
    ctx, pg = p.page(NEW)
    p.go(pg, "#/home")
    c = pg.evaluate(COUNT, _root(pg))
    out.append(
        ok(
            "COUNT home",
            "the home: 215 words or fewer, one primary",
            c["words"] <= 215 and c["primaries"] <= 1,
            _counted(c),
            count=c,
        )
    )
    p.go(pg, "#/post")
    c = pg.evaluate(COUNT, _root(pg))
    out.append(
        ok(
            "COUNT post",
            "Post: 173 words or fewer, two primaries at most",
            c["words"] <= 173 and c["primaries"] <= 2,
            _counted(c),
            count=c,
        )
    )
    ideas = p.api(pg, "/api/ideas?embedding=ref").get("ideas") or []
    card = next((i for i in ideas if i.get("state") == "waiting"), None)
    if card:
        p.go(pg, f"#/ideas/{card['id']}")
        sheet = pg.evaluate(COUNT, "#detail")
        btn = pg.query_selector("#idea-write")
        q = {"words": 0, "controls": 0, "primaries": 0}
        if btn:
            btn.click()
            pg.wait_for_timeout(800)
            q = pg.evaluate(COUNT, "#dlg")
        both = {k: sheet[k] + q[k] for k in ("words", "controls", "primaries")}
        # the D4 was 180 words and 12 controls; the question then gained PROSE's "What do you
        # think?" (P-1: a field) and, while no voice is set, the "Set up how you write ›"
        # (a link): 190 and 14; then the angle step (SOCIAL, PROSE's rule 4): three proposed
        # sentences, each a button you can read before choosing, and Skip: 220 and 18
        out.append(
            ok(
                "COUNT card (fix 10, D4)",
                "a card's sheet with Write a post's question: 220 words, 18 controls, 2 primaries",
                both["words"] <= 220 and both["controls"] <= 18 and both["primaries"] <= 2,
                f"card #{card['id']}: {_counted(both)}",
                sheet=sheet,
                question=q,
            )
        )
    ctx.close()
    bad = {}
    for layout in (NEW, PHONE):
        ctx, pg = p.page(layout)
        for k in (
            "",
            "/watching",
            "/posting",
            "/assistant",
            "/spend",
            "/privacy",
            "/system",
            "/appearance",
        ):
            p.go(pg, "#/settings" + k, 1500)
            c = pg.evaluate(COUNT, _root(pg))
            if c["primaries"] > 1 or (layout[1] < 600 and c["offscreen"]):
                bad[f"{layout[0]} settings{k}"] = c
        ctx.close()
    out.append(
        ok(
            "COUNT settings (fix 9)",
            "Settings' seven pages: one primary at most; on a phone nothing off the screen",
            not bad,
            "every page within" if not bad else json.dumps(bad)[:300],
        )
    )
    return out


# FRONT (F2): News and the draft (to 16, 19, 20 and WORDS) --------------
# On the preview's copy every non-GET is aborted: a press is counted as aborted, never made. The
# presses themselves (Save, Fix them) are tests (the server tests/test_post_edit.py, the page
# post.svelte.test.ts).

PLAIN = re.compile(
    r"Kranto on\b|\b\d{4}-\d{2}-\d{2}\b|\b(?:obs|exa) \d+|observation \d+ ›|"
    r"Deep dive now|Article · \d|this brief ›|About this brief|"
    r"Could not read the server|thing wait on|needs_confirm|readback|draft\.sanity|"
    r"9999-12-31|HN search:|Exa, free mode"
)
F2_PAGES = ["#/news", "#/news/earlier", "#/post", "#/settings/posting/voice", "#/needs"]


def _latest_brief(p: Preview, pg: Any) -> dict[str, Any] | None:
    for t in p.api(pg, "/api/f/news/latest").get("topics") or []:
        b = t.get("brief")
        if b and b.get("status") == "ok":
            return b
    return None


def front_8(p: Preview) -> list[Result]:
    """News on the copy: one line a story, the first open with Why it matters; within 220 words
    and 16 controls (New and phone); no "Kranto on", ISO date, "obs " or "exa "."""
    out = []
    for layout in (NEW, PHONE):
        ctx, pg = p.page(layout)
        p.go(pg, "#/news")
        c = pg.evaluate(COUNT, ".news-today")
        rows = pg.evaluate("() => document.querySelectorAll('li.story').length")
        opened = _text(pg, "li.story.open") if pg.query_selector("li.story.open") else ""
        text = _text(pg, ".news-today") if pg.query_selector(".news-today") else ""
        bad = [m.group(0) for m in PLAIN.finditer(text)][:4]
        good = (
            rows > 0
            and "Why it matters" in opened
            and c["words"] <= 220
            and c["controls"] <= 16
            and not bad
        )
        out.append(
            ok(
                f" {layout[0]}",
                "News: one line a story, the first open with Why it "
                "matters; at most 220 words and 16 controls; no Kranto on, ISO date, obs or "
                "exa",
                good,
                f"{rows} stories, {_counted(c)}" + (f"; found {bad}" if bad else ""),
                count=c,
            )
        )
        ctx.close()
    return out


def front_9(p: Preview) -> Result:
    """I open the third story in place: what happened, why it matters, its outlets, three plain
    buttons; Write a post opens the question."""
    ctx, pg = p.page(NEW)
    p.go(pg, "#/news")
    rows = pg.query_selector_all("li.story:not(.open) .story-row")
    if len(rows) < 2:
        ctx.close()
        return skip("FRONT-9", "the third story opens in place", f"{len(rows) + 1} stories today")
    rows[1].click()
    pg.wait_for_timeout(500)
    o = pg.query_selector("li.story.open")
    verbs = [b.inner_text().strip() for b in o.query_selector_all(".st-verbs .btn")] if o else []
    prim = len(o.query_selector_all(".btn.primary")) if o else 1
    asked = False
    w = next(
        (
            b
            for b in (o.query_selector_all(".st-verbs .btn") if o else [])
            if b.inner_text().strip() == "Write a post"
        ),
        None,
    )
    if w:
        w.click()
        pg.wait_for_timeout(600)
        asked = bool(pg.query_selector("#write-post-facts"))
    key = o.get_attribute("data-story") if o else None
    good = (
        bool(key)
        and bool(o.query_selector(".why"))
        and bool(o.query_selector(".st-src"))
        and prim == 0
        and "Write a post" in verbs
        and asked
    )
    said = f"{key or '-'}: {verbs}; question {'opened' if asked else 'missing'}"
    ctx.close()
    return ok(
        "FRONT-9",
        "the third story opens in place: what happened, why it matters, outlets, "
        "plain buttons; Write a post opens the question",
        good,
        said,
    )


def front_10(p: Preview) -> list[Result]:
    """A story's page has its summary, Why it matters and its sources; #/news/a/<id> lands on its
    story; Idea from this is offered or the page says why; nothing leads to "There is no page"."""
    ctx, pg = p.page(NEW)
    arts = p.api(pg, "/api/f/news/articles.list?limit=5").get("articles") or []
    b = _latest_brief(p, pg)
    out = []
    if arts:
        a = arts[0]
        p.go(pg, f"#/news/a/{a['id']}")
        landed = pg.evaluate("() => location.hash")
        want = f"#/news/i/{a['brief_id']}/{a['item_n']}"
        out.append(
            ok(" land", f"#/news/a/{a['id']} lands on {want}", landed.startswith(want), landed)
        )
    else:
        out.append(skip(" land", "#/news/a/<id> lands on its story", "no article on the copy"))
    if b:
        p.go(pg, f"#/news/i/{b['id']}/0")
        text = _text(pg, "#app")
        why = bool(pg.query_selector("#story-why"))
        idea = bool(pg.query_selector("#story-idea-from, #story-idea, #story-no-idea"))
        srcs = bool(pg.query_selector("#s-evidence .news-sources li"))
        c = pg.evaluate(COUNT, "#app")
        good = why and idea and srcs and "There is no page" not in text and c["primaries"] <= 1
        out.append(
            ok(
                "FRONT-10",
                "a story's page: summary, Why it matters, sources; Idea from "
                "this or why not; no 'There is no page'",
                good,
                f"brief {b['id']} story 1: why {why}, idea line {idea}, sources {srcs}; "
                f"{_counted(c)}",
                count=c,
            )
        )
    else:
        out.append(skip("FRONT-10", "a story's page", "no brief on the copy"))
    ctx.close()
    return out


def front_11(p: Preview) -> list[Result]:
    out = []
    for layout in (NEW, PHONE):
        ctx, pg = p.page(layout)
        p.go(pg, "#/news/earlier")
        c = pg.evaluate(COUNT, _root(pg))
        rows = pg.evaluate("() => document.querySelectorAll('li.row').length")
        out.append(
            ok(
                f" {layout[0]}",
                "Earlier is one row a day, at most 220 words",
                rows > 0 and c["words"] <= 220,
                f"{rows} rows, {_counted(c)}",
                count=c,
            )
        )
        ctx.close()
    return out


def front_12(p: Preview) -> Result:
    """How many of the copy's stories show an idea by the rules (printed)."""
    ctx, pg = p.page(NEW)
    briefs = p.api(pg, "/api/f/news/briefs.list?limit=50").get("briefs") or []
    stories = with_idea = with_theme = 0
    by_rule: dict[int, int] = {}
    for b in briefs:
        if b.get("status") != "ok":
            continue
        got = p.api(pg, f"/api/f/news/brief?id={b['id']}").get("stories") or {}
        for s in got.values():
            stories += 1
            if s.get("idea"):
                with_idea += 1
                by_rule[s["idea"]["rule"]] = by_rule.get(s["idea"]["rule"], 0) + 1
            elif s.get("theme"):
                with_theme += 1
    ctx.close()
    return Result(
        "FRONT-12",
        "how many of the copy's stories show an idea (counted, never failed)",
        "info",
        f"{with_idea} of {stories} stories show an idea (by rule {by_rule}); "
        f"{with_theme} more offer Idea from this",
        {"briefs": len(briefs)},
    )


def front_13(p: Preview) -> Result:
    """On the newsletter draft, Edit opens the draft's own words; its sources read as outlets;
    Save is a press (aborted here; the press is a test)."""
    ctx, pg = p.page(NEW)
    drafts = p.api(pg, "/api/post").get("drafts") or []
    d = next((x for x in drafts if x.get("kind") == "newsletter"), None) or (
        drafts[0] if drafts else None
    )
    if d is None:
        ctx.close()
        return skip("FRONT-13", "Edit opens the draft's own words", "no draft waits")
    sheet = p.api(pg, f"/api/post/d/{d['id']}")
    p.go(pg, f"#/post/d/{d['id']}")
    btn = pg.query_selector("#draft-edit")
    box = ""
    if btn:
        btn.click()
        pg.wait_for_timeout(500)
        el = pg.query_selector("#draft-edit-body, #draft-edit-part-0")
        box = el.input_value() if el else ""
    own = (sheet.get("edit") or {}).get("body") or "".join(
        x.get("text", "") for x in (sheet.get("edit") or {}).get("parts") or []
    )
    labels = re.findall(r"\[(?:obs|exa) \d+\]", box + sheet.get("markdown", ""))
    save = pg.query_selector("#draft-save")
    good = bool(btn) and bool(box) and box == own and not labels and bool(save)
    ctx.close()
    return ok(
        "FRONT-13",
        "on the newsletter draft Edit opens its own words; sources read as "
        "outlets, never obs N; Save is a press",
        good,
        f"draft #{d['id']} ({d.get('kind')}): editor {'opened' if box else 'not opened'}, "
        f"{len(box)} characters; labels left {labels[:3]}",
    )


def front_14(p: Preview) -> Result:
    """With a card's sheet open, the line about a press is drawn in the sheet, not half under it
    (measured after an aborted press)."""
    ctx, pg = p.page(NEW)
    ideas = p.api(pg, "/api/ideas?embedding=ref").get("ideas") or []
    card = next((i for i in ideas if i.get("state") == "waiting"), None)
    if card is None:
        ctx.close()
        return skip("FRONT-14", "the press's line is not half under a sheet", "no card waits")
    p.go(pg, f"#/ideas?sel=i{card['id']}")
    later = pg.query_selector("#detail button:has-text('Later')")
    if later:
        later.click()
        pg.wait_for_timeout(1200)
    boxes = pg.evaluate("""() => {
      const r = (s) => { const e = document.querySelector(s);
        if (!e || !e.getClientRects().length) return null;
        const b = e.getBoundingClientRect();
        return {l: b.left, r: b.right, t: b.top, b: b.bottom}; };
      return { line: r('#sheet-flash') || r('#list-h .flash'), sheet: r('#detail') };
    }""")
    ln, sh = boxes.get("line"), boxes.get("sheet")
    crossing = bool(ln and sh) and not (
        ln["r"] <= sh["l"] or ln["l"] >= sh["r"] or ln["b"] <= sh["t"] or ln["t"] >= sh["b"]
    )
    held = bool(ln and sh) and ln["l"] >= sh["l"] - 1 and ln["r"] <= sh["r"] + 1
    good = bool(later) and (not ln or not crossing or held)
    ctx.close()
    return ok(
        "FRONT-14",
        "with a card's sheet open, the press's line is not half under the sheet",
        good,
        f"Later {'pressed (aborted)' if later else 'not found'}; line {ln}; sheet {sh}",
    )


def front_15(p: Preview) -> Result:
    ctx, pg = p.page(NEW)
    p.go(pg, "#/watch/sources?sel=s999999", 4000)
    # the page's own words, not the top bar (whose wordmark is the name in lowercase): no
    # internal name of the server leaks into what the page says
    text = _text(pg, "#app")
    if pg.query_selector("#top"):
        text = text.replace(_text(pg, "#top"), "", 1)
    good = (
        "This source is not here any more" in text
        and "kranto" not in text
        and "Tell us" not in text
    )
    ctx.close()
    return ok(
        "FRONT-15",
        "#/watch/sources?sel=s999999 says 'This source is not here any more', "
        "no the server, no Tell us",
        good,
        "said so" if good else text[text.find("Could") :][:120] or "no words",
    )


def front_16(p: Preview, fresh: bool = False) -> Result:
    ctx, pg = p.page(NEW)
    p.go(pg, "#/needs")
    # Needs you's head is its first line, "4 things wait for you" (the page has no .ph)
    head = pg.evaluate(
        "() => { const m = document.querySelector('main') || document.body; "
        "const x = (m.innerText.match(/\\d+ things? waits? for you/) || [''])[0]; "
        "return x; }"
    )
    chip = pg.query_selector("#hd-needs")
    chip_text = chip.inner_text().strip() if chip else ""
    n = re.search(r"(\d+) things? waits?", head)
    ctx.close()
    if fresh:
        return ok(
            " fresh", "the top bar says nothing on the fresh home", not chip, chip_text or "no chip"
        )
    good = bool(n) and chip_text == f"Needs you {n.group(1)}" if n else not chip
    return ok(
        "FRONT-16",
        "the top bar says 'Needs you N', the same N as Needs you's head",
        good,
        f"chip {chip_text!r}; head {head!r}",
    )


def front_19(p: Preview) -> Result:
    """On a draft, what reads like AI is underlined with its fix and one line says how many
    (the check is a POST, aborted on the copy: the page's own check is a test; here Kranto's
    checker reads the recorded draft, as does)."""
    ctx, pg = p.page(NEW)
    drafts = p.api(pg, "/api/post").get("drafts") or []
    ctx.close()
    if not drafts:
        return skip("FRONT-19", "a draft's flags", "no draft waits")
    ctx, pg = p.page(NEW)
    sheet = p.api(pg, f"/api/post/d/{drafts[0]['id']}")
    ctx.close()
    words = (sheet.get("edit") or {}).get("body") or sheet.get("markdown", "")
    got = _prose_check(words, "newsletter" if sheet.get("kind") == "newsletter" else "blog")
    if got is None:
        return skip(
            "FRONT-19",
            "a draft's flags",
            "Kranto is not importable here, nor the preview's install",
        )
    spans = [f for f in got["flags"] if f.get("scope") != "text"]
    good = "verdict" in got and all(f.get("fix") for f in got["flags"])
    return ok(
        "FRONT-19",
        "a recorded draft shows its flags: each with its plain fix, one line "
        "says how many (Fix them is a test)",
        good,
        f"{got['verdict']} ({len(spans)} underlined, score {got['score']})",
    )


def front_20(p: Preview, tag: str = "") -> list[Result]:
    out = []
    for layout in (NEW, PHONE):
        ctx, pg = p.page(layout)
        p.go(pg, "#/settings/posting/voice")
        # the page itself (its title, sections and the folded Advanced), not the top bar, the
        # Settings list beside it or the console
        root = "article.page-read" if pg.query_selector("article.page-read") else "#app"
        c = pg.evaluate(COUNT, root)
        # its one primary (Save) is drawn in the shell's page head, outside the article
        c["primaries"] = pg.evaluate(COUNT, "#app")["primaries"]
        card = bool(pg.query_selector("#voice-card"))
        switches = pg.evaluate("() => document.querySelectorAll('#voice-switches select').length")
        folded = pg.evaluate(
            "() => { const d = document.querySelector('#voice-advanced'); return !!d && !d.open; }"
        )
        good = (
            card
            and switches == 4
            and folded
            and c["primaries"] == 1
            and (layout[1] >= 600 or not c["offscreen"])
        )
        out.append(
            ok(
                f"FRONT-20{tag} {layout[0]}",
                "Settings › Posting › How you write: my voice "
                "card, samples, the switches; one primary; the advanced parts folded",
                good,
                f"card {card}, {switches} switches, folded {folded}; {_counted(c)}",
                count=c,
            )
        )
        ctx.close()
    return out


def front_f2_words(p: Preview, tag: str) -> Result:
    found: dict[str, list[str]] = {}
    for layout in (NEW, PHONE):
        ctx, pg = p.page(layout)
        for route in F2_PAGES:
            p.go(pg, route, 1500)
            lines = [ln.strip()[:140] for ln in _text(pg, "#app").split("\n") if PLAIN.search(ln)]
            if lines:
                found[f"{layout[0]} {route}"] = lines[:4]
        ctx.close()
    return ok(
        f"WORDS front {tag}",
        "the left column on none of F2's pages",
        not found,
        f"{len(F2_PAGES)} pages, New and phone" + (f": {len(found)} with a word" if found else ""),
        hits=found,
    )


def front_f2_lines(p: Preview) -> list[Result]:
    out = (
        front_8(p)
        + [front_9(p)]
        + front_10(p)
        + front_11(p)
        + [front_12(p), front_13(p), front_14(p), front_15(p), front_16(p), front_19(p)]
    )
    return out + front_20(p) + [front_f2_words(p, "copy")]


def front_f2_fresh(p: Preview) -> list[Result]:
    return [front_16(p, fresh=True), *front_20(p, " fresh"), front_f2_words(p, "fresh home")]


def link_from_preview(fresh: bool = False) -> str:
    args = ["fresh", "link"] if fresh else ["open"]
    path = os.path.expanduser("~/.local/bin") + ":/usr/local/bin:/usr/bin:/bin"
    got = subprocess.run(
        ["bash", PREVIEW, *args],
        capture_output=True,
        text=True,
        timeout=120,
        env=dict(os.environ, PATH=path),
        check=False,
    )
    m = re.search(r"http://127\.0\.0\.1:\d+/\S+", got.stdout)
    if not m:
        sys.exit("acceptance: no sign-in link: " + (got.stdout + got.stderr)[-300:])
    return m.group(0)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--link", help="a one-time sign-in link (else kranto-preview open makes one)")
    ap.add_argument(
        "--fresh-port",
        type=int,
        help="the fresh home's port (kranto-preview fresh): Welcome's words too",
    )
    ap.add_argument("--fresh-link")
    ap.add_argument("--topic", default="Padel", help="the new topic of HOUR's line 1 (D8)")
    ap.add_argument("--out", help="write the results as JSON here")
    ap.add_argument(
        "--arch-before", help="the retired tables' row counts before the cut, as JSON {table: rows}"
    )
    ap.add_argument("--only", help="run only these groups, comma-separated (e.g. arch)")
    ap.add_argument(
        "--cut-baseline",
        help="hashes of what the cut never writes; the first "
        "run writes the file, a run a day later compares",
    )
    a = ap.parse_args(argv)
    from playwright.sync_api import sync_playwright

    results: list[Result] = []
    with sync_playwright() as pw:
        p = Preview(pw, a.port, a.link or link_from_preview())
        only = set((a.only or "").split(",")) - {""}

        def want(group: str) -> bool:
            return not only or group in only

        try:
            if want("prev"):
                results += prev_lines(p)
            if want("hour"):
                results += hour_lines(p, a.topic)
            if want("post"):
                results += post_lines(p)
            if want("prose"):
                results += prose_lines(p)
            if want("shell"):
                results += shell_lines(p)
            if want("words"):
                # the copy holds the owner's own words (topics, cards, news: "build", "repo"),
                # so its scan is told, not failed; the failing word test is the fresh home's,
                # as ran it
                copy = word_test(p, WORD_PAGES, "copy")
                copy.state = "info"
                results.append(copy)
            if want("counts"):
                results += counts(p)
            if want("social"):
                results += social_lines(p)
            if want("tfix"):
                results += tfix_lines(p)
            if want("arch"):
                results += arch_lines(p, a.arch_before)
            if want("cut"):
                results += cut_lines(p, a.cut_baseline)
            if want("front"):
                results += front_lines(p)  # F1's lines
                results += front_f2_lines(p)  # F2's (to 16, 19, 20, WORDS)
        finally:
            aborted, errors = sorted(set(p.aborted)), sorted(set(p.errors))
            p.close()
        if a.fresh_port and (want("fresh") or want("front")):
            f = Preview(pw, a.fresh_port, a.fresh_link or link_from_preview(fresh=True))
            try:
                if want("fresh"):
                    results.append(word_test(f, FRESH_PAGES, "fresh home"))
                    results += tfix_fresh(f)
                if want("front"):
                    results += front_fresh(f)
                    results += front_f2_fresh(f)
            finally:
                f.close()
        elif want("fresh"):
            results.append(
                skip(
                    "WORDS fresh home",
                    'the word test (with "cub")',
                    "run with --fresh-port 8767 (kranto-preview fresh first)",
                )
            )
    width = max(len(r.line) for r in results)
    for r in results:
        print(f"{r.state.upper():4}  {r.line:{width}}  {r.said}")
    n = {s: sum(1 for r in results if r.state == s) for s in ("pass", "fail", "skip", "info")}
    print(
        f"\n{n['pass']} pass, {n['fail']} fail, {n['skip']} skip, {n['info']} info; "
        f"{len(aborted)} kinds of "
        f"request aborted (nothing was pressed); {len(errors)} page errors"
    )
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "port": a.port,
                    "results": [asdict(r) for r in results],
                    "aborted": aborted,
                    "page_errors": errors,
                },
                fh,
                indent=1,
                ensure_ascii=False,
            )
    return 1 if n["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
