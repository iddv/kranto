"""service.memory: the owner asked the console to raise Kranto's memory and it
edited the systemd drop-in by hand, for want of a setting. The setting writes Kranto's own
drop-in, reloads and applies it to the running service at once, shows the use beside it, and
is refused anywhere but inside Kranto's own service (a scratch copy never touches the real one)."""
from types import SimpleNamespace

import pytest

from kranto import memory as M
from kranto.core import verbs

G = 1 << 30


def test_the_caps_for_a_max_and_the_default_from_the_machine():
    assert M.caps_for_gb(5) == (4 * G, 5 * G)            # the owner's 4G/5G
    high, cap = M.caps_for_gb(2)
    assert cap == 2 * G and high == cap - cap // 5 - (cap - cap // 5) % M.MiB
    assert M.default_caps(16 * G) == (3 * G, 4 * G)


def test_it_is_written_reloaded_and_applied_at_once(tmp_path):
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    out = M.set_service_memory(5, user_home=tmp_path, unit="kranto.service", run=run, here=True)
    p = M.dropin_path(tmp_path, "kranto.service")
    assert p == tmp_path / ".config/systemd/user/kranto.service.d/30-memory.conf"
    assert M.DROPIN_MARK in p.read_text()
    assert M.read_dropin(p) == (4 * G, 5 * G) and out == {"high_mb": 4096, "max_mb": 5120}
    assert calls == [["systemctl", "--user", "daemon-reload"],
                     ["systemctl", "--user", "set-property", "--runtime", "kranto.service",
                      "MemoryHigh=4096M", "MemoryMax=5120M"]]
    shown = M.service_memory(tmp_path, "kranto.service")
    assert shown["setting"] == 5.0 and not shown["by_hand"] and shown["dropin_max_mb"] == 5120
    # auto: the drop-in goes, the unit's own lines (from this machine's memory) apply
    M.set_service_memory(None, user_home=tmp_path, unit="kranto.service", run=run, here=True)
    assert not p.exists() and M.service_memory(tmp_path, "kranto.service")["setting"] == "auto"
    hi, cap = M.default_caps()
    assert calls[-1][-2:] == [f"MemoryHigh={hi // M.MiB}M", f"MemoryMax={cap // M.MiB}M"]


def test_a_hand_written_drop_in_is_read_and_said_so(tmp_path):
    p = M.dropin_path(tmp_path, "kranto.service")
    p.parent.mkdir(parents=True)
    p.write_text("[Service]\n# raised by hand\nMemoryHigh=4G\nMemoryMax=5G\n")
    shown = M.service_memory(tmp_path, "kranto.service")
    assert shown["setting"] == 5.0 and shown["by_hand"]


def test_refused_outside_the_service_and_out_of_range(tmp_path):
    def run(argv, **kw):
        raise AssertionError("nothing is run")
    with pytest.raises(M.ServiceMemoryError, match="not running as kranto.service"):
        M.set_service_memory(5, user_home=tmp_path, unit="kranto.service", run=run, here=False)
    for bad in (0.5, 65, 2.3):
        with pytest.raises(M.ServiceMemoryError, match="from 1 to 64 GB"):
            M.set_service_memory(bad, user_home=tmp_path, unit="kranto.service", run=run,
                                 here=True)
    assert not M.dropin_path(tmp_path, "kranto.service").exists()


def test_a_failed_reload_says_it_was_written_not_applied(tmp_path):
    def run(argv, **kw):
        return SimpleNamespace(returncode=1, stdout="", stderr="Failed to connect to bus")
    with pytest.raises(M.ServiceMemoryError, match="not applied: daemon-reload said Failed"):
        M.set_service_memory(3, user_home=tmp_path, unit="kranto.service", run=run, here=True)


def test_it_is_a_verb_and_its_route_refuses_outside_the_service(tmp_path, store, embedder,
                                                                 make_client, monkeypatch):
    from kranto.config import ApiConfig, BudgetConfig, Config, IngestConfig, MapConfig
    from kranto.runtime import open_runtime
    from kranto.web.app import create_app

    from .conftest import llm_config, web_client
    monkeypatch.setenv("HOME", str(tmp_path / "user"))
    # a test run from the console runs inside kranto.service's group: never the real unit
    monkeypatch.setattr(M, "in_service", lambda unit=None: False)
    (tmp_path / "kranto.yaml").write_text("llm:\n  models:\n    judge: m\n    reason: m\n")
    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=10),
                 ingest=IngestConfig(), map=MapConfig(), api=ApiConfig())
    app = create_app(open_runtime(cfg, store=store, embedder=embedder,
                                  llm=make_client(lambda b: None)), port=8765)
    v = verbs.get("settings.service_memory")
    assert v is not None and v.path == "/api/settings/service" and v.ladder == "reversible"
    with web_client(app, "http://127.0.0.1:8765") as web:
        got = web.get("/api/settings/service").json()["memory"]
        assert {"setting", "used_mb", "ram_mb", "default_max_mb", "applies"} <= set(got)
        r = web.post("/api/settings/service", json={"memory": 5})
        assert r.status_code == 409 and "not running as" in r.json()["error"]
        assert web.post("/api/settings/service", json={"memory": "lots"}).status_code == 400
    assert not (tmp_path / "user" / ".config" / "systemd").exists()
