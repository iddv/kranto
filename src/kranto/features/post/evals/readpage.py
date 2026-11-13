"""The owner's blind read, built from any set of drafts.

    python -m kranto.features.post.evals read --drafts DIR --out read.html --key key.md \\
        [--index index.json] [--seed 13] [--title "..."]

``DIR/<writer>/<name>.md`` is one writer's draft of one post (Kranto's export names them
``<item>.<site>[.<angle kind>]``; any names work). Every name that two or more writers wrote, or
one, becomes a post on the page: its drafts unlabeled, in a random order of their own, lettered
A, B, C…, each with the same choice (A / B / C / None) and a comment box. The page keeps the
answers in the browser (``localStorage``, if the browser allows it) and "Copy my answers" puts
them on the clipboard as plain lines (a box to copy by hand when the clipboard is refused).
Light and dark. ``key.md`` says which letter was which writer; nobody should open it before
reading. The index (the export's ``index.json``, found beside DIR or given) labels each post with
its item's title, its site and its angle.
"""

from __future__ import annotations

import html
import json
import random
import re
from pathlib import Path

CSS = """
:root { color-scheme: light dark; --bg:#fbfaf7; --fg:#1d1c1a; --mut:#6b665d; --card:#ffffff;
  --line:#e4e0d8; --acc:#2f5d50; }
@media (prefers-color-scheme: dark) { :root:not(.light) { --bg:#16171a; --fg:#e9e6df;
  --mut:#a29d93; --card:#1f2125; --line:#33363c; --acc:#8fc7b5; } }
:root.dark { --bg:#16171a; --fg:#e9e6df; --mut:#a29d93; --card:#1f2125; --line:#33363c;
  --acc:#8fc7b5; }
body { background:var(--bg); color:var(--fg); font:17px/1.6 Georgia, "Iowan Old Style", serif;
  margin:0; padding:2rem 1rem 5rem; }
main { max-width:1200px; margin:0 auto; }
h1 { font-size:1.6rem; margin:0 0 .3rem; } .lede { color:var(--mut); margin:0 0 2rem; }
.post { margin:0 0 3rem; } h2 { font-size:1.15rem; margin:0 0 .2rem; }
.src { color:var(--mut); margin:0 0 1rem; font-size:.9rem; }
.angle { margin:0 0 1rem; padding:.5rem .8rem; border-left:3px solid var(--acc); }
.drafts { display:grid; grid-template-columns:repeat(auto-fit, minmax(300px, 1fr)); gap:1.2rem; }
.v { background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:1rem 1.2rem; overflow-wrap:anywhere; }
.v h4 { margin:0 0 .6rem; color:var(--acc); font:600 .85rem/1 system-ui, sans-serif;
  letter-spacing:.04em; text-transform:uppercase; }
.v h3 { font-size:1.02rem; margin:1rem 0 .3rem; } .v p { margin:.5rem 0; }
.answer { margin-top:1rem; font:.95rem system-ui, sans-serif; display:flex; flex-wrap:wrap;
  gap:.4rem 1rem; align-items:center; }
.answer label { cursor:pointer; padding:.35rem .2rem; }
.answer input[type=radio] { width:1.1rem; height:1.1rem; vertical-align:-.15rem; }
textarea { width:100%; min-height:4.5rem; margin-top:.6rem; font:.95rem system-ui, sans-serif;
  background:var(--card); color:var(--fg); border:1px solid var(--line); border-radius:8px;
  padding:.5rem; box-sizing:border-box; }
.bar { position:sticky; top:0; z-index:2; display:flex; justify-content:flex-end; gap:.4rem;
  background:var(--bg); padding:.5rem 0; margin:-1.5rem 0 .5rem; }
button { font:.85rem system-ui; background:var(--card); color:var(--fg);
  border:1px solid var(--line); border-radius:6px; padding:.4rem .7rem; cursor:pointer; }
#copied { color:var(--acc); font:.85rem system-ui; align-self:center; }
#manual { display:none; margin:2rem 0; } #manual textarea { min-height:12rem; }
"""

