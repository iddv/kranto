import numpy as np
import pytest

from kranto import cli, search
from kranto import config as config_mod
from kranto.embed import StubEmbedder
from kranto.runtime import open_runtime
from kranto.search import Hit, Index
from kranto.store import Store, vec_to_blob


def _unit(*values: float) -> np.ndarray:
    vec = np.zeros(4, dtype=np.float32)
    vec[: len(values)] = values
    return vec / np.linalg.norm(vec)


def _obs(store: Store, summary: str, vec: np.ndarray, *, model: str = "m",
         supersedes: int | None = None, title: str | None = None, tags: str = "[]") -> int:
    return store.insert("observations", dict(
        kind="beat", title=title, summary=summary, why_it_matters="it matters",
        content_quality=0.5, durability=0.5, opportunity=0.5, signal=0.125, tags=tags,
        embedding=vec_to_blob(vec), embedding_model=model, supersedes=supersedes,
        created_at="2026-09-26T00:00:00Z"))


def test_match_expression_quotes_each_word_and_drops_stopwords():
    assert search.match_expression("What is the CRDT for collaborative-editing?") == \
        '"crdt" OR "collaborative" OR "editing"'
    assert search.match_expression('drop "table" -- x; x') == '"drop" OR "table" OR "x"'
    assert search.match_expression("the of and") is None
    assert search.match_expression("") is None
    many = " ".join(f"w{i}" for i in range(50))
    assert search.match_expression(many).count(" OR ") == search.MAX_TERMS - 1


def test_lexical_agreement_lifts_a_result_above_the_closest_by_cosine(store):
    close = _obs(store, "grid batteries in general", _unit(1.0, 0.05))
    worded = _obs(store, "Sycophancy in assistants", _unit(1.0, 0.3))
    _obs(store, "unrelated", _unit(0.0, 0.0, 1.0))
    index = Index(store, "m")
    query = _unit(1.0)
    assert [h.observation_id for h in index.nearest(query, 2)] == [close, worded]
    hits = index.fused(query, "sycophancy", 2)
    assert [h.observation_id for h in hits] == [worded, close]
    # The score shown is still the cosine similarity, not the fused rank.
    assert hits[0].score == pytest.approx(float(_unit(1.0, 0.3) @ query))


def test_stemming_matches_other_forms_of_a_word(store):
    target = _obs(store, "Speculative decoding speeds up generation", _unit(0.0, 1.0))
    _obs(store, "something else", _unit(1.0))
    index = Index(store, "m")
    assert index.lexical("decode speedup", 5) == [index._position[target]]


def test_title_and_tags_are_searchable(store):
    titled = _obs(store, "s", _unit(1.0), title="Conflict-Free Replicated Data Types")
    tagged = _obs(store, "s", _unit(0.0, 1.0), tags='["local_first", "sync"]')
    index = Index(store, "m")
    assert [int(index.ids[p]) for p in index.lexical("replicated", 5)] == [titled]
    assert [int(index.ids[p]) for p in index.lexical("local first", 5)] == [tagged]


def test_superseded_and_other_model_rows_are_not_returned(store):
    old = _obs(store, "microgrid tariffs", _unit(1.0))
    new = _obs(store, "microgrid tariffs, corrected", _unit(1.0), supersedes=old)
    _obs(store, "microgrid tariffs elsewhere", _unit(1.0), model="other")
    index = Index(store, "m")
    assert [int(index.ids[p]) for p in index.lexical("microgrid", 10)] == [new]
    assert [h.observation_id for h in index.fused(_unit(1.0), "microgrid", 10)] == [new]


def test_rows_added_after_the_index_loaded_are_found(store):
    index = Index(store, "m")
    assert index.fused(_unit(1.0), "anything", 5) == []
    added = _obs(store, "a heat pump subsidy", _unit(1.0))
    assert [h.observation_id for h in index.fused(_unit(1.0), "heat pump", 5)] == [added]


def test_a_query_with_no_searchable_words_falls_back_to_the_embedding(store):
    first = _obs(store, "one", _unit(1.0))
    second = _obs(store, "two", _unit(0.6, 0.8))
    hits = Index(store, "m").fused(_unit(1.0), "the of", 5)
    assert [h.observation_id for h in hits] == [first, second]


def test_off_topic_is_judged_on_the_closest_hit_and_shown_rounded_down():
    below = [Hit(1, 0.6499, True), Hit(2, 0.61, True)]
    assert search.off_topic(below)
    assert not search.off_topic([Hit(2, 0.61, True), Hit(1, 0.65, False)])
    assert not search.off_topic([])
    assert search.floor2(0.6999) == 0.69 and search.floor2(0.6499) == 0.64
    assert f"{search.floor2(0.6499):.2f}" != f"{search.OFF_TOPIC_BELOW:.2f}"


def test_cutoff_keeps_results_close_to_the_best():
    hits = [Hit(1, 0.70, False), Hit(2, 0.78, False), Hit(3, 0.63, True), Hit(4, 0.62, True)]
    kept = search.within_cutoff(hits)
    assert [h.observation_id for h in kept] == [1, 2, 3]
    assert search.within_cutoff([]) == []


def test_cli_search_says_when_the_library_may_not_cover_a_query(tmp_path, capsys):
    kb = tmp_path / "kb"
    assert cli.main(["init", str(kb)]) == 0
    embedder = StubEmbedder()

    def factory(config: config_mod.Config):
        return open_runtime(config, embedder=embedder)

    rt = factory(config_mod.load(kb))
    text = "solar microgrid battery storage for rural kenya"
    _obs(rt.store, text, embedder.embed_documents([text])[0], model=embedder.model_name)
    rt.close()
    run = ["-w", str(kb), "search"]
    assert cli.main([*run, text], runtime_factory=factory) == 0
    out = capsys.readouterr().out
    assert "may not cover" not in out and "solar microgrid" in out
    assert cli.main([*run, "knitting patterns"], runtime_factory=factory) == 0
    out = capsys.readouterr().out
    assert "the library may not cover this" in out and "below 0.65" in out
