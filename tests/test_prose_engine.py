""" acceptance 2, 3, 5 (the migration) and 6: revise keeps unflagged text byte for byte;
compose builds the messages from the floor, the guides, the voice card, the site's template,
the 3 closest samples and the take; ``blog.tone: plain`` in an old file becomes the voice
card's first line; learn proposes and changes nothing without a yes."""

from __future__ import annotations

import json

import pytest

from kranto import config as config_mod
from kranto.embed import StubEmbedder
from kranto.prose import check, compose, learn, learner, profile, revise
from kranto.prose.profile import Profile, Sample

DRAFT = ("The city approved forty kilometres of bike lanes on Monday, highlighting its growing "
         "commitment to safer streets. Work starts in April on the ring road.\n\n"
         "Here's the thing: the plan leaves out the old town. The council will delve into that "
         "in May. https://example.org/plan stays the source.")


def _home(tmp_path, yaml_text: str = ""):
    (tmp_path / "kranto.yaml").write_text(config_mod.DEFAULT_CONFIG_YAML + "\n" + yaml_text,
                                         encoding="utf-8")
    return config_mod.load(tmp_path, dotenv=False)


# -- revise -------------------------------------------------------------------------------------


def _model(answer):
    calls = []

    def complete(messages, schema):
        calls.append(messages)
        return answer(messages) if callable(answer) else answer
    complete.calls = calls
    return complete


def test_revise_changes_only_the_flagged_spans_byte_for_byte():
    flags = check(DRAFT)["flags"]
    spans = [(f["start"], f["end"]) for f in flags if f["scope"] == "span"]
    assert len(spans) >= 3
    # the model answers a replacement for every span, numbered as sent
    model = _model(lambda m: {"structured": {"edits": [
        {"id": i, "text": f"<{i}>"} for i in range(1, m[1]["content"].count("\n\n") + 2)]}})
    out = revise(DRAFT, flags, complete=model, rounds=1)
    assert out["rounds"] == 1 and out["changed"]
    # everything outside the spans is the input's, in order, byte for byte
    kept, pos = [], 0
    for s, e in sorted(spans):
        if s >= pos:
            kept.append(DRAFT[pos:s])
            pos = e
    kept.append(DRAFT[pos:])
    rest = out["text"]
    for piece in kept:
        i = rest.find(piece)
        assert i >= 0, piece
        rest = rest[i + len(piece):]
    # a replacement that brings in an address the text did not hold is refused
    sneaky = _model({"structured": {"edits": [{"id": 1, "text": "see https://evil.example"}]}})
    assert "evil" not in revise(DRAFT, flags, complete=sneaky, rounds=1)["text"]


def test_revise_cuts_a_span_without_leaving_a_double_space_and_stops_after_two_rounds():
    text = "The fix ships today. Let that sink in."
    flags = check(text)["flags"]
    model = _model({"structured": {"edits": [{"id": 1, "text": ""}]}})
    out = revise(text, flags, complete=model)
    assert out["text"] == "The fix ships today.." or out["text"].startswith("The fix ships today")
    assert "  " not in out["text"]
    stubborn = _model({"text": json.dumps({"edits": [{"id": 1, "text": "Here's the thing:"}]})})
    out = revise("Here's the thing: it works.", check("Here's the thing: it works.")["flags"],
                 complete=stubborn)
    assert out["rounds"] <= 2 and out["flags"]          # what remains is kept, and said


def test_an_unbacked_first_person_sentence_is_cut_by_code_when_the_model_keeps_it():
    from kranto.prose.reviser import enforce_voice
    text = "The plant opened in May. I think it will fail. Output is 40 units a day."
    stubborn = _model({"structured": {"edits": [{"id": 1, "text": "I believe it will fail."}]}})
    out = revise(text, check(text, take="")["flags"], complete=stubborn, take="")
    assert out["text"] == "The plant opened in May. Output is 40 units a day."
    assert not any(f["rule"] == "voice.invented_i" for f in out["flags"])
    # backed by the take, it stays; with no take given it is not judged
    assert enforce_voice(text, None, "I think it will fail.")[0] == text
    assert enforce_voice(text, None, None)[0] == text
    assert enforce_voice("I tried it. It works well.", None, "")[0] == "It works well."


def test_revise_with_no_span_flags_makes_no_call():
    model = _model({"structured": {"edits": []}})
    out = revise("A plain sentence.", [], complete=model)
    assert out == {**out, "text": "A plain sentence.", "rounds": 0} and model.calls == []


# -- compose ------------------------------------------------------------------------------------


