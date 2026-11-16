"""The newsletter cub against FakeHost (the twelve)."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from bears_cub import NotGranted
from bears_cub.testing import FakeHost

HERE = Path(__file__).resolve().parent.parent
MONDAY = datetime(2026, 10, 19, 8, 0, tzinfo=UTC)
INTRO = "Two things moved this week. Both are below, from the briefs."


def item(n: int, topic: int = 1) -> dict:
    return {"headline": f"Headline {topic}.{n}", "body": f"Body sentence {topic}.{n}.",
            "why": f"Why it matters {topic}.{n}.",
            "sources": [{"label": f"obs {n}", "url": f"https://example.com/{topic}/{n}"}]}


@pytest.fixture
def host() -> FakeHost:
    h = FakeHost.from_folder(HERE, now=MONDAY)
    h.library.add_topic(1, "Robotics")
    h.library.add_topic(2, "Energy")
    h.model.reply("newsletter_intro", text=INTRO)
    return h


def two_briefs(h: FakeHost) -> None:
    h.library.add_brief(41, 1, [item(1), item(2)])
    h.library.add_brief(42, 2, [item(1, 2)])


def test_no_briefs_skips(host):
    out = host.run_job("compose", strict=True)
    assert out["status"] == "skipped" and not host.tickets and not host.drafts


def test_two_briefs_file_one_ticket_with_the_drafts_subject_and_both_briefs(host):
    two_briefs(host)
    out = host.run_job("compose", strict=True)
    assert out["status"] == "ok" and out["summary"]["items"] == 3
    [t] = host.tickets
    [d] = host.drafts
    assert t["kind"] == "send.newsletter" and t["fields"]["subject"] == d["content"]["subject"]
    assert t["fields"]["draft_ref"] == d["ref"] and t["fields"]["audience"] == "all"
    assert t["fields"]["when"] == "now"
    assert sorted(t["because"]["briefs"]) == [41, 42]
    assert [e["kind"] for e in host.events.published] == ["newsletter.drafted"]


def test_every_line_of_the_body_is_a_briefs_or_the_intro(host):
    """the eval as a test: the cub adds nothing but the intro."""
    two_briefs(host)
    host.run_job("compose", strict=True)
    body = host.drafts[0]["content"]["body"]
    allowed = {INTRO}
    for b in host.library.briefs:
        for it in b["items"]:
            allowed |= {it["body"], f"*Why it matters:* {it['why']}"}
            allowed.add(f"**{it['headline']}** ({it['date']})")
            # a source's link words are its site, never the material's label
            allowed.add(" · ".join(f"[example.com]({s['url']})" for s in it["sources"]))
    assert "[obs " not in body
    lines = [x for x in body.splitlines() if x.strip()]
    assert lines and all(x in allowed for x in lines), [x for x in lines if x not in allowed]


def test_the_planted_instruction_is_only_a_cited_item_and_files_nothing_else(host):
    planted = host.fixtures.planted_instruction(topic_id=1)
    host.model.reply("newsletter_intro", fn=lambda messages, schema: messages[-1]["content"])
    out = host.run_job("compose", strict=True)
    assert out["status"] == "ok" and len(host.tickets) == 1
    t = host.tickets[0]
    assert t["kind"] == "send.newsletter" and set(t["fields"]) == {"draft_ref", "subject",
                                                                    "audience", "when"}
    assert planted not in t["fields"]["subject"]
    body = host.drafts[0]["content"]["body"]
    assert planted in body                            # as the brief's item, verbatim
    # the headlines reach the model fenced as data, through the prose engine
    assert "<<<sources" in host.model.calls[0]["messages"][-1]["content"]
    assert host.prose.calls[0]["method"] == "compose"
    host.assert_no_secret_asked()


def test_the_intros_check_gets_the_headlines_it_was_written_from(host):
    """salt.person: the check's sources are the headlines, so a person they lack is flagged."""
    two_briefs(host)
    host.run_job("compose", strict=True)
    check = next(c for c in host.prose.calls if c["method"] == "check")
    assert "Headline 1.1" in check["params"]["sources"]
    assert "Headline 2.1" in check["params"]["sources"]


def test_a_second_run_the_same_day_skips(host):
    two_briefs(host)
    host.run_job("compose", strict=True)
    out = host.run_job("compose", strict=True)
    assert out["status"] == "skipped" and len(host.tickets) == 1


def test_compose_now_with_one_brief_uses_that_brief(host):
    two_briefs(host)
    out = host.act("compose_now", {"briefs": ["42"]}, strict=True)
    assert out["ok"] and "waits for Send" in out["say"]
    [t] = host.tickets
    assert t["because"]["briefs"] == [42]
    assert "Headline 2.1" in host.drafts[0]["content"]["body"]
    assert "Headline 1.1" not in host.drafts[0]["content"]["body"]


