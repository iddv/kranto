"""The words Kranto serves to the owner name no setting key (QA BUGS B10, the guard for the kind:
"every 3 h · ingest.every_hours", "up to look.screen_batch a call", "the news-thesis path is off
(invest.news_theses)"). What a page reads from the server as words: each prompt's row on Settings ›
Prompts, and each feature's says, its jobs' and actions' words, its tile and its settings' words.
A key belongs in a code span on the row's sheet ("the key and its file"), never in these."""

import re

import yaml

from kranto import config as config_mod
from kranto import features as features_pkg
from kranto.prompts import REGISTRY


def keys() -> list[str]:
    """Every dotted key of kranto.yaml's defaults and of the features' own sections."""
    def walk(d, pre=""):
        for k, v in d.items():
            yield f"{pre}{k}"
            if isinstance(v, dict):
                yield from walk(v, f"{pre}{k}.")
    out = {k for k in walk(yaml.safe_load(config_mod.DEFAULT_CONFIG_YAML)) if "." in k}
    # and the keys the default file documents commented out ("  # github_client_id: ..." under
    # connections:), which a person writes by hand
    section = None
    for line in config_mod.DEFAULT_CONFIG_YAML.splitlines():
        if m := re.match(r"^([a-z_]+):", line):
            section = m.group(1)
        elif section and (m := re.match(r"^\s+#\s*([a-z_]+):(\s|$)", line)):
            out.add(f"{section}.{m.group(1)}")
    for f in features_pkg.FEATURES:
        out |= {k for k in f.settings.keys if "." in k}
    return sorted(out, key=len, reverse=True)


def served() -> list[tuple[str, str]]:
    """(where, words) for every string the pages show from the server's manifests and prompts."""
    out = []
    for e in REGISTRY:
        out += [(f"prompt {e.id}", s) for s in (e.title, e.purpose, e.where)]
    for f in features_pkg.FEATURES:
        out += [(f.id, s) for s in (f.title, f.says, f.ui.tile.line, f.ui.tile.words)]
        out += [(j.kind, j.says) for j in f.jobs]
        out += [(a.kind, a.title) for a in f.actions] + [(a.kind, a.says) for a in f.actions]
        out += [(k, s.words) for k, s in f.settings.keys.items()]
    # Settings › Accounts: each provider's line and sheet (found the GitHub blurb's key
    # on live, a pane the browser smoke's guard never draws)
    from kranto.connections import PROVIDER_INFO
    for p in PROVIDER_INFO:
        out += [(f"provider {p['key']}", p.get(k) or "")
                for k in ("blurb", "reads", "never", "reason")]
    return [(w, s) for w, s in out if s]


def offending(text: str, ks: list[str]) -> list[str]:
    return [k for k in ks if re.search(rf"(?<![\w.]){re.escape(k)}(?![\w])", text)]


def test_the_check_finds_a_key_and_passes_words():
    ks = keys()
    assert "look.screen_batch" in ks and "ingest.every_hours" in ks and "news.hour" in ks
    assert "connections.github_client_id" in ks                    # documented, commented out
    assert offending("up to look.screen_batch a call", ks) == ["look.screen_batch"]
    assert offending("in your settings (kranto.yaml) · example.com", ks) == []


def test_no_served_word_names_a_setting_key():
    ks = keys()
    bad = [(w, k, s) for w, s in served() for k in offending(s, ks)]
    assert not bad, bad
