"""the telemetry tests that failed once on the runner.

The cause: ``server_jobs(update_job=True)`` (``test_activity_api``) starts the error reports'
flusher, as the server does, and nothing stopped it. For the rest of the serial run it flushed
its dead home every 30 s; that home's mode said off, so ``flush`` called ``forget``, which
cleared the module's ``_pending``: a tick inside another test emptied what it had just
reported ("sent 0, waiting 0", "40 == 50"). Here a flusher is left running on purpose, ticking
every 10 ms, and the three tests that flaked pass 50 times in a row beside it.
"""

from __future__ import annotations

import threading

import pytest

from kranto import config as config_mod
from kranto import telemetry
from kranto.telemetry import errors, local

from . import test_telemetry as tt
from . import test_telemetry_errors as te
from .conftest import reports_threads_left


def _leak(tmp_path, keep: bool) -> errors.Flusher:
    """A flusher of a home whose mode is off, left as an earlier test left it: still this
    process's ``_flusher`` (``keep``, as ``test_activity_api`` did) or let go of (the telemetry
    fixtures' ``_flusher = None``)."""
    dead = tmp_path / "dead"
    config_mod.init_workspace(dead)
    fl = errors.Flusher(dead, tick_s=0.01)
    fl.start()
    errors._flusher = fl
    if not keep:
        errors._flusher = None
    return fl


@pytest.mark.parametrize("keep", [True, False])
def test_the_three_tests_hold_beside_a_flusher_left_running(tmp_path, monkeypatch, keep):
    for k in (local.DNT, local.ENV_MODE):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv(local.ENV_ENDPOINT, te.ENDPOINT)
    fl = _leak(tmp_path, keep)
    try:
        for i in range(50):
            run = tmp_path / f"r{i}"
            for name, test in (("limits", te.test_the_limits_per_batch_hour_and_day),
                               ("unreached", te.test_unreached_keeps_the_reports_and_waits)):
                (run / name).mkdir(parents=True)
                errors._pending.clear()
                try:
                    test(run / name, monkeypatch) if name == "limits" else test(run / name)
                finally:
                    errors._pending.clear()
                    errors._flusher = None               # as the telemetry fixtures do
                    telemetry.configure(None)
            h = run / "detailed" / "home"
            config_mod.init_workspace(h)
            telemetry.configure(h)
            monkeypatch.delenv(local.ENV_ENDPOINT)       # test_telemetry's own environment
            try:
                tt.test_detailed_carries_a_random_id(h)
            finally:
                telemetry.configure(None)
                monkeypatch.setenv(local.ENV_ENDPOINT, te.ENDPOINT)
    finally:
        fl.stop()
        errors._flusher = None


def test_a_flusher_let_go_of_ends_by_itself(tmp_path):
    before = set(threading.enumerate())
    _leak(tmp_path, keep=False)
    assert reports_threads_left(before) == []


def test_the_guard_finds_a_flusher_left_running(tmp_path):
    before = set(threading.enumerate())
    fl = _leak(tmp_path, keep=True)
    try:
        assert [t.name for t in reports_threads_left(before, wait_s=0.1)] == \
            ["kranto-error-reports"]
    finally:
        fl.stop()
        errors._flusher = None
    assert reports_threads_left(before) == []
