"""A model's failure said for the provider in use: Claude Code not installed says so and how to
fix it, and "model key" is said only to a provider that takes a key."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from kranto import model_trouble
from kranto.web import post_api

NOT_INSTALLED = "Claude Code: Claude Code is not installed (no claude on PATH)"


def test_claude_code_not_installed_is_said_with_how_to_fix_it_and_no_key():
    t = model_trouble.said(NOT_INSTALLED, "claude_code")
    assert t is not None and t["key"] is False and t["fix"] == "settings/watching"
    assert t["words"].startswith("Claude Code is not installed on this machine.")
    assert "choose another provider on Settings › Watching" in t["words"]
    assert model_trouble.CLAUDE_INSTALL in t["words"]
    assert "key" not in t["words"]


def test_the_words_follow_the_provider():
    # a model that did not answer: Claude Code is checked, a key provider's key is
    cc = model_trouble.said("the model did not answer: TransientLLMError", "claude_code")
    assert cc is not None and "key" not in cc["words"] and "Claude Code" in cc["words"]
    orr = model_trouble.said("the model did not answer: TransientLLMError", "openrouter")
    assert orr is not None and "model key" in orr["words"] and orr["key"] is True
    missing = model_trouble.said("No angles: $OPENROUTER_API_KEY is not set", "openrouter")
    assert missing is not None and missing["words"] == model_trouble.NO_KEY
    signed_out = model_trouble.said("Claude Code is not signed in: run 'claude auth login'")
    assert signed_out is not None and signed_out["words"] == model_trouble.NOT_SIGNED_IN
    refused = model_trouble.said("FatalLLMError: HTTP 401 from https://openrouter.ai/api/v1: "
                                 "invalid api key", "openrouter")
    assert refused is not None and "OpenRouter key was refused" in refused["words"]
    assert model_trouble.said("Brief 41 has no item 9.") is None
    assert model_trouble.said("") is None


@pytest.mark.parametrize("why", [
    NOT_INSTALLED,
    "failed: the handler raised HostError after Kranto answered: the model did not answer: "
    "FatalLLMError: " + NOT_INSTALLED,
    # short posts: each site's failure, joined
    "Bluesky: " + NOT_INSTALLED + "; X: " + NOT_INSTALLED,
])
def test_every_failed_write_says_claude_code_is_not_installed(why):
    said = post_api.not_written(why, "claude_code")
    assert said.startswith("No draft was written: Claude Code is not installed on this machine.")
    assert "model key" not in said and "PATH" not in said
    assert said.endswith("Then choose Write a post again.")


def test_a_failed_writes_line_on_post_links_where_it_is_fixed(tmp_path):
    from kranto.web.jobs import Jobs
    jobs = Jobs(tmp_path / "jobs")
    jobs.fail("post:short:card:1", post_api.not_written(NOT_INSTALLED, "claude_code"))
    store = SimpleNamespace(query_one=lambda *a, **k: {"title": "A card"})
    [f] = post_api.failed_writes(store, jobs)
    assert f["fix"] == "settings/watching" and "Claude Code is not installed" in f["error"]


def test_the_angle_step_says_claude_code_is_not_installed(monkeypatch):
    """The angle step's proposals showed "Claude Code: Claude Code is not installed (no claude on
    PATH)" raw."""
    from kranto import prose

    def boom(*a, **k):
        raise RuntimeError(NOT_INSTALLED)
    monkeypatch.setattr(post_api, "material_for", lambda rt, about: {"title": "t", "facts": "f"})
    monkeypatch.setattr(prose, "load", lambda cfg, store: SimpleNamespace(
        writer_model=lambda w: None))
    monkeypatch.setattr(prose, "angles", boom)
    llm = SimpleNamespace(has_key=True, provider_for=lambda tier: SimpleNamespace(
        name="claude_code"))
    rt = SimpleNamespace(llm=llm, cfg=None, store=None)
    with pytest.raises(post_api.WriteError) as e:
        post_api.propose_angles(rt, "card:1", "blog")
    assert e.value.words.startswith("No angles were proposed: Claude Code is not installed")
    assert e.value.words.endswith("Or type your own sentence.")
    assert e.value.fix == "settings/watching" and "model key" not in e.value.words
