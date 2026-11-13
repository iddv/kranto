"""``FakeHost`` refuses what Kranto refuses: every check of the table, the
ticket kinds and broker operations as the core's own, the quotas and the payload limits; the
template's own tests pass against it."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from bears_cub import CapReached, NotConnected, RateLimited, grants, kinds
from bears_cub.errors import HostError
from bears_cub.testing import FakeHost

TEMPLATE = Path(__file__).parent / "fixtures" / "cubs" / "template"   # the starter, as in bearcubs
ECHO = Path(__file__).parent / "fixtures" / "cubs" / "echo"


@pytest.fixture
def host():
    h = FakeHost.from_folder(TEMPLATE)
    h.library.add_topic(id=1, name="Robotics")
    h.library.add_topic(id=2, name="Energy")
    h.library.add_observation(id=10, topic_id=1, title="One", signal=0.9)
    h.library.add_observation(id=20, topic_id=2, title="Two", signal=0.4)
    return h


def code(fn) -> int:
    with pytest.raises(HostError) as e:
        fn()
    return e.value.code


@pytest.mark.parametrize("method,params", [
    ("reads.get", {"name": "ideas.list", "params": {}}),
    ("reads.get", {"name": "briefs.get", "params": {"id": 1}}),
    ("events.read", {"kind": "brief.published"}),
    ("events.ack", {"kind": "brief.published", "last_id": 3}),
    ("events.publish", {"kind": "my_cub.said", "payload": {}}),
    ("model.complete", {"purpose": "other", "tier": "reason", "messages": []}),
    ("model.complete", {"purpose": "my_cub", "tier": "judge", "messages": []}),
    ("model.complete", {"purpose": "my_cub", "tier": "reason", "messages": [],
                        "tools": [{"name": "x"}]}),
    ("model.complete", {"purpose": "my_cub", "tier": "reason", "messages": [],
                        "model": "big"}),
    ("search.run", {"q": "x", "kind": "web"}),
    ("http.fetch", {"url": "https://example.com/"}),
    ("http.fetch", {"url": "http://example.com/"}),
    ("broker.call", {"service": "mastodon", "op": "account.get", "args": {}}),
    ("broker.call", {"service": "newsletter", "op": "emails.create_draft", "args": {}}),
    ("ticket.file", {"kind": "send.newsletter", "fields": {}}),
    ("ticket.file", {"kind": "trade.instruct", "fields": {}}),
])
def test_every_check_of_the_grant_table_is_not_granted(host, method, params):
    assert code(lambda: host.handle(method, params)) == -32001
    assert host.refused[-1]["code"] == -32001


def test_the_shapes_a_method_never_takes(host):
    host.granted["http"] = {"hosts": ["example.com"]}
    for url in ("https://10.0.0.1/", "https://[::1]/", "https://u:p@example.com/",
                "https://example.com:8443/"):
        assert code(lambda u=url: host.handle("http.fetch", {"url": u})) == -32602
    assert grants.check_url("https://api.example.com/x", ["example.com"]) is None
    assert grants.check_url("https://example.com.evil.net/", ["example.com"])[0] == -32001


def test_storage_none_has_no_kv(host):
    host.granted["storage"] = "none"
    assert code(lambda: host.handle("kv.get", {"key": "a"})) == -32001


def test_a_narrowed_cub_sees_its_topics_only(host):
    host.granted["reads_topics"] = [1]
    host.granted["reads"].append("objects")
    topics = host.handle("reads.get", {"name": "topics.list", "params": {}})["topics"]
    assert [t["id"] for t in topics] == [1]
    obs = host.handle("reads.get", {"name": "library.observations", "params": {}})
    assert [o["id"] for o in obs["observations"]] == [10]
    assert code(lambda: host.handle("reads.get", {"name": "library.observations",
                                                  "params": {"topic_id": 2}})) == -32006
    assert code(lambda: host.handle("reads.get", {"name": "objects.get", "params": {
        "kind": "observation", "id": 20}})) == -32006


def test_the_model_cap_and_the_canned_replies(host):
    host.model.reply("my_cub", text="hello")
    msgs = [{"role": "user", "content": "x"}]
    out = host.handle("model.complete", {"purpose": "my_cub", "tier": "reason",
                                         "messages": msgs})
    assert out["text"] == "hello" and out["cost_usd"] > 0
    host.model.spent_usd = 5
    with pytest.raises(CapReached):
        host.handle("model.complete", {"purpose": "my_cub", "tier": "reason",
                                       "messages": msgs})


def test_broker_operations_their_args_credentials_and_windows(host):
    assert host.handle("broker.call", {"service": "mastodon", "op": "statuses.draft",
                                       "args": {"text": "hi"}})["limit"] == 500
    assert code(lambda: host.handle("broker.call", {"service": "mastodon",
                                                    "op": "statuses.draft",
                                                    "args": {"text": "x" * 501}})) == -32005
    assert code(lambda: host.handle("broker.call", {"service": "mastodon",
                                                    "op": "statuses.draft",
                                                    "args": {"text": "hi", "account": "@a"}})
                ) == -32005
    host.granted["broker"]["mastodon"].append("instance.limits")
    with pytest.raises(NotConnected):
        host.handle("broker.call", {"service": "mastodon", "op": "instance.limits",
                                    "args": {}})
    host.broker("mastodon").connected = True
    host.broker("mastodon").max_characters = 1000
    assert host.handle("broker.call", {"service": "mastodon", "op": "instance.limits",
                                       "args": {}})["max_characters"] == 1000
    for _ in range(19):
        host.handle("broker.call", {"service": "mastodon", "op": "statuses.draft",
                                    "args": {"text": "hi"}})
    with pytest.raises(RateLimited):
        host.handle("broker.call", {"service": "mastodon", "op": "statuses.draft",
                                    "args": {"text": "hi"}})


def test_tickets_typed_fields_owned_drafts_duplicates_and_caps(host):
    d = host.handle("broker.call", {"service": "mastodon", "op": "statuses.draft",
                                    "args": {"text": "hi"}})
    fields = {"draft_ref": d["draft_ref"], "text": "hi", "visibility": "public",
              "language": "en"}
    out = host.handle("ticket.file", {"kind": "post.mastodon", "fields": fields})
    assert out["mode"] == "dry" and out["state"] == "needs_confirm"
    dup = code(lambda: host.handle("ticket.file", {"kind": "post.mastodon",
                                                   "fields": fields}))
    assert dup == -32009
    for bad in ({**fields, "account": "@me@x"}, {**fields, "visibility": "direct"},
                {**fields, "draft_ref": "draft:99"}, {**fields, "text": "x" * 501}):
        assert code(lambda b=bad: host.handle("ticket.file", {"kind": "post.mastodon",
                                                              "fields": b})) == -32005
    assert code(lambda: host.handle("ticket.file", {"kind": "post.mastodon",
                                                    "fields": fields,
                                                    "because": {"prose": "trust me"}})
                ) == -32005
    def another(i):
        d = host.handle("broker.call", {"service": "mastodon", "op": "statuses.draft",
                                        "args": {"text": f"hi {i}"}})
        f = {**fields, "draft_ref": d["draft_ref"], "text": f"hi {i}"}
        return host.handle("ticket.file", {"kind": "post.mastodon", "fields": f})

    for i in range(4):                    # five a day: one filed above, four more
        another(i)
    with pytest.raises(RateLimited) as e:
        another(9)
    assert e.value.retry_after_s and len(host.tickets) == 5
    assert code(lambda: host.handle("ticket.get", {"ticket_id": 999})) == -32006


def test_the_key_value_quota(host):
    host.kv_quota_bytes = 300
    host.handle("kv.put", {"key": "a", "value": "x" * 200})
    with pytest.raises(CapReached):
        host.handle("kv.put", {"key": "b", "value": "x" * 200})
    assert code(lambda: host.handle("kv.put", {"key": "bad key", "value": 1})) == -32602
    assert code(lambda: host.handle("kv.put", {"key": "big",
                                               "value": "x" * 70000})) == -32011
    assert code(lambda: host.handle("kv.get", {"key": "nope"})) == -32006


def test_payloads_stay_small_and_dedupe_keys_answer_the_first_id():
    h = FakeHost.from_folder(ECHO)
    assert code(lambda: h.handle("events.publish", {"kind": "echo.said",
                                                    "payload": {"t": "x" * 300}})) == -32005
    first = h.handle("events.publish", {"kind": "echo.said", "payload": {}, "dedupe": "k"})
    again = h.handle("events.publish", {"kind": "echo.said", "payload": {}, "dedupe": "k"})
    assert again == {"event_id": first["event_id"], "duplicate": True}


def test_the_sdks_tables_are_the_cores():
    from kranto.core import api, tickets
    core = tickets.describe_kinds()
    for kind, spec in kinds.TICKETS.items():
        assert [f["key"] for f in core[kind]["fields"]] == list(spec["fields"])
        assert core[kind]["per_day"] == spec["per_day"]
        assert core[kind]["expires_hours"] == spec["expires_hours"]
        for key, (ftype, rules) in spec["fields"].items():
            f = tickets.KINDS[kind].fields[key]
            assert f.type == ftype and tuple(rules.get("choices", ())) == f.choices
            assert rules.get("pattern") == f.pattern
    assert set(kinds.READ_FAMILIES) == set(api.READ_FAMILIES)
    assert set(kinds.READS) - {"grades.mine"} == set(api.V1)


def test_a_folder_whose_entry_misses_a_handler_is_refused(tmp_path):
    (tmp_path / "cub.yaml").write_text((ECHO / "cub.yaml").read_text())
    (tmp_path / "main.py").write_text("from bears_cub import Cub\ncub = Cub()\n")
    from bears_cub.schema import ManifestError
    with pytest.raises(ManifestError, match="handlers missing from the entry file: jobs: tick"):
        FakeHost.from_folder(tmp_path)


def test_the_templates_own_tests_pass_against_fakehost():
    out = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                          str(TEMPLATE / "tests")], capture_output=True, text=True,
                         cwd=TEMPLATE, timeout=120)
    assert out.returncode == 0, out.stdout + out.stderr


def test_kranto_cub_check_says_ok_for_the_template_and_why_not_for_a_broken_one(tmp_path):
    from bears_cub import check
    assert check.problems(TEMPLATE) == [] or all("kranto:" in p for p in check.problems(TEMPLATE))
    (tmp_path / "cub.yaml").write_text("schema: 1\napi: cub/1\nid: x1\n")
    assert check.main([str(tmp_path)]) == 1


DAY_CUB = '''from bears_cub import Cub

cub = Cub()


@cub.job("day")
def day(ctx):
    return {"line": ctx.today(), "summary": {"first": ctx.once(ctx.today())}}
'''


def test_a_cubs_day_is_the_hosts(tmp_path):
    """``ctx.now()`` runs on the host's clock (``hello.now``), so FakeHost's advance() moves a
    cub's today() and once() keys, and a cub on Kranto counts days by Kranto's clock."""
    from datetime import UTC, datetime
    (tmp_path / "cub.yaml").write_text(
        "schema: 1\napi: cub/1\nid: clock\nversion: 1.0.0\ntitle: Clock\nsays: Says the day.\n"
        "jobs: [{kind: clock.day, method: day, every_hours: 24}]\nstorage: own\n")
    (tmp_path / "main.py").write_text(DAY_CUB)
    h = FakeHost.from_folder(tmp_path, now=datetime(2026, 1, 31, 23, 0, tzinfo=UTC))
    first = h.run_job("day", strict=True)
    assert first["line"] == "2026-01-31" and first["summary"] == {"first": True}
    assert h.run_job("day", strict=True)["summary"] == {"first": False}
    h.advance(hours=2)
    assert h.run_job("day", strict=True) == {"status": "ok", "line": "2026-02-01",
                                              "summary": {"first": True}}


def test_a_trade_or_a_perform_op_is_refused_as_kranto_refuses_it(tmp_path):
    import shutil
    folder = tmp_path / "t"
    shutil.copytree(TEMPLATE, folder)
    text = (folder / "cub.yaml").read_text()
    assert "mastodon: [statuses.draft]" in text
    (folder / "cub.yaml").write_text(text.replace("mastodon: [statuses.draft]",
                                                  "newsletter: [emails.send]"))
    with pytest.raises(Exception, match="no such operation a cub may be granted: emails.send"):
        FakeHost.from_folder(folder)
