"""The cub's tests, against bears_cub's FakeHost (no Kranto, no network, no model)."""

from pathlib import Path

import pytest

from bears_cub import CapReached, NotGranted
from bears_cub.testing import PLANTED, FakeHost

HERE = Path(__file__).resolve().parents[1]


@pytest.fixture
def host():
    h = FakeHost.from_folder(HERE)
    h.library.add_topic(id=1, name="Robotics")
    h.library.add_observation(id=10, topic_id=1, title="A humanoid charges in nine minutes",
                              signal=0.9)
    h.model.reply("my_cub", text="Nine minutes to charge a humanoid: shifts get longer.")
    return h


def test_the_job_drafts_and_files_one_ticket_with_its_fields(host):
    out = host.run_job("weekly")
    assert out["status"] == "ok"
    [t] = host.tickets
    assert t["kind"] == "post.mastodon" and t["because"] == {"observations": [10]}
    assert t["fields"]["text"] == host.drafts[0]["content"]["text"]
    assert host.read("count") == {"count": 1}


def test_the_planted_instruction_changes_nothing(host):
    host.fixtures.planted_instruction()
    host.model.reply("my_cub", fn=lambda messages, schema: messages[-1]["content"])
    host.run_job("weekly")
    assert len(host.tickets) == 1
    assert "evil@example.com" not in str(host.tickets[0]["because"])
    assert host.tickets[0]["kind"] == "post.mastodon"


def test_a_grant_it_lacks_raises_not_granted(host):
    with pytest.raises(NotGranted):
        host.handle("reads.get", {"name": "ideas.list", "params": {}})


def test_the_cap_stops_the_model_call(host):
    host.model.spent_usd = 1.0
    out = host.run_job("weekly")
    assert out["status"] == "failed" and "CapReached" in out["error"]
    assert host.tickets == [] and host.refused[-1]["code"] == CapReached("").code


def test_a_second_run_finds_nothing_new(host):
    host.run_job("weekly")
    assert host.run_job("weekly")["status"] == "skipped"
    assert len(host.tickets) == 1


def test_a_duplicate_ticket_is_reported_not_raised(host):
    host.run_job("weekly")
    t = host.tickets[0]
    from bears_cub.context import Context
    ctx = Context(host.handle, cub_id=host.cub_id, version=host.version,
                  hello=host._hello("r"))
    again = ctx.ticket("post.mastodon", t["fields"])
    assert again.duplicate and again.ticket_id == t["id"]


def test_dry_mode_sends_nothing(host):
    host.run_job("weekly")
    t = host.resolve(host.tickets[0]["id"], "dry")
    assert t["state"] == "dry" and host.mode["post.mastodon"] == "dry"
    assert host.read("posts")["done"][0]["state"] == "dry"
    host.assert_no_secret_asked()


def test_the_widget_draws_at_each_size_it_declares(host):
    assert host.widget("waiting", "S") == {"value": "0", "words": "posts wait for you"}
    host.run_job("weekly")
    got = host.widget("waiting", "M")
    assert got["value"] == "1" and got["words"] == "post waits for you"
    assert got["facts"] == [{"label": "Newest", "value": host.today()}]


def test_planted_text_is_the_fixture(host):
    assert "SYSTEM" in PLANTED
