"""The ? tip and the docs page: ui/tips.json is one map of plain JSON; every id a tip
names exists; a tip that links to the docs lands on a heading of help.md, served at /help (at
/brb/help under the server); no tip says again what the page already says; the sign-in box keeps
its ids and puts its instructions behind its ?."""
import json
import re
from pathlib import Path

from kranto.page.ui import api
from kranto.page.ui import help as helpdoc

from .webui import css, everything, src

UI = Path(api.__file__).parent
JS = everything()
CSS = css()
TIPS = src("ui/tips.json")


def tips() -> dict:
    return json.loads(TIPS)



def test_tips_are_plain_json_with_words():
    t = tips()
    assert t and all(set(v) <= {"text", "docs"} and v["text"].strip() for v in t.values())
    assert all(isinstance(v.get("docs", True), (bool, str)) for v in t.values())


def test_every_tip_id_used_exists():
    t = tips()
    # <Tip id=…>, a list's or a pane's about= (its head's ?) and a section's about:
    used = set(re.findall(r'<Tip id="([^"]+)"', JS)) | set(re.findall(r'<(?!Tip\b)[A-Z]\w*\b[^>]*?\babout="([^"]+)"', JS))
    used |= set(re.findall(r'\babout: "([^"]+)"', JS))
    used |= set(re.findall(r'tipText\("([^"]+)"\)', JS))
    assert used, "no tip is used"
    assert used <= set(t), sorted(used - set(t))


def test_every_docs_link_has_its_heading():
    heads = {i for i, _ in helpdoc.sections()}
    slug = lambda s: re.sub(r"[^a-z0-9]+", "-", s.lower())
    want = {slug(k if v["docs"] is True else v["docs"]) for k, v in tips().items() if v.get("docs")}
    want |= {slug(x) for x in re.findall(r'\bdocs: "([^"]+)"', JS)}       # a tip worked out from data
    assert want, "no tip links to the docs"
    assert want <= heads, sorted(want - heads)


def test_no_tip_repeats_a_sentence_drawn_beside_it():
    body = JS.replace(TIPS, "\n")
    for k, v in tips().items():
        for sentence in re.split(r"(?<=[.!?])\s+", v["text"]):
            if len(sentence.split()) >= 6:
                assert sentence not in body, (k, sentence)


def test_the_tip_is_the_one_popover():
    # its ways of opening and closing are ui/tips.svelte.test.ts's
    t = src("ui/Tip.svelte")
    assert 'import TIPS from "./tips.json"' in t and "popover(b" in t      # the one popover: one open at a time
    assert "textContent" not in t and "innerHTML" not in t and "{@html" not in t
    assert ".tip:focus-visible" in CSS and ".pop.tipbox" in CSS


def test_the_sign_in_box_is_one_line_with_its_ids_and_a_tip():
    s = src("shell/ListHead.svelte")
    for part in ('id="signin"', 'id="signin-code"', 'id="signin-go"', '<Tip id="signin" about="signing in" />', ">Not signed in:<"):
        assert part in s, part                                            # the ? is the tips' own
    assert "/auth/code" in src("lib/app/data.ts")
    assert "Run " not in s and "the link it prints" not in s          # the steps are the ?'s
    assert "kranto open" in tips()["signin"]["text"]
    assert "#signin.line" in CSS


def test_settings_hints_are_tips():
    for f in ("UpdatesPane", "ModelsPane", "SpendPane", "CatalogPane", "KeysPane", "KeyField"):        # moved: a hint is FLabel's ?
        assert 'class="hint"' not in src(f"pages/settings/{f}.svelte"), f


def test_the_help_page_is_served_and_escaped():
    code, ctype, data = api.handle("GET", "/help", app=object())
    page = data.decode()
    assert code == 200 and ctype.startswith("text/html")
    for hid, _ in helpdoc.sections():
        assert f'id="{hid}"' in page
    assert page.index("static/theme.js") < page.index("static/kranto.css")
    assert "<script>" not in page
    assert "&lt;idea id&gt;" in page or "&lt;name&gt;" in page          # every text is escaped
    assert helpdoc.render("## A <b> {#x}\n\nhi `<i>` [l](javascript:alert(1))") == \
        '<h2 id="x">A &lt;b&gt;</h2>\n<p>hi <code>&lt;i&gt;</code> [l](javascript:alert(1))</p>'


def test_the_help_page_names_keys_as_the_readers_computer_does():
    """help.md writes ⌘K once; the page shows Ctrl+K on Linux and Windows and ⌘K on a Mac
    (theme.js marks a Mac on <html>, kranto.css shows the one that fits)."""
    assert helpdoc.render("Press ⌘K.") == ('<p>Press <span class="modkey"><span class="k-pc">'
                                          'Ctrl+K</span><span class="k-mac">⌘K</span></span>.</p>')
    assert "ctrl J)" not in helpdoc.HELP.read_text()       # the label says it now
    static = Path(helpdoc.__file__).with_name("static")
    assert 'setAttribute("data-mac"' in (static / "theme.js").read_text()
    assert "html[data-mac] .modkey .k-mac" in (static / "kranto.css").read_text()