JS = """
(function () {
  var KEY = %(key)s;
  function load() { try { return JSON.parse(localStorage.getItem(KEY) || "{}"); }
                    catch (e) { return {}; } }
  function save(s) { try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) {} }
  var state = load();
  document.querySelectorAll("section.post").forEach(function (sec) {
    var id = sec.dataset.post, got = state[id] || {};
    sec.querySelectorAll("input[type=radio]").forEach(function (r) {
      if (got.pick === r.value) { r.checked = true; }
      r.addEventListener("change", function () {
        state[id] = state[id] || {}; state[id].pick = r.value; save(state); });
    });
    var t = sec.querySelector("textarea");
    if (got.note) { t.value = got.note; }
    t.addEventListener("input", function () {
      state[id] = state[id] || {}; state[id].note = t.value; save(state); });
  });
  function answers() {
    var lines = [document.title];
    document.querySelectorAll("section.post").forEach(function (sec) {
      var r = sec.querySelector("input[type=radio]:checked");
      var t = sec.querySelector("textarea").value.replace(/\\s+/g, " ").trim();
      lines.push("Post " + sec.dataset.n + " (" + sec.dataset.post + "): " +
                 (r ? r.value : "(none picked)") + (t ? " | " + t : ""));
    });
    return lines.join("\\n");
  }
  function fallback(text) {
    var ta = document.createElement("textarea"); ta.value = text;
    ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select(); var ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    document.body.removeChild(ta); return ok;
  }
  function done(ok, text) {
    var said = document.getElementById("copied");
    if (ok) { said.textContent = "Copied"; setTimeout(function () { said.textContent = ""; },
                                                       2500); return; }
    var box = document.getElementById("manual"); box.style.display = "block";
    var ta = box.querySelector("textarea"); ta.value = text; ta.focus(); ta.select();
    said.textContent = "Copy it from the box below";
  }
  document.getElementById("copy").addEventListener("click", function () {
    var text = answers();
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(function () { done(true, text); },
                                               function () { done(fallback(text), text); });
    } else { done(fallback(text), text); }
  });
  document.getElementById("mode").addEventListener("click", function () {
    var r = document.documentElement;
    var d = r.classList.contains("dark") || (!r.classList.contains("light") &&
            matchMedia("(prefers-color-scheme: dark)").matches);
    r.classList.toggle("dark", !d); r.classList.toggle("light", d);
  });
})();
"""


def _inline(text: str) -> str:
    t = html.escape(text, quote=False)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
               lambda m: f'<a href="{html.escape(m.group(2))}" rel="noopener">{m.group(1)}</a>',
               t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<i>\1</i>", t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    return t


_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")


def markdown(text: str) -> str:
    """Enough markdown for a post: headings, paragraphs, lists, bold, italics, links."""
    out = []
    for block in re.split(r"\n\s*\n", (text or "").strip()):
        b = block.strip()
        if not b:
            continue
        m = re.match(r"(#{1,6})\s+(.*)", b)
        if m and "\n" not in b:
            out.append(f"<h3>{_inline(m.group(2))}</h3>")
            continue
        lines = [ln for ln in b.splitlines() if ln.strip()]
        if all(re.match(r"\s*(?:[-*+]\s|\d+[.)]\s)", ln) for ln in lines):
            tag = "ol" if re.match(r"\s*\d", lines[0]) else "ul"
            items = "".join("<li>" + _inline(_BULLET.sub("", ln)) + "</li>" for ln in lines)
            out.append(f"<{tag}>{items}</{tag}>")
            continue
        out.append("<p>" + "<br>".join(_inline(ln) for ln in lines) + "</p>")
    return "\n".join(out)


def _title_and_body(text: str) -> tuple[str | None, str]:
    m = re.match(r"\s*#\s+([^\n]+)\n+", text or "")
    return (m.group(1).strip(), text[m.end():]) if m else (None, text or "")


def collect(drafts: Path) -> dict[str, dict[str, str]]:
    """name -> writer -> the draft's text, from ``DIR/<writer>/<name>.md``."""
    out: dict[str, dict[str, str]] = {}
    for wdir in sorted(p for p in drafts.iterdir() if p.is_dir()):
        for f in sorted(wdir.glob("*.md")):
            text = f.read_text(encoding="utf-8").strip()
            if text:
                out.setdefault(f.stem, {})[wdir.name] = text
    return out


