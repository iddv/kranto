"""The two checks beside the contracts:
the stored-shape lint (``scripts/ci/stored_shape_lint.py``) and the type check's ratchet
(``scripts/ci/typecheck.py``). The lint's cases are the unguarded similarity read in the six
shapes probed, and one case per guard it understands."""
from __future__ import annotations

import importlib.util
import json
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CI = ROOT / "scripts" / "ci"


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(f"ci_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lint = _load(CI / "stored_shape_lint.py")
typecheck = _load(CI / "typecheck.py")

CONTRACT = '''
from dataclasses import dataclass
class Validation:
    COLUMN = ("sources", "validation")
    SETTING = "money.tools_approved.*"
    status: str = ""
    median_similarity: float | None = None
'''


def findings(tmp_path: Path, code: str, contract: str = CONTRACT) -> list[tuple[str, int]]:
    """(rule, line) for each finding in ``code``, linted beside a contract module."""
    stored = tmp_path / "pkg" / "stored"
    stored.mkdir(parents=True, exist_ok=True)
    (stored / "sources.py").write_text(textwrap.dedent(contract))
    f = tmp_path / "pkg" / "reader.py"
    f.write_text(textwrap.dedent(code))
    out = lint.lint_files(lint.files_under([tmp_path / "pkg"]))
    return [(rule, line) for path, line, rule, _, _ in out if path == f]


def rules(tmp_path: Path, code: str) -> set[str]:
    return {r for r, _ in findings(tmp_path, code)}


# -- the unguarded similarity read, six shapes (the probe) --

def test_the_unguarded_similarity_line_is_found(tmp_path):
    """mypy and pyright see nothing here, strict or not."""
    assert rules(tmp_path, '''
        def status(s):
            v = s.validation or {}
            return f"sim {v.get('median_similarity', 0):.2f}"
        ''') == {"GET-DEFAULT", "GET-FORMAT"}


def test_the_typed_field_formatted_without_a_guard_is_found(tmp_path):
    """The typed f-string: no type checker inspects the format spec."""
    assert rules(tmp_path, '''
        def status(v):
            return f"sim {v.median_similarity:.2f}"
        ''') == {"ATTR-FORMAT"}


def test_the_typed_field_through_an_assignment_is_found_and_its_guard_clears_it(tmp_path):
    """``sim = v.median_similarity; f"{sim:.2f}"``: the shape _status reads it in."""
    assert findings(tmp_path, '''
        def status(v):
            sim = v.median_similarity
            return f"sim {sim:.2f}"
        ''') == [("ATTR-FORMAT", 4)]
    assert findings(tmp_path, '''
        def status(v):
            sim = v.median_similarity
            return f"sim {sim:.2f}" if sim is not None else ""
        ''') == []


def test_one_file_is_linted_against_the_whole_package(tmp_path):
    """Linting a single file still knows which fields the contracts declare `| None`."""
    findings(tmp_path, "")                          # writes the contract module
    reader = tmp_path / "pkg" / "one.py"
    reader.write_text("def f(v):\n    return f'{v.median_similarity:.2f}'\n")
    out = lint.lint_files([reader], lint.files_under([tmp_path / "pkg"]))
    assert [r for _, _, r, _, _ in out] == ["ATTR-FORMAT"]
    assert lint.lint_files([reader]) == []          # alone, it cannot know


@pytest.mark.parametrize("expr", ["round(v.median_similarity, 2)", "v.median_similarity >= line",
                                  "v.median_similarity * 100"])
def test_the_typed_siblings_are_left_to_the_type_checker(tmp_path, expr):
    """round(), >= and * on a float | None are mypy's (arg-type, operator) once typed."""
    assert rules(tmp_path, f'''
        def status(v, line):
            return {expr}
        ''') == set()


def test_the_fix_is_clean(tmp_path):
    assert rules(tmp_path, '''
        def status(v):
            sim = v.median_similarity
            return f"sim {sim:.2f}" if sim is not None else ""

        def status2(v):
            return f"sim {v.median_similarity:.2f}" if v.median_similarity is not None else ""
        ''') == set()


# -- the guards it understands --

@pytest.mark.parametrize("code", [
    '''
    def f(d):
        x = d.get("n")
        if x is not None:
            return f"{x:.2f}"
    ''',
    '''
    def f(d):
        x = d.get("n")
        if x is None:
            return ""
        else:
            return f"{x:.2f}"
    ''',
    '''
    def f(d):
        x = d.get("n")
        return x and f"{x:.2f}"
    ''',
    '''
    def f(d):
        x = d.get("n")
        return x is None or x > 3
    ''',
    '''
    def f(d):
        x = d.get("n")
        if isinstance(x, (int, float)):
            return round(x)
    ''',
    '''
    def f(d):
        x = d.get("n")
        if str(x or "").isdigit():
            return int(x)
    ''',
    '''
    def f(d):
        try:
            return int(d.get("n"))
        except (TypeError, ValueError):
            return 0
    ''',
    '''
    def f(d):
        return f"{d.get('n') or 0:.2f}"
    ''',
    '''
    def f(v):
        if v.median_similarity:
            return f"{v.median_similarity:.2f}"
    ''',
    '''
    def f(v):
        return v.median_similarity is None or f"{v.median_similarity:.2f}"
    ''',
    '''
    def f(v, spent):
        cap = v.median_similarity
        if cap is None or spent < 1:
            return None
        return f"{cap:.2f}"
    ''',
    '''
    def f(v):
        if v.median_similarity is None:
            raise ValueError("not measured")
        return f"{v.median_similarity:.2f}"
    ''',
    '''
    def f(d):
        x = d.get("n")
        if x is None:
            return ""
        return f"{x:.2f}"
    ''',
])
def test_a_guarded_read_is_not_a_finding(tmp_path, code):
    assert findings(tmp_path, code) == []


def test_an_unguarded_get_formatted_compared_or_counted_is_found(tmp_path):
    got = findings(tmp_path, '''
        def f(d):
            x = d.get("n")
            a = f"{x:,}"
            b = x > 3
            c = len(d.get("items"))
            return a, b, c
        ''')
    assert sorted(got) == [("GET-FORMAT", 4), ("GET-FORMAT", 5), ("GET-FORMAT", 6)]


def test_the_counting_idiom_and_text_formats_are_not_findings(tmp_path):
    assert findings(tmp_path, '''
        def f(rows, d, when):
            counts = {}
            for r in rows:
                counts[r] = counts.get(r, 0) + 1
            return f"{d.get('name'):>10}", f"{when:%Y-%m-%d}", "x" + d.get("s")
        ''') == []


def test_a_finding_dismissed_on_its_line_is_not_reported(tmp_path):
    assert findings(tmp_path, '''
        def f(s):
            v = s.validation or {}
            return v.get("items", 0)  # stored-shape: every writer stores items (packs, cli)
        ''') == []


# -- JSON-OUTSIDE --

def test_a_typed_column_loaded_or_dumped_outside_its_contract_is_found(tmp_path):
    got = findings(tmp_path, '''
        import json
        def read(row, d, store, adapter):
            a = json.loads(row["validation"])
            b = json.loads(d.get("validation") or "{}")
            store.insert("sources", {"validation": json.dumps(a)})
            store.set_setting(f"money.tools_approved.{adapter}", json.dumps(b))
            c = json.loads(row["summary"])            # no contract yet: not this rule
            return c
        ''')
    assert sorted(got) == [("JSON-OUTSIDE", 4), ("JSON-OUTSIDE", 5), ("JSON-OUTSIDE", 6),
                           ("JSON-OUTSIDE", 7)]


def test_the_contract_module_itself_may_load_and_dump(tmp_path):
    stored = tmp_path / "pkg" / "stored"
    stored.mkdir(parents=True)
    (stored / "sources.py").write_text(textwrap.dedent(CONTRACT) + textwrap.dedent('''
        import json
        def raw(row):
            return json.loads(row["validation"])
        '''))
    out = lint.lint_files(lint.files_under([tmp_path / "pkg"]))
    assert [r for _, _, r, _, _ in out] == []


# -- the baseline --

def test_the_baseline_keys_a_finding_by_its_line_text_not_its_number(tmp_path):
    a = lint.key_of(Path("x.py"), "GET-DEFAULT", "    v.get('n', 0)\n")
    b = lint.key_of(Path("x.py"), "GET-DEFAULT", "v.get('n', 0)")
    assert a == b and a.startswith("x.py:GET-DEFAULT:")


def test_the_lint_passes_on_main_with_its_baseline():
    """What CI runs: every finding on today's code is in the baseline, and nothing in the
    baseline is stale."""
    files = lint.files_under([ROOT / p for p in lint.DEFAULT_PATHS])
    keys = [lint.key_of(lint.rel(f), rule, text) for f, _, rule, _, text in lint.lint_files(files)]
    from collections import Counter
    now, base = Counter(keys), lint.load_baseline()
    assert not (now - base), f"new findings: {sorted((now - base).elements())}"
    assert not (base - now), f"stale baseline lines: {sorted((base - now).elements())}"


# -- the type check's ratchet --

def test_the_ratchet_fails_a_rise_and_keeps_a_fall():
    lines = ["src/a.py:3: error: x  [arg-type]", "src/a.py:9: error: y  [index]",
             "src/b.py:1: error: z  [union-attr]", "src/a.py:3: note: not an error"]
    now = typecheck.counts(lines)
    assert now == {"src/a.py": 2, "src/b.py": 1}
    rose, fell = typecheck.compare(now, {"src/a.py": 1, "src/c.py": 4})
    assert rose == {"src/a.py": (1, 2), "src/b.py": (0, 1)}       # a new file starts at 0
    assert fell == {"src/c.py": (4, 0)}
    assert typecheck.lowered({"src/a.py": 1}, {"src/a.py": 3, "src/c.py": 2}) == {"src/a.py": 1}


def test_the_baseline_file_round_trips(tmp_path):
    p = tmp_path / "b.json"
    typecheck.write_baseline({"src/a.py": 2, "src/z.py": 0}, p)
    assert typecheck.load_baseline(p) == {"src/a.py": 2}
    assert json.loads(p.read_text())["total"] == 2


def test_the_strict_modules_have_no_baseline():
    """A module made strict starts at 0 and stays there: it is never in the baseline."""
    base = typecheck.load_baseline()
    strict = [f for f in base if "/stored/" in f or f.endswith("web/types.py")]
    assert strict == []
