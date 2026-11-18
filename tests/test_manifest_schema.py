"""The manifest's one validator against its JSON Schema: the reference cubs'
``cub.yaml`` and every first-party ``to_manifest()`` validate against ``cub.schema.json`` with
``jsonschema`` (a dev dependency only: what ships is ``core.manifest.validate``, which interprets
the same file), and every refusal rule of has a case."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest
import yaml

from kranto.core import api, events, manifest, registry, tickets
from kranto.core.manifest import (
    SCHEMA_FILE,
    Feature,
    ManifestError,
    check_requirements,
    grants_of,
    in_range,
    manifest_hash,
    version_key,
)

FIXTURES = Path(__file__).parent / "fixtures" / "cub_manifests"
OPS = {"newsletter": {"emails.create_draft", "emails.get", "drafts.list", "newsletter.get"},
       "mastodon": {"statuses.draft", "drafts.list", "account.get", "instance.limits"}}


def example(name: str) -> dict:
    return yaml.safe_load((FIXTURES / f"{name}.yaml").read_text())


def check(m: dict, **kw) -> dict:
    args = dict(read_families=api.READ_FAMILIES, request_kinds=tickets.kind_names(),
                core_kinds=events.CORE_KINDS, search_kinds=("web", "discussion", "code",
                                                            "papers"),
                source="cub", broker_ops=OPS)
    args.update(kw)
    return manifest.validate(m, **args)


@pytest.mark.parametrize("name", ["newsletter", "toot"])
def test_the_reference_cubs_validate_against_the_json_schema_and_the_validator(name):
    raw = example(name)
    jsonschema.validate(raw, json.loads(SCHEMA_FILE.read_text()))
    before = manifest_hash(raw)
    m = check(copy.deepcopy(raw))
    assert m["id"] == name and m["actions"][0]["click"] == "click"   # defaults filled
    assert m["actions"][0]["place"] == "card" and m["storage"] == "own"
    assert manifest_hash(raw) == before                              # the file's hash, unfilled


def test_every_first_party_manifest_validates_against_the_schema_widened_for_features():
    schema = manifest._schema("feature")
    for f in registry.features():
        jsonschema.validate(f.to_manifest(), schema)
    assert {m["id"] for m in registry.check()} == {"news"}


def test_the_shipped_schema_is_the_design_file():
    notes = Path(__file__).resolve().parents[2] / "" / "plans" / "cld" / \
        "cub.schema.json"
    if notes.exists():                       # a checkout beside (CI has none)
        assert json.loads(notes.read_text()) == json.loads(SCHEMA_FILE.read_text())


def _mut(path: str, value):
    """A change at a dotted path (an int is a list index; ``+`` appends)."""
    def change(m):
        node, parts = m, path.split(".")
        for p in parts[:-1]:
            node = node[int(p)] if p.isdigit() else node[p]
        last = parts[-1]
        if last == "+":
            node.append(value)
        elif last.isdigit():
            node[int(last)] = value
        else:
            node[last] = value
    return change


def _drop(path: str):
    def change(m):
        node, parts = m, path.split(".")
        for p in parts[:-1]:
            node = node[int(p)] if p.isdigit() else node[p]
        del node[parts[-1]]
    return change


REFUSALS = [
    # 1: an unknown key anywhere
    (_mut("shell", True), "unknown keys in the manifest: shell"),
    (_mut("jobs.0.cron", "* * * * *"), r"unknown keys in jobs\[0\]: cron"),
    (_mut("ui.tile.colour", "red"), "unknown keys in ui.tile"),
    (_mut("events.subscribe.0.handler", "x"), "unknown keys in events.subscribe"),
    # 2: schema, api, id
    (_mut("schema", 2), "manifest schema 2 needs a newer Kranto"),
    (_mut("api", "cub/2"), "this cub speaks cub/2; this Kranto speaks cub/1"),
    (_mut("id", "News"), "id: 'News' is not of the expected shape"),
    (_mut("id", "llm"), "reserved word"),
    (_mut("id", "news"), "reserved word"),
    (_mut("id", "enabled"), "reserved word"),
    (_drop("says"), "the manifest needs says"),
    # 3: version
    (_mut("version", "1.0"), "version: '1.0' is not of the expected shape"),
    # 4: first-party-only keys
    (_mut("trust", "first-party"), "Kranto's own"),
    (_mut("trust", "core"), "Kranto's own"),
    (_mut("owns", ["newsletter_rows"]), "owns no tables"),
    (_mut("ui.pages", ["NewsPage"]), "ships no page code"),
    (_mut("ui.keys", {"g x": "newsletter"}), "no keyboard key"),
    (_mut("actions.0.place", "head"), "page's head"),
    (_mut("actions.0.click", "house"), "house confirm is the core's"),
    (_mut("actions.0.doors", ["ui", "mcp"]), "never mcp"),
    (_mut("prompts", [{"id": "x"}]), "prompts are its own files"),
    # 5: paths inside the folder
    (_mut("entry", "../main.py"), "not of the expected shape"),
    (_mut("entry", "lib/../../x.py"), "inside the cub's folder"),
    (_mut("entry", "/abs/main.py"), "not of the expected shape"),
    (_mut("requirements", "deps/../../r.txt"), "inside the cub's folder"),
    (_mut("docs.page", "../README.md"), "inside the cub's folder"),
    # 6: a grant the core cannot give
    (_mut("reads", ["secrets"]), r"reads\[0\] is one of"),
    (_mut("requests", ["send.pigeon"]), "no such high-trust action"),
    (_mut("broker", {"newsletter": ["emails.send"]}), "no such operation a cub may be granted"),
    (_mut("broker", {"money": ["quote.get"]}), "no money operations"),
    (_mut("search", ["dark"]), r"search\[0\] is one of"),
    (_mut("model.tiers", ["oracle"]), r"model.tiers\[0\] is one of"),
    (_mut("model.purposes", ["intro"]), "must be newsletter or start with newsletter_"),
    (_mut("events.publish", ["ticket.filed"]), "is the core's"),
    (_mut("events.publish", ["brief.published"]), "a cub's kinds start with newsletter."),
    (_mut("http.hosts", ["127.0.0.1"]), "not of the expected shape"),
    (_mut("http.hosts", ["*.example.com"]), "not of the expected shape"),
    (_mut("http.hosts", ["github.io"]), "shared by many sites"),
    (_mut("http.hosts", ["example.com", "pages.dev"]), "shared by many sites"),
    (_mut("http.hosts", ["co.uk"]), "shared by many sites"),
    # 7: an undeclared cross-reference
    (_mut("jobs.0.when", "newsletter.nope"), "not one of its true-or-false settings"),
    (_mut("jobs.0.when", "newsletter.intro"), "not one of its true-or-false settings"),
    (_mut("jobs.0.purpose", "newsletter_other"), "is not one of its model.purposes"),
    (_mut("jobs.0.on", ["brief.drafted"]), "which it does not subscribe to"),
    (_mut("ui.forms.0.submit", "newsletter.nope"), "submit names one of its actions"),
    (_mut("ui.today_rows.0.primary", "post.mastodon"), "primary"),
    (_mut("ui.today_rows.0.read", "nope"), "is not one of its reads"),
    (_mut("ui.cards.issue.actions", ["newsletter.nope"]), "no action"),
    (_mut("ui.lists.0.read", "nope"), "is not one of its reads"),
    (_mut("ui.lists.0.card", "nope"), "no card"),
    (_mut("ui.lists.0.count", "nope"), "names one of its groups"),
    (_mut("ui.tile.count", "nope"), "is not one of its reads"),
    (_mut("actions.0.fields.0.read", "nope"), "is not one of its reads"),
    (lambda m: m["settings"]["keys"].update({"Newsletter.x": {"type": "bool"}}),
     "unknown keys in settings.keys: Newsletter.x"),
    (lambda m: m["settings"]["keys"].update({"other.x": {"type": "bool"}}),
     "must start with newsletter."),
    (_mut("settings.sensitive", ["newsletter.nope"]), "listed but not declared"),
    # 8: limits
    (_mut("title", "x" * 81), "at most 80 characters"),
    (_mut("provides", [f"r{i}" for i in range(21)]), "holds at most 20"),
    (_mut("jobs.0.deadline_s", 3601), "at most 3600"),
    (_mut("jobs.0.at", "25:00"), "not of the expected shape"),
    (_mut("jobs.0.days", ["monday"]), "is one of mon"),
    (lambda m: m["settings"]["keys"]["newsletter.max_items"].update(default=99),
     "its default does not fit"),
    # a key's place on its Settings page; Settings' pages are not cub ids
    (lambda m: m["settings"]["keys"]["newsletter.max_items"].update(group="x" * 25),
     "at most 24 characters"),
    (lambda m: m["settings"]["keys"]["newsletter.max_items"].update(advanced="yes"),
     "advanced"),
    (_mut("id", "appearance"), "a page of Settings"),
    (_mut("id", "features"), "reserved word"),
    # The page's keys
    (lambda m: m["ui"]["lists"][0]["groups"][0].update(tone="loud"), "is one of"),
    (lambda m: m["ui"]["lists"][0].update(empty="x" * 161), "at most 160 characters"),
    (lambda m: m["ui"]["cards"]["issue"].update(open="page"), "open: page needs body"),
    (lambda m: m["ui"]["cards"]["issue"].update(open="window"), "is one of"),
    (_mut("ui.primary", "nope"), "is not one of its forms"),
]


@pytest.mark.parametrize("change,words", REFUSALS)
def test_every_refusal_rule_names_the_key(change, words):
    m = example("newsletter")
    change(m)
    with pytest.raises(ManifestError, match=words):
        check(m)


def test_a_kind_only_kranto_may_ask_for_is_refused_to_a_cub(monkeypatch):
    tickets.kind_names()
    own = tickets.Kind("publish.own", "Publish as Kranto",
                       {"what": tickets.Field("str", label="What")}, first_party_only=True)
    monkeypatch.setitem(tickets.KINDS, "publish.own", own)
    m = example("newsletter")
    m["requests"] = ["publish.own"]
    with pytest.raises(ManifestError, match="Kranto's own"):
        check(m)


def test_a_path_must_be_in_the_tree_when_the_tree_is_known():
    files = {"cub.yaml", "README.md"}
    with pytest.raises(ManifestError, match="main.py is not in the cub's folder"):
        check(example("newsletter"), files=files)
    assert check(example("newsletter"), files=files | {"main.py"})["id"] == "newsletter"


def test_a_kind_another_installed_cub_publishes_is_refused():
    with pytest.raises(ManifestError, match="published by toot"):
        check(example("newsletter"), published={"newsletter.drafted": "toot"})
    assert check(example("newsletter"), published={"newsletter.drafted": "newsletter"})


def test_a_secret_shaped_setting_default_is_refused():
    m = example("newsletter")
    token = "ghp_" + "A1b2C3d4" * 5
    m["settings"]["keys"]["newsletter.subject_prefix"]["default"] = token
    with pytest.raises(ManifestError, match="shaped like a key"):
        check(m)


STAGE = {"id": "check", "title": "Licence check", "at": "after_build", "kind": "code",
         "entry": "stage_check.py", "tree": "rw", "writes": ["**/*.py"], "gives": ["findings",
                                                                                  "patch"]}


@pytest.mark.parametrize("change,words", [
    ({"at": "before_publish"}, "nothing edits it after Check"),
    ({"tree": "ro"}, "gives a patch, so it needs tree: rw"),
    ({"writes": []}, "needs writes"),
    ({"requests": ["send.pigeon"]}, "no such high-trust action"),
    ({"kind": "session", "entry": None}, "needs its prompt file"),
    ({"entry": None}, "needs its entry file"),
    ({"entry": "x/../../x.py"}, "inside the cub's folder"),
    ({"model": {"role": "oracle"}}, r"role is one of"),
    ({"model": {"tier": "reason", "max_usd": 3}}, "over the cub's"),
    ({"hold_at": "high"}, "hold_at needs on_fail: hold"),
    ({"at": "after_brief", "reads": ["findings"], "tree": "ro", "gives": ["findings"],
      "writes": []}, "no findings yet"),
    ({"when": {"traits": ["mobile"]}}, "is one of web"),
    ({"settings": ["newsletter.nope"]}, "is not one of its settings"),
    ({"needs": ["later"]}, "which runs later"),
])
def test_the_stage_block_rules(change, words):
    m = example("newsletter")
    later = {**STAGE, "id": "later", "at": "before_check", "tree": "ro", "gives": ["findings"],
             "writes": []}
    m["stages"] = [{**STAGE, **change}, later]
    with pytest.raises(ManifestError, match=words):
        check(m)


def test_a_stage_that_follows_the_rules_validates():
    m = example("newsletter")
    m["stages"] = [STAGE]
    out = check(m)
    assert out["stages"][0]["on_fail"] == "warn" and out["stages"][0]["cap"]["timeout_s"] == 600
    assert grants_of(out)["stages"] == ["check"]


def test_requirements_are_exact_pins_with_hashes():
    h = "a" * 64
    assert check_requirements(f"attrs==24.2.0 --hash=sha256:{h}\n# a comment\n\n") == \
        [f"attrs==24.2.0 --hash=sha256:{h}"]
    assert check_requirements(f"attrs==24.2.0 \\\n    --hash=sha256:{h}\n")
    for bad in ("attrs>=24", "attrs==24.2.0", "https://x.example/a.whl", "-e ./pkg",
                f"attrs==24.2.0 --hash=md5:{h[:32]}", "./local"):
        with pytest.raises(ManifestError, match="not name==version"):
            check_requirements(bad)
    with pytest.raises(ManifestError, match="at most 50 lines"):
        check_requirements("\n".join(f"a{i}==1 --hash=sha256:{h}" for i in range(51)))


def test_versions_and_ranges():
    assert version_key("0.5.0rc1") < version_key("0.5.0") < version_key("0.5.1")
    assert version_key("0.5.1.dev3+g1a2b") < version_key("0.5.1")
    assert in_range("0.5.0", ">=0.5,<0.7") and in_range("0.6.9", ">=0.5,<0.7")
    assert not in_range("0.7.0", ">=0.5,<0.7") and not in_range("0.4.9", ">=0.5,<0.7")
    assert not in_range("0.5.0rc1", ">=0.5")            # a pre-release is before its release
    assert in_range("0.5.0", "==0.5.0") and in_range("1.0.0", "")


class FakeRunner:
    def __init__(self):
        self.made = []

    def job(self, kind, method):
        self.made.append(("job", kind, method))
        return lambda ctx: {"status": "ok"}

    def action(self, kind, method):
        self.made.append(("action", kind, method))
        return lambda ctx, fields: {}

    def read(self, name):
        self.made.append(("read", name))
        return lambda ctx, params: {"count": 0}

    def deliver(self, kind, method):
        self.made.append(("deliver", kind, method))
        return lambda ctx, ev: None

    def mode(self, ctx):
        return "dry run"


def test_an_installed_cub_becomes_a_feature_whose_code_is_its_runner():
    m = check(example("newsletter"))
    runner = FakeRunner()
    grants = grants_of(m)
    grants["reads_topics"] = [1]
    f = Feature.from_manifest(m, runner, trust="owner", grants=grants)
    assert f.id == "newsletter" and f.trust == "owner" and f.permissions.reads == ("topics",
                                                                                  "briefs")
    assert [j.kind for j in f.jobs] == ["newsletter.weekly"] and f.jobs[0].at == "08:00"
    assert f.jobs[0].days == ("mon",) and f.jobs[0].method == "compose"
    assert ("job", "newsletter.weekly", "compose") in runner.made
    assert ("action", "newsletter.compose", "compose_now") in runner.made
    assert ("deliver", "ticket.resolved", "on_resolved") in runner.made
    assert sorted(f.api) == ["brief_choices", "count", "issues", "rows"]
    pull = next(s for s in f.events.subscribes if s.kind == "brief.published")
    assert pull.handler is None and pull.min_trust == "first-party"
    assert f.permissions.broker == {"newsletter": ("emails.create_draft", "emails.get",
                                                   "drafts.list")}
    assert f.mode(None) == "dry run" and f.ui.tile.count == "count"
    assert f.to_manifest()["trust"] == "owner" and f.to_manifest()["jobs"][0]["at"] == "08:00"
    assert f.settings.keys["newsletter.max_items"].hi == 30
