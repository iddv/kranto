"""One loop home: the page on a Kranto install uses that install's loop (the home
``kranto up`` or ``kranto adopt`` recorded), never a second, empty ``~/kranto-loop``; and nothing
starts a home that is not there."""
import pytest

from kranto.page.settings import store as config


@pytest.fixture
def user(tmp_path, monkeypatch):
    home = tmp_path / "user"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for k in ("KRANTO_LOOP_HOME", "KRANTO_HOME", "KRANTO_UNIT"):
        monkeypatch.delenv(k, raising=False)
    return home


def record(user, kranto, name="home"):
    (user / ".config" / "kranto").mkdir(parents=True, exist_ok=True)
    (user / ".config" / "kranto" / name).write_text(f"{kranto}\n")


def test_without_kranto_it_is_brb_loop(user):
    assert config.home() == (user / "kranto-loop").resolve()


def test_a_kranto_install_names_its_loop_home(user, tmp_path, monkeypatch):
    kranto = tmp_path / "kb"
    kranto.mkdir()
    (kranto / "kranto.yaml").write_text(f"brb:\n  enabled: true\n  loop_home: {tmp_path / 'loop'}\n")
    record(user, kranto)
    assert config.home() == (tmp_path / "loop").resolve()
    # $KRANTO_LOOP_HOME and an explicit home still win
    monkeypatch.setenv("KRANTO_LOOP_HOME", str(tmp_path / "other"))
    assert config.home() == (tmp_path / "other").resolve()
    assert config.home(tmp_path / "x") == (tmp_path / "x").resolve()


def test_a_new_kranto_home_keeps_its_loop_inside(user, tmp_path):
    kranto = tmp_path / "dot-kranto"
    (kranto / "loop").mkdir(parents=True)
    (kranto / "kranto.yaml").write_text("brb:\n  enabled: true\n")
    record(user, kranto)
    assert config.home() == (kranto / "loop").resolve()


def test_another_unit_and_kranto_home_are_followed(user, tmp_path, monkeypatch):
    test_home = tmp_path / "scratch"
    (test_home / "loop").mkdir(parents=True)
    record(user, tmp_path / "nowhere")                        # the real unit's pointer
    record(user, test_home, "home.kranto-test")
    monkeypatch.setenv("KRANTO_UNIT", "kranto-test.service")
    assert config.home() == (test_home / "loop").resolve()
    monkeypatch.delenv("KRANTO_UNIT")
    monkeypatch.setenv("KRANTO_HOME", str(test_home))
    assert config.home() == (test_home / "loop").resolve()


def test_reading_a_home_that_is_not_there_makes_nothing(user, tmp_path):
    missing = tmp_path / "no-such-loop"
    config.Config(missing)
    assert not missing.exists()
