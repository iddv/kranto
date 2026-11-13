import json

import numpy as np

from kranto import library
from kranto.embed import NOMIC_MODEL_NAME
from kranto.importers import import_parallax


def record(i, **overrides):
    vec = np.zeros(384)
    vec[i % 384] = 2.0
    rec = {
        "id": f"p-{i}", "firehose": "reddit:r/LocalLLaMA", "ts": "2026-05-31T00:00:48.8Z",
        "kind": "mild_signal", "summary": f"summary {i}", "why_it_matters": "why",
        "content_quality": 0.5, "durability": 0.5, "opportunity": 0.8, "tags": ["a"],
        "embedding": vec.tolist(), "embedding_model": "nomic-embed-text-v1.5",
        "source_url": f"https://reddit.com/{i}", "source_excerpt": "ex",
        "data_source": f"firehose-post:{i}",
    }
    rec.update(overrides)
    return json.dumps(rec)


def test_import_parallax_is_idempotent_and_skips_incompatible(tmp_path, store):
    run = tmp_path / "runs" / "r1" / "reddit"
    run.mkdir(parents=True)
    (run / "library.jsonl").write_text("\n".join([
        record(1), record(2), record(3, embedding=[0.1] * 10), record(4, content_quality=None),
        "not json", record(5, embedding_model="other-model"),
    ]) + "\n")
    (run / "costs.jsonl").write_text("{}\n")

    report = import_parallax(store, [tmp_path])
    assert report.files == 1
    assert report.imported == 2
    assert report.skipped == {"no compatible embedding": 2, "missing ratings or text": 1,
                              "unparseable line": 1}
    again = import_parallax(store, [tmp_path])
    assert again.imported == 0 and again.already_present == 2

    row = store.query_one("SELECT * FROM observations WHERE external_id = 'p-1'")
    assert row["embedding_model"] == NOMIC_MODEL_NAME
    assert row["signal"] == 0.5 * 0.5 * 0.8
    assert row["created_at"] == "2026-05-31T00:00:48Z"
    [src] = library.list_sources(store)
    assert src.kind == "parallax" and src.status == "imported"
    assert src.label == "r/LocalLLaMA (Parallax)"
