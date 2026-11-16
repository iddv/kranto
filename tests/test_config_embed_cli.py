from pathlib import Path

import numpy as np
import pytest

from kranto import cli
from kranto import config as config_mod
from kranto.embed import NomicEmbedder, StubEmbedder


def test_init_then_load_defaults(tmp_path):
    config_mod.init_workspace(tmp_path / "kb")
    cfg = config_mod.load(tmp_path / "kb")
    assert cfg.llm.models["judge"]
    assert cfg.llm.cost_source == "provider"
    # the gate goes with the default judge, Haiku 5.5 (2026-10-08 calibration)
    assert cfg.llm.models["judge"] == "anthropic/claude-haiku-5.5"
    assert cfg.ingest.signal_threshold == pytest.approx(0.03)
    assert cfg.db_path.parent.is_dir()


def test_init_refuses_to_overwrite(tmp_path):
    config_mod.init_workspace(tmp_path)
    with pytest.raises(config_mod.ConfigError):
        config_mod.init_workspace(tmp_path)


def test_unknown_keys_are_rejected(tmp_path):
    config_mod.init_workspace(tmp_path)
    path = tmp_path / config_mod.CONFIG_FILENAME
    path.write_text(path.read_text() + "\ningest:\n  typo_key: 1\n")
    with pytest.raises(config_mod.ConfigError):
        config_mod.load(tmp_path)


def test_dotenv_in_workspace_is_loaded_without_overriding(tmp_path, monkeypatch):
    config_mod.init_workspace(tmp_path)
    (tmp_path / ".env").write_text('# comment\nexport AFK_T1="from-file"\nAFK_T2=file\n')
    monkeypatch.delenv("AFK_T1", raising=False)
    monkeypatch.setenv("AFK_T2", "from-shell")
    config_mod.load(tmp_path)
    import os

    assert os.environ["AFK_T1"] == "from-file"
    assert os.environ["AFK_T2"] == "from-shell"
    monkeypatch.delenv("AFK_T1")


def test_missing_workspace_has_helpful_error(tmp_path, monkeypatch):
    monkeypatch.delenv(config_mod.WORKSPACE_ENV, raising=False)
    with pytest.raises(config_mod.ConfigError, match="python -m kranto init"):
        config_mod.find_workspace(str(tmp_path))


def test_stub_embedder_geometry(embedder):
    vecs = embedder.embed_documents(
        ["solar microgrid financing in kenya", "kenya solar microgrid pay as you go", "crdt sync"]
    )
    assert vecs.shape == (3, 384)
    assert np.allclose(np.linalg.norm(vecs, axis=1), 1.0, atol=1e-5)
    assert vecs[0] @ vecs[1] > vecs[0] @ vecs[2]
    assert np.allclose(embedder.embed_query("crdt sync"), vecs[2])


def test_stub_embedder_is_deterministic():
    a = StubEmbedder().embed_documents(["same text"])
    b = StubEmbedder().embed_documents(["same text"])
    assert np.array_equal(a, b)


@pytest.mark.slow
def test_nomic_embedder_prefixes_and_truncation():
    e = NomicEmbedder()
    docs = e.embed_documents(["Solar home systems sold on pay-as-you-go plans in Kenya"])
    query = e.embed_query("pay as you go solar")
    assert docs.shape == (1, 384)
    assert abs(float(np.linalg.norm(query)) - 1.0) < 1e-4
    assert float(docs[0] @ query) > 0.6


def test_cli_init_status_pause_resume(tmp_path, capsys):
    kb = tmp_path / "kb"
    assert cli.main(["init", str(kb)]) == 0
    out = capsys.readouterr().out
    assert f"responsible use: {cli.RESPONSIBLE_USE_URL}" in out.splitlines()
    assert cli.RESPONSIBLE_USE_URL.endswith("/RESPONSIBLE_USE.md")
    assert (Path(__file__).parents[1] / "RESPONSIBLE_USE.md").is_file()
    assert cli.main(["-w", str(kb), "pause", "trip"]) == 0
    assert cli.main(["-w", str(kb), "status"]) == 0
    assert "paused:       trip" in capsys.readouterr().out
    assert cli.main(["-w", str(kb), "resume"]) == 0
    assert cli.main(["-w", str(kb), "status"]) == 0
    assert "paused:       no" in capsys.readouterr().out


def test_cli_reports_missing_workspace(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv(config_mod.WORKSPACE_ENV, raising=False)
    assert cli.main(["-w", str(tmp_path / "nope"), "status"]) == 2
    assert "not a workspace" in capsys.readouterr().err
