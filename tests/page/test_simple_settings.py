"""The simple flow's settings: today's keys that do nothing with
``build.flow: simple`` are said, never rewritten and never a reason to refuse a build."""
from kranto.page.settings.schema import check, describe, refuses_builds


def test_keys_of_todays_flow_that_do_nothing_with_the_simple_flow_are_said():
    data = {"build": {"flow": "simple", "auto_repair": 1, "fix_rounds": 3,
                      "models": {"oracle": "claude-haiku-5-5", "verify": "claude-sonnet-5-5"},
                      "stage_caps": {"reverify": 1.0, "repair": 3.0}}}
    probs = check(data)
    assert sorted(p["key"] for p in probs if p["kind"] == "inert") == [
        "build.auto_repair", "build.models.oracle", "build.stage_caps.reverify"]
    # verify and repair map onto check and fix: they still do something
    assert not [p for p in probs if p["kind"] != "inert"]
    line = describe(probs)
    assert "3 keys doing nothing with build.flow: simple: build.auto_repair" in line
    assert refuses_builds(probs) == []
    # today's flow: every key is read
    assert check({"build": {**data["build"], "flow": "v5"}}) == []
    assert check({"build": {"flow": "simple"}}) == []
