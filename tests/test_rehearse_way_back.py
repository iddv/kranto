"""The way-back rehearsal's shims: they refuse every unit but the rehearsal's own and its update
helper's, never reach the real systemd, and run the allowed unit from its ExecStart and
Environment= lines. Nothing here touches a real unit; the one process started is a sleep."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from kranto import legacy, product

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "release" / "rehearse_way_back.py"
UNIT = f"{product.COMMAND}-rehearsal.service"


@pytest.fixture
def rw():
    spec = importlib.util.spec_from_file_location("rehearse_way_back", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["rehearse_way_back"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def sdir(tmp_path):
    d = tmp_path / "shim"
    for n in ("shim", "state", "journal", "run", "home/.config/systemd/user"):
        (tmp_path / n).mkdir(parents=True, exist_ok=True)
    stem = UNIT.removesuffix(".service")
    (d / "shim.json").write_text(json.dumps({
        "sdir": str(d), "home": str(tmp_path / "home"), "user": "someone",
        "state": str(tmp_path / "state"), "journal": str(tmp_path / "journal"),
        "run": str(tmp_path / "run"), "log": str(tmp_path / "shim.log"),
        "units": [UNIT, f"{stem}-update", f"{stem}-update.service"],
        "prefixes": [product.ENV_PREFIX, *legacy.ENV_PREFIXES],
        "renamed": list(legacy.ENV_RENAMED)}))
    return d


def refused(tmp_path):
    return [json.loads(x)["REFUSED"] for x in (tmp_path / "shim.log").read_text().splitlines()
            if "REFUSED" in x]


@pytest.mark.parametrize("unit", [legacy.UNIT, product.UNIT, "anything.service"])
def test_the_shims_refuse_every_other_unit(rw, sdir, tmp_path, unit):
    for verb in ("restart", "stop", "start", "enable", "is-active", "show", "cat"):
        assert rw.shim(str(sdir), "systemctl", ["--user", verb, unit]) == 1
    assert rw.shim(str(sdir), "systemd-run", ["--user", f"--unit={unit}", "/bin/true"]) == 1
    assert rw.shim(str(sdir), "journalctl", ["--user", "-u", unit]) == 1
    assert refused(tmp_path).count(unit) == 9


def test_the_shims_refuse_the_system_manager_and_a_scope(rw, sdir, tmp_path):
    assert rw.shim(str(sdir), "systemctl", ["stop", UNIT]) == 1
    assert rw.shim(str(sdir), "systemd-run", ["--user", "--scope", "/bin/true"]) == 1
    assert len(refused(tmp_path)) == 2


def test_the_shims_never_call_the_real_systemd():
    src = SCRIPT.read_text()
    assert "/bin/systemctl" not in src and "/bin/systemd-run" not in src
    assert 'Popen(["systemctl' not in src and 'run(["systemctl' not in src


def test_the_rehearsal_unit_runs_from_its_exec_start_and_environment(rw, sdir, tmp_path):
    units = tmp_path / "home" / ".config" / "systemd" / "user"
    (units / UNIT).write_text("[Service]\nEnvironment=A=1\nExecStart=/bin/sleep 30\n")
    (units / f"{UNIT}.d").mkdir()
    (units / f"{UNIT}.d" / "x.conf").write_text('[Service]\nEnvironment="B=two words" C=%h/c\n')
    command, env = rw._unit_service(rw._shim_cfg(sdir), UNIT)
    assert command == ["/bin/sleep", "30"]
    assert env == {"A": "1", "B": "two words", "C": f"{tmp_path}/home/c"}
    try:
        assert rw.shim(str(sdir), "systemctl", ["--user", "enable", "--now", UNIT]) == 0
        assert rw.shim(str(sdir), "systemctl", ["--user", "is-active", UNIT]) == 0
        pid = rw._read_state(rw._shim_cfg(sdir), UNIT)["pid"]
        environ = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
        assert b"A=1" in environ and b"B=two words" in environ
    finally:
        rw.shim(str(sdir), "systemctl", ["--user", "stop", UNIT])
    assert rw.shim(str(sdir), "systemctl", ["--user", "is-active", UNIT]) == 3
    assert refused(tmp_path) == []


def test_the_real_unit_hashes_say_absent_or_the_sha(rw, tmp_path):
    d = tmp_path / ".config" / "systemd" / "user"
    (d / f"{legacy.UNIT}.d").mkdir(parents=True)
    (d / legacy.UNIT).write_text("x")
    (d / f"{legacy.UNIT}.d" / "a.conf").write_text("y")
    got = rw.real_unit_hashes(tmp_path, [legacy.UNIT, product.UNIT])
    assert got[str(d / product.UNIT)] == "absent"
    assert len(got) == 3 and all(len(v) == 64 for k, v in got.items() if "absent" not in v)
