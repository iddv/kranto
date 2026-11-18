"""The API's types: ``src/kranto/page/ui/types.py`` says what the page's reads
answer, and three guards keep it true. (1) The generated TypeScript is current (``gen_ts.py
--check``). (2) Every typed route's real answer on the page's server, with a console session in
its loop home, has the shape its TypedDict says (here). (3) ``svelte-check`` fails a component
that reads a field that is gone (CI's frontend job)."""
import copy
import importlib.util
import json
import threading
import urllib.request
from pathlib import Path

import pytest

from kranto.page.ui import api
from kranto.page.ui import types as T
from kranto.page.ui.server import make_server

from .app_common import make_home
from .test_trace_session import TID, make_session

ROOT = Path(__file__).resolve().parents[2]


def _gen_ts():
    spec = importlib.util.spec_from_file_location("gen_ts", ROOT / "scripts" / "dev" / "gen_page_ts.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def app(tmp_path):
    from kranto.page.trace import service
    service._TRACES.clear()
    cfg = make_home(tmp_path)
    make_session(cfg.home)
    yield api.App(None, "fake", cfg.home)


def get(app, path: str, query=None):
    code, ctype, body = api.handle("GET", "/" + path.lstrip("/"), query, app=app)
    assert code == 200 and ctype.startswith("application/json"), (path, code, body[:200])
    return json.loads(body)


def test_the_generated_typescript_is_current():
    gen = _gen_ts()
    stale = [name for name, make in gen.FILES.items() if (gen.OUT / name).read_text() != make()]
    assert not stale, f"stale: {stale}; run python3 scripts/dev/gen_page_ts.py"


def test_every_typed_route_answers_its_type(app):
    from kranto.page.trace.model import span_id
    tr = f"session:{TID}"
    run = span_id(tr, "run")
    query = {"api/trace": {"trace": tr}, "api/trace/spans": {"trace": tr},
             "api/trace/search": {"trace": tr, "q": "idea"},
             "api/trace/span": {"trace": tr, "span": run},
             "api/trace/payload": {"trace": tr, "span": run, "part": "output"},
             "api/trace/follow": {"trace": tr}}
    seen = {}
    for path, tp in T.RETURNS.items():
        if path.startswith("/"):
            continue                                  # a server's own route: below
        seen[path] = got = get(app, path, query.get(path))
        assert T.problems(got, tp) == [], path
    # the check read a real row, not an empty list: the session lists without being opened
    assert [r["id"] for r in seen["api/traces"]["traces"]] == [tr]
    gone = {"api/info", "api/kranto", "api/loop/editor", "api/actions", "api/outcomes",
            "api/build/runs", "api/run", "api/trace/compare"}
    assert not gone & set(T.RETURNS)                  # the factory's reads left


def test_whoami_answers_its_type(app):
    srv = make_server(None, port=0, harness="fake", loop_home=app.loop_home)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}/api/whoami",
                                    timeout=30) as r:
            assert T.problems(json.loads(r.read()), T.WhoAmI) == []
    finally:
        srv.shutdown()
        srv.server_close()


def test_a_renamed_or_retyped_field_is_caught(app):
    """What the check exists for: a field the page reads renamed, dropped or retyped."""
    s = get(app, "api/traces")
    assert T.problems(s, T.TraceList) == []
    bad = copy.deepcopy(s)
    bad["traces"][0]["name"] = bad["traces"][0].pop("title")        # renamed
    bad["traces"][0]["sessions"] = "one"                             # retyped
    del bad["next"]                                                  # dropped
    bad["flagged"] = 1                                               # added to a closed type
    got = T.problems(bad, T.TraceList)
    assert "$.traces[0]: no 'title' (TraceSummary)" in got
    assert "$.traces[0].sessions: 'one' is not an integer" in got
    assert "$: no 'next' (TraceList)" in got
    assert "$: 'flagged' is not in TraceList" in got
    assert T.problems({**get(app, "api/header"), "extra": 1}, T.Header) == [
        "$: 'extra' is not in Header"]


def test_the_checks_rules():
    assert T.problems(1, float) == [] and T.problems(True, int) != [] and T.problems(1.5, int)
    assert T.problems(None, str | None) == [] and T.problems(3, str | None)
    assert T.problems("term", T.ChangeKind) == [] and T.problems("chat", T.ChangeKind)
    assert T.problems({"a": 1}, dict[str, int]) == [] and T.problems({"a": "1"}, dict[str, int])
    assert T.problems([1, "2"], list[int]) == ["$[1]: '2' is not an integer"]
    with pytest.raises(TypeError):
        T.problems(1, complex)


def test_every_type_generates_and_the_stream_is_typed():
    gen = _gen_ts()
    text = gen.types_ts()
    for name in ("Header", "WhoAmI", "TraceList", "Activity", "StreamChange", "StreamHost"):
        assert f"export interface {name} {{" in text, name
    assert '"api/traces": TraceList;' in text and f"API_VERSION = {api.API_VERSION};" in text
    assert "  calls?: number;" in text                               # NotRequired
    assert set(gen.FILES) == {"types.gen.ts"}                        # actions.gen.ts left