def _index(drafts: Path, index: Path | None) -> dict[str, dict]:
    for cand in [index, drafts / "index.json", drafts.parent / "export" / "index.json"]:
        if cand and cand.is_file():
            rows = json.loads(cand.read_text(encoding="utf-8")).get("prompts") or []
            return {r["name"]: r for r in rows if isinstance(r, dict) and r.get("name")}
    return {}


def build(drafts: Path, out: Path, key: Path, *, index: Path | None = None, seed: int = 13,
          title: str = "Posts by several writers: which would you post?") -> dict:
    """Write the page and the key; ``{posts, writers}``."""
    posts = collect(drafts)
    if not posts:
        raise SystemExit(f"no drafts under {drafts}: expected <writer>/<name>.md")
    idx = _index(drafts, index)
    rnd = random.Random(seed)
    writers = sorted({w for d in posts.values() for w in d})
    names = sorted(posts, key=lambda n: (list(idx).index(n) if n in idx else len(idx), n))
    sections, key_rows = [], []
    for n, name in enumerate(names, 1):
        order = sorted(posts[name])
        rnd.shuffle(order)
        letters = [chr(65 + i) for i in range(len(order))]
        meta = idx.get(name, {})
        site = meta.get("site") or ("toot" if ".toot" in name else "blog")
        kind = "Blog post" if site == "blog" else "Short post"
        head = html.escape(meta.get("title") or name)
        angle = meta.get("angle")
        cards = []
        for letter, w in zip(letters, order, strict=True):
            t, body = _title_and_body(posts[name][w])
            ttl = f"<h3>{_inline(t)}</h3>" if t else ""
            cards.append(f'<article class="v"><h4>Version {letter}</h4>{ttl}\n'
                         f"{markdown(body)}</article>")
        radios = "".join(
            f'<label><input type="radio" name="p{n}" value="{x}"> {x}</label>'
            for x in [*letters, "None"])
        what = html.escape(meta.get("angle_kind") or "the person's")
        angle_html = (f'<p class="angle">Written from this angle ({what}): '
                      f"{html.escape(angle)}</p>" if angle else "")
        sections.append(
            f'<section class="post" data-post="{html.escape(name)}" data-n="{n}">'
            f"<h2>{n}. {kind}: {head}</h2>"
            f'<p class="src">{html.escape(name)}</p>{angle_html}'
            f'<div class="drafts">{"".join(cards)}</div>'
            f'<div class="answer"><span>Which would you post?</span>{radios}</div>'
            f'<textarea placeholder="What works, what doesn\'t (optional)" '
            f'aria-label="Comment on post {n}"></textarea></section>')
        key_rows.append(f"| {n} | `{name}` | " + ", ".join(
            f"{letter} = {w}" for letter, w in zip(letters, order, strict=True)) + " |")
    store_key = json.dumps("prose-read:" + re.sub(r"\W+", "-", out.stem + "-" + str(seed)))
    page = (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n<style>{CSS}</style></head>\n<body>"
        '<div class="bar"><span id="copied" aria-live="polite"></span>'
        '<button id="copy" type="button">Copy my answers</button>'
        '<button id="mode" type="button">Light / dark</button></div>\n<main>'
        f"<h1>{html.escape(title)}</h1>"
        f'<p class="lede">{len(names)} posts. Each was written by {len(writers)} '
        f"writer{'s' if len(writers) != 1 else ''} from the same facts and the same angle; "
        "the versions are unlabeled and in a random order of their own. Pick the one you "
        "would post, or None, and say why if you like. Your answers stay in this browser; "
        "Copy my answers puts them on the clipboard. The key is in a separate file: open it "
        "after.</p>\n"
        + "\n".join(sections)
        + '<div id="manual"><p>The clipboard was refused: copy your answers from here.</p>'
          '<textarea readonly aria-label="Your answers"></textarea></div>'
        + f"</main><script>{JS % {'key': store_key}}</script></body></html>\n")
    out.write_text(page, encoding="utf-8")
    key.write_text(
        f"# The key to {out.name}\n\nDon't open this before you have read and picked.\n\n"
        f"Writers: {', '.join(writers)}. Order shuffled per post (seed {seed}).\n\n"
        "| # | Post | Which is which |\n|---|---|---|\n" + "\n".join(key_rows) + "\n",
        encoding="utf-8")
    return {"posts": len(names), "writers": writers}