def test_compose_puts_in_every_part():
    samples = tuple(Sample(f"s{i}", text, site) for i, (text, site) in enumerate([
        ("Bike lanes went in on my street. Quieter mornings, fewer close calls.", "mastodon"),
        ("A recipe for sourdough that takes three days and one jar.", None),
        ("The tram line opened late again; I walked.", "mastodon"),
        ("Notes on a long hike in the Alps with too little water.", None),
        ("Parking fees doubled downtown; cycling numbers rose a third.", "blog"),
    ]))
    p = Profile(voice="Tone: plain.\nShort sentences. Dry.", samples=samples,
                always=("Sign off with: — R.",))
    msgs = compose({"take": "Good, but late.", "title": "Bike lanes approved",
                    "facts": "[1] Council: 40 km of lanes approved Monday.",
                    "format": "Answer JSON with text."},
                   "mastodon", p, task="Write one Mastodon post.", embedder=StubEmbedder(),
                   limits={"max_chars": 500}, features="Content warning when sensitive.")
    system = msgs[0]["content"]
    assert msgs[0]["role"] == "system" and system.startswith("Write one Mastodon post.")
    assert "# The floor" in system and "# Plain words" in system
    assert "# A Mastodon post" in system                       # the site's template
    assert "Tone: plain." in system                             # the voice card
    assert "Sign off with" in system and "max_chars: 500" in system
    assert "Content warning when sensitive." in system          # SOCIAL's feature rules
    assert "# The angle" in system and "never invent an experience" in system  # P-9, P-10
    shots = msgs[1]["content"]
    assert msgs[1]["role"] == "user" and msgs[2]["role"] == "assistant"
    assert shots.count("<example") == 3                          # the 3 closest samples
    user = msgs[-1]["content"]
    assert "Good, but late." in user and "40 km" in user and "<<<" in user
    assert user.index("Good, but late.") < user.index("40 km")  # the take first


def test_compose_without_samples_or_take_says_no_invented_opinion():
    msgs = compose({"facts": "[1] a fact"}, "blog")
    assert len(msgs) == 2
    assert "no opinion, feeling or experience given as theirs" in msgs[0]["content"]
    assert "# A blog post" in msgs[0]["content"]


def test_the_closest_samples_are_picked_by_embedding():
    samples = tuple(Sample(f"s{i}", f"text number {i} about {w}", None)
                    for i, w in enumerate(["cats", "trams", "bikes", "soup", "bike lanes"]))
    p = Profile(samples=samples)
    picked = profile.closest(p, "bike lanes", None, StubEmbedder(), n=3)
    assert len(picked) == 3 and len({s.id for s in picked}) == 3


# -- the profile's storage and the tone migration -----------------------------------------------


def test_an_old_tone_setting_becomes_the_voice_cards_first_line(tmp_path, store):
    cfg = _home(tmp_path, "blog:\n  tone: plain\n")
    p = profile.load(cfg, store)
    assert p.voice.splitlines()[0] == "Tone: plain."
    assert (tmp_path / "prose" / "voice.md").read_text().startswith("Tone: plain.")
    row = profile.load_row(store)
    assert row.migrated == {"blog.tone": "plain"} and row.migrated_at
    # once: an edit of the card is never undone by the migration
    profile.change(cfg, store, {"voice": "Dry, short."})
    assert profile.load(cfg, store).voice == "Dry, short."


def test_different_tones_are_kept_each(tmp_path, store):
    cfg = _home(tmp_path, "blog:\n  tone: dry\ntoot:\n  tone: playful\n")
    first = profile.load(cfg, store).voice.splitlines()[0]
    assert first == "Tone: on the blog, dry; on mastodon, playful."


def test_no_tone_written_means_an_empty_card(tmp_path, store):
    assert profile.load(_home(tmp_path), store).voice == ""


def test_a_malformed_row_reads_as_the_default(tmp_path, store):
    store.set_setting("prose.profile", json.dumps({"switches": None, "strictness": 7,
                                                   "rules_off": None, "guides": None,
                                                   "take": None, "migrated_at": "x"}))
    p = profile.load(_home(tmp_path), store)
    assert p.switches["length"] == "medium" and p.strictness == "light" and p.take


