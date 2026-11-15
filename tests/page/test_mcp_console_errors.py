"""A tool that raises inside ``kranto mcp`` is an error report (``where: console``, with the
tool's verb), through the server's own ``telemetry.errors`` (which keeps it only as the person's
usage-report choice allows); reporting never fails the tool's answer (TEL, 2026-10-27)."""
import sys
import types

from kranto.page.mcp import server


def fake_kranto(monkeypatch, calls, raise_on_report=False):
    errors = types.ModuleType("kranto.telemetry.errors")

    def report(exc, where, **kw):
        if raise_on_report:
            raise RuntimeError("the report itself failed")
        calls.append((type(exc).__name__, where, kw))
    errors.report = report
    assistant = types.ModuleType("kranto.telemetry.assistant")
    assistant.verb_of_tool = lambda t: {"topic_add": "topic.add"}.get(t)
    telemetry = types.ModuleType("kranto.telemetry")
    telemetry.errors, telemetry.assistant = errors, assistant
    pkg = types.ModuleType("kranto")
    pkg.telemetry = telemetry
    for name, mod in (("kranto", pkg), ("kranto.telemetry", telemetry),
                      ("kranto.telemetry.errors", errors),
                      ("kranto.telemetry.assistant", assistant)):
        monkeypatch.setitem(sys.modules, name, mod)


def test_a_raising_tool_is_reported_as_the_consoles_error(monkeypatch, tmp_path):
    calls = []
    fake_kranto(monkeypatch, calls)
    monkeypatch.setenv("KRANTO_HOME", str(tmp_path))
    try:
        raise KeyError("a value of yours")
    except KeyError as exc:
        server.report_console_error(exc, "kranto_topic_add")
    assert calls == [("KeyError", "console", {"home": tmp_path.resolve(), "verb": "topic.add"})]


def test_reporting_never_fails(monkeypatch, tmp_path):
    fake_kranto(monkeypatch, [], raise_on_report=True)
    monkeypatch.setenv("KRANTO_HOME", str(tmp_path))
    server.report_console_error(ValueError("x"), "kranto_status")       # no exception
    monkeypatch.setitem(sys.modules, "kranto.telemetry", None)       # the server absent
    server.report_console_error(ValueError("x"), "kranto_status")
