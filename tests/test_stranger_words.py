"""What a stranger met on a fresh install, in words: the watcher's commands say something on an
empty home and name no provider nobody chose; the server's words the page and `kranto status`
show say "feature", never the developer's word "cub" (its setting keys and SDK aside)."""
from __future__ import annotations

import re

from kranto import cli
from kranto import config as config_mod


def test_an_empty_home_lists_no_topics_in_words(tmp_path, capsys, monkeypatch):
    kb = tmp_path / "kb"
    assert cli.main(["init", str(kb)]) == 0
    capsys.readouterr()
    assert cli.main(["-w", str(kb), "topics", "list"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("no topics yet: ")
    assert "kranto watch topics add NAME DESCRIPTION" in out


def test_status_names_no_provider_before_one_is_chosen(tmp_path, capsys, monkeypatch):
    for v in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", config_mod.WORKSPACE_ENV):
        monkeypatch.delenv(v, raising=False)
    kb = tmp_path / "kb"
    assert cli.main(["init", str(kb)]) == 0
    capsys.readouterr()
    assert cli.main(["-w", str(kb), "status"]) == 0
    out = capsys.readouterr().out
    assert "api key:      no model chosen yet" in out
    assert "OPENROUTER_API_KEY" not in out


CUB = re.compile(r"\bcubs?\b", re.I)


def test_the_jobs_words_say_feature():
    from kranto.activity import words
    flat = [s for w in words.KINDS.values() for s in w if s]
    assert any("features' updates" in s for s in flat)
    assert [s for s in flat if CUB.search(s)] == []


def test_the_settings_words_say_feature():
    from kranto.core.cubs import settings
    every = {**settings.GLOBAL, **settings.PER_CUB}
    said = {k: s.words for k, s in every.items() if s.words}
    assert said
    # the SDK is the developer's thing and keeps its name
    assert {k: w for k, w in said.items() if CUB.search(w) and "SDK" not in w} == {}