def test_redraft_withdraws_the_first_ticket_and_files_a_second(host):
    two_briefs(host)
    host.run_job("compose", strict=True)
    first = host.tickets[0]
    out = host.act("redraft", {"intro": "warm"}, subject={"kind": "newsletter_issue",
                                                          "id": first["fields"]["draft_ref"]},
                   strict=True)
    assert out["ok"] and len(host.tickets) == 2
    assert host.tickets[0]["state"] == "expired" and host.tickets[1]["state"] == "needs_confirm"
    rows = host.read("issues")
    assert [r["state"] for r in rows["closed"]] == ["closed"] and len(rows["waiting"]) == 1


@pytest.mark.parametrize("state, row_state, group", [("done", "sent", "sent"),
                                                     ("dry", "practiced", "practiced"),
                                                     ("declined", "closed", "closed")])
def test_on_resolved_moves_the_row(host, state, row_state, group):
    two_briefs(host)
    host.run_job("compose", strict=True)
    host.resolve(host.tickets[0]["id"], state)
    issues = host.read("issues")
    assert [r["state"] for r in issues[group]] == [row_state] and not issues["waiting"]


def test_issues_rows_and_count_agree(host):
    two_briefs(host)
    host.run_job("compose", strict=True)
    host.act("compose_now", {"briefs": ["41"], "subject": "A special issue"}, strict=True)
    issues, rows, count = host.read("issues"), host.read("rows"), host.read("count")
    # Kranto 0.6: an issue is one series, so the newer draft replaces the waiting one, which is
    # closed with "replaced by #2" and can still be read
    assert count == {"count": 1} == {"count": len(rows["rows"])}
    assert {r["id"] for r in rows["rows"]} == {r["id"] for r in issues["waiting"]}
    assert [r["title"] for r in rows["rows"]] == ["A special issue"]
    assert host.tickets[0]["state"] == "expired" and host.tickets[0]["note"] == "replaced by #2"
    assert [r["state"] for r in issues["closed"]] == ["closed"]
    assert host.read("brief_choices")["choices"][0]["value"] == "42"


def test_an_undeclared_purpose_is_not_granted(host):
    """A mutation: the manifest without the purpose; the SDK refuses before the pipe."""
    two_briefs(host)
    host.granted["model"]["purposes"] = []
    out = host.run_job("compose")
    assert out["status"] == "failed" and NotGranted.__name__ in out["error"]
    assert not host.model.calls and not host.tickets


def test_the_cap_stops_the_intro_and_the_job_fails_with_why(host):
    two_briefs(host)
    host.model.spent_usd = 2.0                     # the manifest's $2 a month, spent
    out = host.run_job("compose")
    assert out["status"] == "failed" and "of its $2.00 this month" in out["error"]
    assert not host.tickets
    host.model.spent_usd = 0.0                     # the next month, or a raised cap: the
    assert host.run_job("compose", strict=True)["status"] == "ok"   # same day composes
    assert len(host.tickets) == 1


def test_not_connected_the_draft_is_in_kranto_and_the_ticket_still_files(host):
    two_briefs(host)
    assert host.broker("newsletter").connected is False
    host.run_job("compose", strict=True)
    assert host.drafts[0]["ref"].startswith("draft:") and len(host.tickets) == 1
    assert host.read("rows")["rows"][0]["meta"].endswith("draft in kranto")


def test_send_at_a_time_of_day_files_the_next_one(host):
    two_briefs(host)
    host.settings["newsletter.send_at"] = "09:30"
    host.run_job("compose", strict=True)
    assert host.tickets[0]["fields"]["when"] == "2026-10-19T09:30:00Z"
    host.settings["newsletter.send_at"] = "08:15"      # within half an hour: tomorrow's
    host.act("compose_now", {"briefs": ["41"]}, strict=True)
    assert host.tickets[1]["fields"]["when"] == "2026-10-20T08:15:00Z"


def test_a_scheduled_send_reads_as_scheduled(host):
    two_briefs(host)
    host.run_job("compose", strict=True)
    host.resolve(host.tickets[0]["id"], "done", note="scheduled: b1 for 2026-10-20T09:30:00Z")
    assert [r["state"] for r in host.read("issues")["sent"]] == ["scheduled"]


def test_an_earlier_versions_dry_run_reads_as_practiced_never_sent(host):
    """1.3.1 kept a practiced issue as "dry run" and listed it with the sent ones (the owner on
    2026-10-29 took live's issue of 27 Oct for sent); 1.4.0 reads it as practiced."""
    two_briefs(host)
    host.run_job("compose", strict=True)
    ref = host.tickets[0]["fields"]["draft_ref"]
    host.resolve(host.tickets[0]["id"], "dry")
    host.kv[f"issue:{ref}"] = {**host.kv[f"issue:{ref}"], "state": "dry run"}
    issues = host.read("issues")
    assert [r["state"] for r in issues["practiced"]] == ["practiced"] and not issues["sent"]
