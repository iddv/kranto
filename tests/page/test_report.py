"""Report to Kranto: the new-issue link the feedback sheet opens when ``gh``
cannot file is scrubbed of secrets, personal data, paths, the host and the login, under 6,000
characters with the dedupe marker intact. The scrub cannot run: nothing is offered."""
import secrets as pysecrets
import socket
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from kranto.page import report as R
from kranto.page.upstream import REPOS

FACTORY = REPOS["kranto"]
MARK = "<!-- kranto-report: build/401-auth -->"


def test_scrub_removes_secrets_paths_host_and_login(tmp_path, monkeypatch):
    tok = "ghp_" + pysecrets.token_hex(18)
    home = Path.home()
    monkeypatch.setenv("KRANTO_HOME", str(tmp_path / "kranto"))
    host = socket.gethostname()
    text = (f"Transcript: {home}/tasks/plots/.den/x.jsonl\nGITHUB_TOKEN={tok}\n"
            f"mail jane.doe@example.org or +1 415 555 0132; thanks @karpathy\n"
            f"on {host} as octo-owner; {tmp_path}/kranto/loop/loop.yaml; /home/someone/else/x\n"
            f"the bot octo-owner[bot] and octo-owner-ish")
    out = R.scrub(text, None, "octo-owner", host)
    assert tok not in out and "[redacted]" in out
    assert "jane.doe" not in out and "415" not in out and "karpathy" not in out
    assert str(home) not in out and "<home>/tasks/plots" in out
    assert str(tmp_path) not in out and "<kranto>/loop/loop.yaml" in out
    assert "/home/someone" not in out and "<home>/else/x" in out
    assert host not in out and "<host> as <you>" in out
    assert "<you>[bot]" in out and "octo-owner-ish" in out       # a longer word is not the login


def test_fit_cuts_at_a_paragraph_and_keeps_the_marker():
    title = "Build stage dies when the login expires"
    long = "\n\n".join(f"paragraph {i}: " + "words " * 200 for i in range(20)) + "\n\n" + MARK
    assert len(long) > 20_000
    url, body, cut = R.fit(FACTORY, title, long)
    assert cut and len(url) <= R.MAX_URL and url.startswith(f"https://github.com/{FACTORY}/issues/new?")
    q = parse_qs(urlsplit(url).query)
    assert q["title"] == [title] and q["body"] == [body]
    assert body.rstrip().endswith(MARK) and R.CUT_NOTE.strip() in body
    assert body.startswith("paragraph 0:") and "paragraph 19" not in body
    url2, body2, cut2 = R.fit(FACTORY, title, "short\n\n" + MARK)
    assert not cut2 and body2 == "short\n\n" + MARK and len(url2) < 300
    rep = R.build(FACTORY, title, long, None, "octo-owner", "box")
    assert rep["cut"] and rep["text"].endswith(MARK) and rep["body"] in rep["text"][:len(rep["body"])] or MARK in rep["body"]


def test_without_a_scrub_nothing_is_offered(monkeypatch):
    monkeypatch.setattr(R, "_EMAIL", None)                  # the scrub breaks: no report
    with pytest.raises(R.ReportError, match="could not be scrubbed"):
        R.build(FACTORY, "x", "y", None, "octo-owner", "box")