def test_change_checks_and_writes(tmp_path, store):
    cfg = _home(tmp_path)
    out = profile.change(cfg, store, {
        "switches": {"length": "short", "grade": 6}, "strictness": "strict",
        "rules_off": ["shape.tricolon"], "never_add": ["synergy", "/\\bcircle back\\b/"],
        "keep_add": ["for what it's worth"], "always_add": ["— R."],
        "samples_add": [{"text": "A sample long enough to be one, about trams.",
                         "site": "mastodon"}],
        "disclosure": {"mastodon": profile.DISCLOSURE_LINE},
        "guides": {"blog": ["plain"]}, "take": False})
    assert out["ok"] and "the voice card" not in out["changed"]
    p = profile.load(cfg, store)
    assert p.switches["length"] == "short" and p.switches["grade"] == 6
    assert p.strictness == "strict" and p.rules_off == ("shape.tricolon",)
    assert p.never == ("synergy", "/\\bcircle back\\b/") and p.keep == ("for what it's worth",)
    assert p.samples[0].site == "mastodon" and p.disclosure["mastodon"]
    assert p.guides_for("blog") == ("floor", "plain") and not p.take
    for bad in ({"switches": {"length": "huge"}}, {"strictness": "max"}, {"rules_off": ["x"]},
                {"never_add": ["/[/"]}, {"samples_add": [{"text": "short"}]}, {"nope": 1}, {},
                {"guides": {"blog": ["no-such-guide"]}}):
        with pytest.raises(profile.ProfileError):
            profile.change(cfg, store, bad)
    profile.change(cfg, store, {"samples_remove": [p.samples[0].id], "never_remove": ["synergy"]})
    p = profile.load(cfg, store)
    assert p.samples == () and p.never == ("/\\bcircle back\\b/",)


def test_a_persons_guide_replaces_kranto_template(tmp_path, store):
    cfg = _home(tmp_path)
    (tmp_path / "prose" / "guides" / "sites").mkdir(parents=True)
    (tmp_path / "prose" / "guides" / "sites" / "mastodon.md").write_text("# Mine\n\nTwo lines.")
    msgs = compose({"facts": "x"}, "mastodon", profile.load(cfg, store))
    assert "# Mine" in msgs[0]["content"] and "# A Mastodon post" not in msgs[0]["content"]


# -- learn --------------------------------------------------------------------------------------


def test_learn_proposes_from_a_diff_and_changes_nothing(tmp_path, store):
    cfg = _home(tmp_path)
    draft = "This game-changer ships today. It is a seamless update for everyone."
    sent = "This update ships today. It works for everyone, and it is robust."
    props = learn(draft, sent)
    kinds = {(pr["kind"], pr["entry"].lower()) for pr in props}
    assert ("never", "game-changer") in kinds and ("never", "seamless") in kinds
    assert ("keep", "robust") in kinds                   # added on purpose, though flagged
    assert profile.load(cfg, store).never == ()          # nothing changed


def test_observe_then_yes_through_answer(tmp_path, store):
    cfg = _home(tmp_path)
    p = profile.load(cfg, store)
    new = learner.observe(store, p, "A pivotal week.", "A busy week.")
    assert [pr["entry"] for pr in new] == ["pivotal"]
    assert profile.load(cfg, store).never == ()
    out = learner.answer(cfg, store, new[0]["id"], True)
    assert out["answer"] == "yes" and profile.load(cfg, store).never == ("pivotal",)
    # answered: never asked again, and the no is remembered too
    assert learner.observe(store, profile.load(cfg, store), "A pivotal week.", "A week.") == []
    second = learner.observe(store, p, "It was crucial.", "It mattered.")
    learner.answer(cfg, store, second[0]["id"], False)
    assert learner.load(store).answered[second[0]["id"]] == "no"
    with pytest.raises(learner.LearnError):
        learner.answer(cfg, store, "nope", True)


def test_a_word_cut_twice_and_a_phrase_added_twice(tmp_path, store):
    p = profile.load(_home(tmp_path), store)
    assert learner.observe(store, p, "The basically fine plan.", "The fine plan.") == []
    twice = learner.observe(store, p, "A basically good idea.", "A good idea, for what it's "
                                                                 "worth.")
    entries = {(pr["kind"], pr["entry"]) for pr in twice}
    assert ("never", "basically") in entries
    again = learner.observe(store, p, "Fine.", "Fine, for what it's worth.")
    assert ("voice", "for what it's worth") in {(pr["kind"], pr["entry"]) for pr in again}


def test_over_the_limit_is_one_shorter_rewrite_then_fits_at_a_sentence():
    from kranto.prose.reviser import fit
    long = "The council approved forty kilometres of bike lanes on Monday. " * 6
    flags = check(long, "bluesky")["flags"]
    assert any(f["rule"] == "site.length" for f in flags)
    model = _model({"structured": {"text": "The council approved 40 km of bike lanes."}})
    out = revise(long, flags, complete=model, site="bluesky")
    assert out["text"] == "The council approved 40 km of bike lanes." and out["rounds"] >= 1
    assert "Shorten this post to at most 300 characters" in model.calls[0][0]["content"]
    # the fallback never cuts mid-word
    assert fit("One fact here. Another fact that runs on and on.", 30) == "One fact here."
    assert fit("a" * 10 + " " + "b" * 40, 30).endswith("…")
    assert fit("short", 30) == "short"
