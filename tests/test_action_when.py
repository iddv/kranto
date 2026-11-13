"""An action's ``when`` (UIBUGS B1,): a head offers a verb only while the setting it names is
on, so no head holds a button that can only refuse. Checked at load like a job's ``when``."""

from dataclasses import replace

import pytest

from bears_cub.schema import ManifestError
from kranto import features as features_pkg
from kranto.core import registry
from kranto.features.news import FEATURE as NEWS


def test_no_head_verb_of_a_feature_that_can_be_off_is_offered_while_it_is():
    for m in registry.check():
        on = next((k for k, s in (m.get("settings") or {}).get("keys", {}).items()
                   if k.endswith(".enabled") and s.get("type") == "bool"), None)
        for a in m["actions"]:
            if a["place"] == "head" and on and not a["kind"].endswith((".stop", ".resume")):
                assert a.get("when") == on, f"{a['kind']} is offered while {on} is off"
    acts = {a["kind"]: a for m in registry.check() for a in m["actions"]}
    # an action without one carries no key: every other manifest hashes as it did
    assert "when" not in acts["news.toggle"]


@pytest.mark.parametrize("when", ["news.depth", "news.nope"])
def test_a_when_must_name_one_of_its_own_switches(monkeypatch, when):
    first = NEWS.actions[0].kind
    acts = tuple(replace(a, when=when) if a.kind == first else a for a in NEWS.actions)
    monkeypatch.setattr(features_pkg, "FEATURES", tuple(
        replace(NEWS, actions=acts) if f.id == "news" else f for f in features_pkg.FEATURES))
    with pytest.raises(ManifestError, match="not one of its true-or-false settings"):
        registry.check()
