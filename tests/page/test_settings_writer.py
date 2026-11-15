"""The settings writer: a ``{key, value}`` checked by ``settings.write.RULES`` and
written into loop.yaml, keeping the owner's comments; the rest of loop.yaml is set in the file on
purpose (commands, paths, credentials, the network allow-lists). Since the factory left (CUT) the
page writes only the console's keys through it (``POST api/term/settings``: test_page_api.py)."""
import pytest
import yaml

from kranto.page import paths
from kranto.page.settings import store
from kranto.page.settings import write as W


def at(d, key):
    for k in key.split("."):
        d = d[k]
    return d


def test_every_rule_is_a_key_kranto_reads_and_its_default_passes_its_check():
    for key, rule in W.RULES.items():
        if rule[0] in ("path", "policy"):   # a folder on this machine; no build pipeline (CUT)
            continue
        assert W.checked(rule, key, at(store.DEFAULTS, key)) == at(store.DEFAULTS, key) \
            or rule[0] == "float", key


@pytest.mark.parametrize("key", [
    "build.command", "build.revise_command", "publish.gh_command",
    "maintain.gh_command", "maintain.token_env_file", "maintain.net_hosts", "term.net_hosts",
    "kranto.db", "ideas.editor.command", "nudge.path",
    "chat.factory_repos", "capabilities.kranto_mod.kind"])
def test_what_is_set_by_hand_on_purpose_is_never_written_from_a_request(key):
    with pytest.raises(ValueError, match="set it in loop.yaml|only removed here"):
        W.check(key, "x")


def test_a_build_pipeline_is_never_written():
    with pytest.raises(ValueError, match="builds are not part of Kranto"):
        W.check("build.policy", "v5")
    assert W.policies() == []


def test_a_term_value_is_checked_and_written_keeping_the_owners_comments(tmp_path):
    f = paths.LoopLayout(tmp_path).settings
    f.write_text("# the owner's note\nterm:\n  idle_min: 30\n")
    for key, good, bad in (("term.enabled", False, "maybe"), ("term.daily_usd", "12", 0),
                           ("term.allow_api_key", True, "yes")):
        W.write(f, tuple(key.split(".")), W.check(key, good))
        with pytest.raises(ValueError, match=key.replace(".", r"\.")):
            W.check(key, bad)
    assert f.read_text().startswith("# the owner's note")
    data = yaml.safe_load(f.read_text())["term"]
    assert data == {"idle_min": 30, "enabled": False, "daily_usd": 12.0, "allow_api_key": True}
    W.write(f, ("term", "daily_usd"), W.UNSET)
    assert "daily_usd" not in yaml.safe_load(f.read_text())["term"]
    assert store.Config(tmp_path)["term"]["daily_usd"] is None        # back to the default


def test_the_rules_say_how_each_term_key_is_edited():
    assert W.rule_view(W.RULES["term.enabled"]) == {"kind": "enum",
                                                     "choices": [None, True, False],
                                                     "empty": True}
    assert W.rule_view(W.RULES["term.daily_usd"])["kind"] == "usd"
    assert W.rule_view(W.RULES["term.allow_api_key"]) == {"kind": "bool", "empty": False}
