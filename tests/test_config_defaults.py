"""The written config template states the defaults: a workspace made from it behaves exactly
as one whose file names only the required ``llm`` section (a key left out of a hand-written
file must not mean something else than the template's line for it)."""
from __future__ import annotations

import dataclasses

import yaml

from kranto import config as config_mod


def test_the_template_is_the_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    full, bare = tmp_path / "full", tmp_path / "bare"
    full.mkdir()
    bare.mkdir()
    (full / config_mod.CONFIG_FILENAME).write_text(config_mod.DEFAULT_CONFIG_YAML)
    llm = yaml.safe_load(config_mod.DEFAULT_CONFIG_YAML)["llm"]
    (bare / config_mod.CONFIG_FILENAME).write_text(yaml.safe_dump({"llm": llm}))
    a = config_mod.load(full, dotenv=False)
    b = config_mod.load(bare, dotenv=False)
    # Claude Code's cwd and home are the home's own paths, not defaults
    b = dataclasses.replace(b, llm=dataclasses.replace(b.llm, claude_code=a.llm.claude_code))
    differ = [f.name for f in dataclasses.fields(a)
              if f.name != "root" and getattr(a, f.name) != getattr(b, f.name)]
    assert differ == []


def test_the_templates_reply_ceilings_are_the_codes():
    import re
    text = config_mod.DEFAULT_CONFIG_YAML
    said = re.search(r"Defaults: (.*?)\. Set any", text, re.S).group(1)
    pairs = dict(re.findall(r"(\w+) (\d+)", " ".join(said.split())))
    assert {k: int(v) for k, v in pairs.items()} == config_mod.MAX_TOKENS
