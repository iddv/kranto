"""The default kranto.yaml (``DEFAULT_CONFIG_YAML``) is the config reference: every key the
loader reads is named in it, as a key or in a comment, and what it sets is the default."""
from __future__ import annotations

import dataclasses
import re
import typing

import yaml

from kranto import config as config_mod

INTERNAL = {"root", "home"}        # set by Kranto, not by a person


def fields(cls, path=""):
    hints = typing.get_type_hints(cls)
    for f in dataclasses.fields(cls):
        if f.name in INTERNAL:
            continue
        yield (f"{path}.{f.name}" if path else f.name), f.name
        t = hints.get(f.name)
        for sub in [a for a in typing.get_args(t) if dataclasses.is_dataclass(a)] or \
                ([t] if dataclasses.is_dataclass(t) else []):
            yield from fields(sub, f"{path}.{f.name}" if path else f.name)


def test_every_config_key_is_named_in_the_default_config():
    text = config_mod.DEFAULT_CONFIG_YAML
    missing = [p for p, name in fields(config_mod.Config)
               if not re.search(rf"\b{re.escape(name)}\b", text)]
    assert missing == []


def test_the_default_config_sets_the_defaults(tmp_path):
    config_mod.init_workspace(tmp_path)
    cfg = config_mod.load(tmp_path, dotenv=False)
    assert cfg.update == config_mod.UpdateConfig()
    assert cfg.api == config_mod.ApiConfig()
    assert yaml.safe_load(config_mod.DEFAULT_CONFIG_YAML)["update"]["auto"] == "off"
