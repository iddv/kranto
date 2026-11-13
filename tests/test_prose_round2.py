"""the acceptance on the live run's recorded answers (``recorded2.json``; no model,
no network): ten items, the owner's five and five more, each written once from each of three
proposed angles. The checker's complaints about round 1 are not tripped by round 2's drafts of
the same items; no draft announces its structure or carries more than one caveat; every first
sentence is a claim, a prediction or a question (the rubric judge's mark); the angle reaches the
opening; nobody's experience is invented; and the outlines are measured. The export and the
read page work from a folder of an outside model's drafts."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from kranto.features.post.evals import export, outline, readpage, round2, writers
from kranto.prose import check
from kranto.prose.checker import (
    ANNOUNCED,
    HEDGE,
    UNKNOWN,
    _body_sentences,
    _content,
    invented_first_person,
)

REC = json.loads((Path(writers.__file__).parent / "recorded2.json").read_text("utf-8"))
DRAFTS = [(iid, r["site"], kind, d) for iid, r in REC["items"].items()
          for kind, d in r["drafts"].items()]
IDS = [f"{iid}-{kind}" for iid, _, kind, _ in DRAFTS]
COMPLAINED = ("claim.announced", "claim.caveats", "claim.no_hook", "claim.sections",
              "claim.skeleton", "claim.restates")


def _check(site: str, text: str, angle: str) -> dict:
    if site == "blog":
        return check(text, "blog", kind="long", take=angle)
    return check(text, "mastodon", kind="short", take=angle,
                 limits={"max_chars": writers.ROOM, "unit": "characters"})


def test_ten_items_three_angles_each_and_the_run_stayed_under_three_dollars():
    assert set(REC["items"]) == {*round2.OWNER_FIVE, *round2.FIVE_MORE}
    for iid, r in REC["items"].items():
        assert [a["kind"] for a in r["angles"]] == ["claim", "prediction", "question"], iid
        assert set(r["drafts"]) == {"claim", "prediction", "question"}, iid
    meta = REC["meta"]
    assert max(meta["cost_usd"], meta["equiv_usd"]) <= 3.0
    assert {run["provider"] for run in meta["runs"]} == {"claude_code"}


def test_angles_are_three_distinct_sentences():
    for iid, r in REC["items"].items():
        texts = [a["text"] for a in r["angles"]]
        assert len({re.sub(r"\W+", " ", t.lower()) for t in texts}) == 3, iid
        assert texts[2].endswith("?"), iid


@pytest.mark.parametrize("iid,site,kind,d", DRAFTS, ids=IDS)
def test_round_2_does_not_trip_what_the_owner_complained_of(iid, site, kind, d):
    rules = {f["rule"] for f in _check(site, d["text"], d["angle"])["flags"]}
    assert not rules & set(COMPLAINED), (iid, kind, sorted(rules))


@pytest.mark.parametrize("iid,site,kind,d", DRAFTS, ids=IDS)
def test_no_announced_structure_and_at_most_one_caveat(iid, site, kind, d):
    first = d["text"].strip().split("\n\n")[0]
    assert not ANNOUNCED.search(first), first
    assert len(HEDGE.findall(d["text"])) + len(UNKNOWN.findall(d["text"])) <= 1


@pytest.mark.parametrize("iid,site,kind,d", DRAFTS, ids=IDS)
def test_the_first_sentence_is_a_claim_a_prediction_or_a_question(iid, site, kind, d):
    assert d["mark"]["first"] in ("claim", "prediction", "question"), d["mark"]


def _stems(text: str) -> set[str]:
    return {w[:-1] if w.endswith("s") and len(w) > 4 else w for w in _content(text)}


@pytest.mark.parametrize("iid,site,kind,d", DRAFTS, ids=IDS)
def test_the_picked_angle_reaches_the_opening(iid, site, kind, d):
    body = _body_sentences(d["text"])
    opening = " ".join(d["text"][s:e] for s, e in body[:2])
    assert len(_stems(d["angle"]) & _stems(opening)) >= 2, (d["angle"], opening)


@pytest.mark.parametrize("iid,site,kind,d", DRAFTS, ids=IDS)
def test_no_invented_experience(iid, site, kind, d):
    assert invented_first_person(d["text"], [d["angle"]]) == []
    assert not d["mark"].get("invented"), d["mark"]


def test_the_outlines_are_measured_and_not_one_shape():
    got = round2.summary(REC)["outline"]
    r2 = got["round2_blog"]
    assert r2["drafts"] >= 20
    assert r2["distinct"] >= r2["drafts"] // 2           # not one template for every post
    assert r2["mean_pair"] < got["round1_old_blog"]["mean_pair"]


def test_the_rubric_judge_was_set_against_the_owners_five():
    checks = {c["post"]: c for c in REC["owner_check"]}
    assert set(checks) == {1, 2, 3, 4, 5}
    assert all(c["judge"] in ("old", "new", "neither", "cant_tell") for c in checks.values())
    assert [checks[n]["owner"] for n in range(1, 6)] == ["neither", "old", "old", "neither",
                                                         "neither"]
    assert sum(c["agrees"] for c in checks.values()) >= 4


def test_an_outline_is_its_blocks():
    text = "## A head\n\nOne.\n\nTwo here. And three. Four.\n\n- a\n- b\n\nWhy?"
    assert outline.outline(text) == ["H", "P1", "P2", "L", "Q"]
    same = outline.sameness(["One.\n\nTwo.", "Uno.\n\nDos."])
    assert same["mean_pair"] == 1.0 and same["identical_share"] == 1.0


# -- the export and the read page, from an outside model's drafts (acceptance 7) -------------


def test_the_export_writes_messages_and_a_plain_prompt(tmp_path):
    angles = {"brief-24-1": {"claim": "Teleop data stops being the moat."}}
    rows = export.export(tmp_path, ["brief-24-1", "brief-19-1"], ("blog",), angles=angles,
                         site_of={"brief-19-1": "toot"})
    assert [r["name"] for r in rows] == ["brief-24-1.blog.claim", "brief-19-1.toot"]
    e = json.loads((tmp_path / "brief-24-1.blog.claim.json").read_text())
    assert e["messages"][0]["role"] == "system" and e["system"].startswith("You write a blog")
    assert "Teleop data stops being the moat." in e["user"]
    assert e["examples"] and e["schema"]["required"] == ["title", "excerpt", "body"]
    txt = (tmp_path / "brief-24-1.blog.claim.txt").read_text()
    assert "=== INSTRUCTIONS ===" in txt and "Answer JSON" not in txt
    assert "Teleop data stops being the moat." in txt and "No JSON" in txt
    index = json.loads((tmp_path / "index.json").read_text())["prompts"]
    assert index[0]["angle"] == "Teleop data stops being the moat."


def test_the_read_page_from_three_outside_writers(tmp_path):
    drafts = tmp_path / "drafts"
    names = ["brief-24-1.blog.claim", "brief-19-1.toot.question"]
    for w in ("gpt", "gemini", "claude"):
        (drafts / w).mkdir(parents=True)
        for n in names:
            (drafts / w / f"{n}.md").write_text(f"# A title by {w}\n\nA body <b>by</b> {w}.\n")
    idx = tmp_path / "index.json"
    idx.write_text(json.dumps({"prompts": [
        {"name": names[0], "site": "blog", "title": "Grasping", "angle": "Bold <one>",
         "angle_kind": "claim"}]}))
    out, key = tmp_path / "read.html", tmp_path / "key.md"
    got = readpage.build(drafts, out, key, index=idx, seed=3)
    assert got == {"posts": 2, "writers": ["claude", "gemini", "gpt"]}
    page = out.read_text()
    for w in ("gpt", "gemini", "claude"):
        assert f"by {w}" in page                       # every draft is on the page...
    assert "Version A" in page and "Version C" in page and "data-writer" not in page
    assert 'value="None"' in page and page.count("<textarea") == 3   # two posts + the manual box
    assert "Copy my answers" in page and "localStorage" in page and "execCommand" in page
    assert "try {" in page and "prefers-color-scheme: dark" in page
    assert "&lt;b&gt;by&lt;/b&gt;" in page and "Bold &lt;one&gt;" in page   # escaped
    k = key.read_text()
    assert names[0] in k and all(w in k for w in ("gpt", "gemini", "claude"))
    # each post has its own order, and the same seed gives the same page
    readpage.build(drafts, tmp_path / "again.html", tmp_path / "again.md", index=idx, seed=3)
    assert (tmp_path / "again.md").read_text().split("\n", 1)[1] == k.split("\n", 1)[1]


def test_the_cli_runs_export_and_read(tmp_path, capsys):
    from kranto.features.post.evals.__main__ import main
    assert main(["export", "--items", "card-158", "--out", str(tmp_path / "x")]) == 0
    (tmp_path / "d" / "other").mkdir(parents=True)
    (tmp_path / "d" / "other" / "card-158.blog.md").write_text("A post.")
    assert main(["read", "--drafts", str(tmp_path / "d"), "--out", str(tmp_path / "r.html"),
                 "--key", str(tmp_path / "k.md"), "--index",
                 str(tmp_path / "x" / "index.json")]) == 0
    assert "1 posts by other" in capsys.readouterr().out
