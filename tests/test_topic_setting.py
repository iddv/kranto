"""Which topics, picked, never typed: a setting of type ``topics`` is a list of
topic ids the core's picker draws on any feature's or cub's generated Settings page; an id
written as digits (the newsletter's older ``list`` value) still reads; the newsletter cub 1.2.0
declares its topics so."""

from pathlib import Path

import pytest

from bears_cub.testing import FakeHost
from kranto.core import manifest as manifest_mod
from kranto.core import settings
from kranto.core.manifest import Setting

NEWSLETTER = Path(__file__).resolve().parents[1] / "src/kranto/cubs/examples/newsletter"


def test_a_topics_value_is_a_list_of_topic_ids():
    rule = Setting("topics", [])
    assert settings.check("x.topics", rule, [4, "3", 4]) == [3, 4]
    assert settings.check("x.topics", rule, []) == []
    for bad in (["robotics"], [0], [True], "3", [3.5], list(range(1, 202))):
        with pytest.raises(settings.SettingError, match="list of topic ids"):
            settings.check("x.topics", rule, bad)


def test_the_newsletter_picks_its_topics_and_its_older_value_still_reads():
    import yaml
    raw = yaml.safe_load((NEWSLETTER / "cub.yaml").read_text())
    # topics since 1.2.0; prose 1.5.0; outlets 1.5.1; the check's sources 1.5.2
    assert raw["version"] == "1.5.2"
    assert raw["settings"]["keys"]["newsletter.topics"]["type"] == "topics"
    assert "topics" in manifest_mod.SETTING_TYPES
    host = FakeHost.from_folder(NEWSLETTER)              # the SDK checks it against the schema
    assert host.settings["newsletter.topics"] == []
    rule = Setting("topics", [])
    assert settings.check("newsletter.topics", rule, ["2", 13]) == [2, 13]


def test_settings_describe_says_the_type_the_picker_draws():
    feature = type("F", (), {"settings": manifest_mod.Settings(
        keys={"demo.topics": Setting("topics", [], words="the topics it reads")})})()
    [row] = settings.describe(feature, {"demo.topics": [2]})
    assert (row["type"], row["value"], row["default"]) == ("topics", [2], [])
