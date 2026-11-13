"""The console loads Kranto's copy of its plugin when Kranto wrote one:
``<home>/assistant/plugin``, without the skill of a feature that is off; else Kranto package's
own, as before."""

from kranto.page.term import console


def test_the_copy_in_kranto_home_wins_when_it_is_there(tmp_path, monkeypatch):
    monkeypatch.setattr(console, "kranto_home", lambda: tmp_path)
    wheel = console.plugin_dir()                        # none written: the package's, if any
    assert wheel is None or wheel != tmp_path / "assistant" / "plugin"
    copy = tmp_path / "assistant" / "plugin"
    (copy / ".claude-plugin").mkdir(parents=True)
    (copy / ".claude-plugin" / "plugin.json").write_text("{}")
    assert console.plugin_dir() == copy
    (copy / ".claude-plugin" / "plugin.json").unlink()  # a broken copy is not loaded
    assert console.plugin_dir() == wheel
