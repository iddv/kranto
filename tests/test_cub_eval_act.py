"""``kranto cub eval`` says when pytest is missing; Kranto package ships pytest for it; ``kranto
cub act`` reads a file on the owner's side and posts the action through the page's route with
the command line's door. (These ran on the examplecom cub until it moved to
a repository of its own with its own tests.)

No connection exists and nothing leaves the machine (the model is a fake transport)."""

from __future__ import annotations

import httpx
import pytest

from kranto.core.cubs import cli as cubs_cli

from .cubhelp import needs_bwrap
from .test_examples_install import add, home  # noqa: F401 - fixture
from .test_web import rt  # noqa: F401 - fixture

POST = ("# What Kranto turned into\n\n**Slug:** what-the-kranto-turned-into\n\n"
        "---\n\n## Body\n\nIn April I wrote about patient agents.\n")


@needs_bwrap
def test_kranto_cub_eval_says_when_pytest_is_not_installed(home, capsys, monkeypatch):  # noqa: F811
    import importlib.util
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda name, *a: None if name == "pytest" else real(name, *a))
    add(home, "newsletter")
    assert cubs_cli.main(home.cfg.root, ["eval", "newsletter"], rt=home) == 1
    out = capsys.readouterr().out
    assert "tests     FAILED: not run: pytest is not installed" in out
    assert "standard  ok" in out


def test_the_kranto_package_ships_pytest_for_kranto_cub_eval():
    import tomllib
    from pathlib import Path
    meta = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
    assert any(d.startswith("pytest") for d in meta["project"]["dependencies"])


def test_kranto_cub_act_reads_the_file_and_posts_with_the_cli_door(tmp_path, monkeypatch, rt,  # noqa: F811
                                                                  capsys):
    md = tmp_path / "post.md"
    md.write_text(POST)
    seen = {}

    def fake_post(url, json=None, timeout=None, headers=None):  # noqa: A002
        seen.update(url=url, json=json)
        return httpx.Response(200, json={"say": "Drafted: ticket #4 waits for your press."},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    code = cubs_cli.main(rt.cfg.root, ["act", "blog", "blog.draft_markdown", "--field",
                                       f"markdown=@{md}", "--field", "category=build"], rt=rt)
    assert code == 0 and "ticket #4" in capsys.readouterr().out
    assert seen["url"].endswith("/api/f/blog/act/draft_markdown")
    assert seen["json"] == {"fields": {"markdown": POST, "category": "build"}}


def test_kranto_cub_act_refuses_a_missing_file_and_a_bad_pair(tmp_path, rt):  # noqa: F811
    with pytest.raises(ValueError, match="cannot read"):
        cubs_cli.fields_of([f"markdown=@{tmp_path / 'none.md'}"])
    with pytest.raises(ValueError, match="key=value"):
        cubs_cli.fields_of(["markdown"])
