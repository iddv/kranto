"""The one scrubber (``errtrace``): what an error may say outside Kranto.

The properties: whatever a message holds, a secret, a path under a home, an address, an email
or an id never survives the template; a stack is Kranto's own frames and library names, never a
path or a value; the signature is the type and Kranto's frames, not their lines."""

from __future__ import annotations

import json
import re
import sqlite3

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from kranto import errtrace
from kranto.telemetry import local

VOCAB = errtrace.vocabulary()
_TOKEN = re.compile(r"[A-Za-z0-9_]+")


def _not_a_word(s: str) -> bool:
    return all(not errtrace.known_word(w) for w in _TOKEN.findall(s))


name = st.from_regex(r"[a-z][a-z0-9]{5,11}", fullmatch=True).filter(_not_a_word)
host = st.builds(lambda a, b: f"{a}.{b}", name, st.sampled_from(["com", "org", "io", "eu"]))
hexid = st.from_regex(r"[0-9a-f]{12,40}", fullmatch=True).filter(_not_a_word)
secret = st.one_of(
    st.from_regex(r"sk-ant-[A-Za-z0-9_-]{24,40}", fullmatch=True),
    st.from_regex(r"sk-or-v1-[a-f0-9]{32,64}", fullmatch=True),
    st.from_regex(r"ghp_[A-Za-z0-9]{36}", fullmatch=True),
    st.from_regex(r"github_pat_[A-Za-z0-9_]{40,60}", fullmatch=True),
    st.from_regex(r"AKIA[0-9A-Z]{16}", fullmatch=True),
    st.from_regex(r"xox[abp]-[A-Za-z0-9-]{20,40}", fullmatch=True),
    st.from_regex(r"eyJ[A-Za-z0-9_-]{10,30}\.eyJ[A-Za-z0-9_-]{10,30}\.[A-Za-z0-9_-]{10,30}",
                  fullmatch=True),
).filter(_not_a_word)
filler = st.lists(st.sampled_from(sorted(VOCAB)), max_size=6).map(" ".join)


def _sensitive():
    """``(the text put in a message, the parts that must not come out)``."""
    home = st.builds(lambda root, u, d, f: (f"{root}/{u}/{d}/{f}.db", [u, d, f]),
                     st.sampled_from(["/home", "/Users", "/var/home"]), name, name, name)
    url = st.builds(lambda h, p, v: (f"https://{h}/{p}?q={v}", [h, h.split('.')[0], p, v]),
                    host, name, name)
    email = st.builds(lambda u, h: (f"{u}@{h}", [u, h.split('.')[0]]), name, host)
    ident = st.builds(lambda x: (x, [x]), hexid)
    uuid = st.uuids().map(lambda u: (str(u), [p for p in str(u).split("-") if _not_a_word(p)]))
    number = st.integers(1000, 10**12).map(lambda n: (str(n), [str(n)]))
    sec = st.builds(lambda s: (s, [s] + [p for p in re.split(r"[^A-Za-z0-9]+", s)
                                        if len(p) >= 6 and _not_a_word(p)]), secret)
    quoted = st.builds(lambda u: (f"'{u}'", [u]), name)
    return st.one_of(home, url, email, ident, uuid, number, sec, quoted)


@settings(max_examples=400, deadline=None)
@given(before=filler, item=_sensitive(), after=filler)
def test_nothing_sensitive_survives_the_template(before, item, after):
    text, parts = item
    out = errtrace.template(f"{before} {text} {after}")
    assert text not in out
    for p in parts:
        assert p not in out, (p, out)
    assert "/" not in out and "@" not in out and "?" not in out


@settings(max_examples=400, deadline=None)
@given(st.text(max_size=400))
def test_a_template_is_known_words_and_placeholders_only(text):
    out = errtrace.template(text)
    assert len(out) <= errtrace.MAX_MESSAGE
    rest = out.replace("<x>", " ").replace("<n>", " ")
    assert all(errtrace.known_word(w) for w in _TOKEN.findall(rest)), out
    assert set(rest) <= set(" '\"(),.:;[]=-") | {c for w in _TOKEN.findall(rest) for c in w}


def test_the_incidents_message_keeps_its_words():
    msg = "unsupported format string passed to NoneType.__format__"
    assert errtrace.template(msg) == msg
    assert errtrace.template("'NoneType' object has no attribute 'median_similarity'") == \
        "'NoneType' object has no attribute '<x>'"
    assert errtrace.template("invalid literal for int() with base 10: 'Robotics'") == \
        "invalid literal for int() with base <n>: '<x>'"
    assert errtrace.template("no such table: topics_now") == "no such table: <x>"


def _raise_through_json(exc: Exception):
    def hook(_):
        raise exc
    json.loads('{"a": 1}', object_hook=hook)


def test_library_frames_collapse_to_their_package_and_no_path_survives(tmp_path):
    try:
        _raise_through_json(KeyError(str(tmp_path / "secret.txt")))
    except KeyError as exc:
        t = errtrace.scrub(exc)
    assert t.type == "KeyError"
    assert t.frames == ("[other]", "[json]", "[other]")
    assert t.message == "'<x>'"
    assert "/" not in t.stack and str(tmp_path) not in repr(t)


def test_kranto_own_frames_are_module_function_line():
    try:
        local.parse({"mode": "basic", "token_sk-ant-abcdefghijklmnopqrstuvwx": 1})
    except local.TelemetryError as exc:
        t = errtrace.scrub(exc)
    assert t.type == "kranto.telemetry.local.TelemetryError"
    assert t.frames[0] == "[other]"
    assert re.fullmatch(r"kranto\.telemetry\.local\.parse:\d+", t.frames[-1])
    assert "sk-ant" not in t.message and "abcdefghij" not in t.message
    assert t.message.startswith("unknown keys in <x>")


def test_the_signature_is_the_type_and_own_frames_without_lines():
    a = errtrace.signature("TypeError", ("[starlette]", "kranto.x.f:10", "kranto.y.g:20"))
    b = errtrace.signature("TypeError", ("kranto.x.f:11", "[anyio]", "kranto.y.g:99"))
    c = errtrace.signature("KeyError", ("kranto.x.f:10", "kranto.y.g:20"))
    assert a == b != c
    assert re.fullmatch(r"[0-9a-f]{16}", a)


def test_type_names():
    assert errtrace.type_name(TypeError("x")) == "TypeError"
    assert errtrace.type_name(sqlite3.OperationalError("x")) == "sqlite3.OperationalError"

    class Mine(Exception):
        pass

    assert errtrace.type_name(Mine()) == "Exception"   # a class from outside Kranto and libraries


def test_a_failure_has_no_frames_and_a_template():
    t = errtrace.failure("UpdateSelfCheck", "GET /api/topics/12 answered 500")
    assert t.frames == () and t.type == "UpdateSelfCheck"
    assert "12" not in t.message and t.message.endswith("<n>")
    assert errtrace.failure("not a type!", "").type == "Exception"


def test_scrub_never_raises():
    class Bad(Exception):
        def __str__(self):
            raise RuntimeError("no")

    t = errtrace.scrub(Bad())
    assert t.message == "" and t.type == "Exception"


@pytest.mark.parametrize("deep", [5, 80])
def test_at_most_the_innermost_frames(deep):
    def f(n):
        if n == 0:
            raise ValueError("x")
        return f(n - 1)
    try:
        f(deep)
    except ValueError as exc:
        t = errtrace.scrub(exc)
    assert len(t.frames) <= errtrace.MAX_FRAMES
