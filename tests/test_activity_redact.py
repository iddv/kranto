"""No secret in any trace: secret shapes, built at run time, put in a run's
title, words, waiting words, error and detail never reach a mark row, the mirror file or
``/api/activity``. Nothing touches a model or the network."""

from __future__ import annotations

import json
import random

import pytest

from kranto import activity
from kranto.activity import read as activity_read
from kranto.store import Store

# built at run time from a seeded generator: a written-out fake key is still a literal that
# secret scanners flag (tests/test_no_secrets.py)
_RNG = random.Random("test_activity_redact")


def _hex(n: int) -> str:
    return _RNG.randbytes(n).hex()


SECRETS = ["sk-or-v1-" + _hex(16), "sk-ant-" + "api03-" + _hex(15), "AKIA" + _hex(8).upper(),
           "ghp_" + "a" * 36, "xai-" + _hex(30), "jane.doe+work@example.com"]


@pytest.fixture(autouse=True)
def _writers_stopped():
    yield
    activity.shutdown()


@pytest.fixture
def fstore(tmp_path):
    s = Store.open(tmp_path / "data" / "kranto.db")
    yield s
    activity.shutdown()
    s.close()


def everything(store) -> str:
    activity.settle(store, 5)
    rows = [dict(r) for r in store.query("SELECT * FROM run_marks")]
    mirror = activity.mirror_path(store)
    return json.dumps(rows) + (mirror.read_text() if mirror and mirror.exists() else "")


@pytest.mark.parametrize("secret", SECRETS)
def test_a_secret_in_any_word_a_run_carries_is_scrubbed_at_write(fstore, secret):
    with pytest.raises(RuntimeError), activity.run(
            fstore, "scout", title=f"Scouting with {secret}",
            subject=("topic", 1, f"Robotics {secret}")) as r:
        r.progress(f"asking with key {secret}", detail={"header": f"Bearer {secret}"})
        r.waiting(f"waits for {secret}", {"verb": "Review", "href": f"#/x?k={secret}",
                                          "words": secret})
        activity.writer_for(fstore).flush(5)
        live = activity_read.Reader(fstore).read()
        assert secret not in json.dumps(live)
        assert secret not in everything(fstore)
        raise RuntimeError(f"the provider said: invalid key {secret}")
    activity.flush(5)
    assert secret not in everything(fstore)
    out = activity_read.Reader(fstore).read()
    one = activity_read.Reader(fstore).one(r.uuid)
    assert secret not in json.dumps(out) and secret not in json.dumps(one)


def test_a_detail_past_its_size_is_replaced_never_kept(store):
    with activity.run(store, "ingest") as r:
        r.progress("big", detail={"blob": "x" * 5000})
        activity.writer_for(store).flush(5)
    [m] = [dict(x) for x in store.query("SELECT detail FROM run_marks WHERE mark = 'progress'")]
    assert len(m["detail"]) < 200 and "over 2000 bytes" in m["detail"]
    assert r.uuid
