"""paths.py: one module finds the homes and names what is inside them. Each
resolver that now calls it keeps its order; the table below pins them."""
from pathlib import Path

import pytest

from kranto.page import paths
from kranto.page.settings import store


@pytest.fixture
def user(tmp_path, monkeypatch):
    """A user home with no pointer and no unit, and none of the env names set."""
    home = tmp_path / "user"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    for k in (paths.KRANTO_HOME_ENV, paths.LOOP_HOME_ENV, paths.UNIT_ENV):
        monkeypatch.delenv(k, raising=False)
    return home


def point(user: Path, at: Path, name: str = "home") -> None:
    (user / ".config" / "kranto").mkdir(parents=True, exist_ok=True)
    (user / ".config" / "kranto" / name).write_text(f"{at}\n")


def unit(user: Path, home_line: str, name: str = "kranto.service") -> None:
    d = paths.unit_dir(user)
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(f"[Service]\n{home_line}\nExecStart=/bin/true\n")


def test_kranto_home_explicit_then_env_then_pointer_then_unit_then_default(user, monkeypatch,
                                                                           tmp_path):
    assert paths.kranto_home(user_home=user) == (Path("~/.kranto").expanduser().resolve())
    assert paths.kranto_home(user_home=user, default=None) is None
    unit(user, "Environment=KRANTO_HOME=%h/from-unit")
    assert paths.kranto_home(user_home=user) == (user / "from-unit").resolve()
    point(user, tmp_path / "pointed")
    assert paths.kranto_home(user_home=user) == (tmp_path / "pointed").resolve()
    monkeypatch.setenv("KRANTO_HOME", str(tmp_path / "env"))
    assert paths.kranto_home(user_home=user) == (tmp_path / "env").resolve()
    assert paths.kranto_home(tmp_path / "flag", user_home=user) == (tmp_path / "flag").resolve()
    assert paths.kranto_home(user_home=None, default=None) == (tmp_path / "env").resolve()


def test_another_unit_keeps_its_own_pointer(user, monkeypatch, tmp_path):
    point(user, tmp_path / "real")
    monkeypatch.setenv("KRANTO_UNIT", "kranto-test.service")
    assert paths.pointer_path(user).name == "home.kranto-test"
    assert paths.read_pointer(user) is None
    point(user, tmp_path / "scratch", "home.kranto-test")
    assert paths.recorded_home(user) == tmp_path / "scratch"
    assert paths.read_pointer(user, paths.DEFAULT_UNIT) == tmp_path / "real"


def test_an_empty_pointer_is_no_pointer(user, tmp_path):
    point(user, tmp_path)
    paths.pointer_path(user).write_text("\n")
    assert paths.read_pointer(user) is None and paths.recorded_home(user) is None


@pytest.mark.parametrize("line, want", [
    ("Environment=KRANTO_HOME=%h/kb", "U/kb"),
    ('Environment="KRANTO_HOME=%h/kb"', "U/kb"),
    ('Environment=KRANTO_HOME="/abs/kb"', "/abs/kb"),
    ("Environment=OTHER=1", None),
])
def test_unit_env_reads_quoted_and_bare_values(line, want, tmp_path):
    env = paths.unit_env(f"[Service]\n{line}\n", tmp_path / "U")
    got = env.get("KRANTO_HOME")
    assert got == (want.replace("U/", f"{tmp_path / 'U'}/") if want else None)


def test_loop_home_configured_then_env_then_default(user, monkeypatch, tmp_path):
    assert paths.loop_home() == Path("~/kranto-loop").expanduser().resolve()
    monkeypatch.setenv("KRANTO_LOOP_HOME", str(tmp_path / "env"))
    assert paths.loop_home() == (tmp_path / "env").resolve()
    assert paths.loop_home(tmp_path / "conf") == (tmp_path / "conf").resolve()


def test_the_loop_finds_the_kranto_installs_loop_home(user, monkeypatch, tmp_path):
    """settings.store.home: --home, $KRANTO_LOOP_HOME, the kranto install's (its config's
    brb.loop_home, else its loop/), else ~/kranto-loop. The install is $KRANTO_HOME or the
    pointer, never the unit."""
    assert store.kranto_loop_home() is None
    kranto = tmp_path / "kranto"
    (kranto / "loop").mkdir(parents=True)
    point(user, kranto)
    assert store.kranto_loop_home() == kranto / "loop"
    (kranto / "kranto.yaml").write_text("brb:\n  loop_home: elsewhere\n")
    assert store.kranto_loop_home() == kranto / "elsewhere"
    monkeypatch.setenv("KRANTO_HOME", str(tmp_path / "none"))
    assert store.kranto_loop_home() is None
    monkeypatch.setenv("KRANTO_LOOP_HOME", str(tmp_path / "env"))
    assert store.home() == (tmp_path / "env").resolve()
    assert store.home(tmp_path / "flag") == (tmp_path / "flag").resolve()


def test_the_layouts_name_what_the_homes_hold(tmp_path):
    lay = paths.Layout(tmp_path)
    assert lay.config == tmp_path / "kranto.yaml"
    (tmp_path / "kranto.yaml").write_text("")
    assert lay.config == tmp_path / "kranto.yaml"            # an adopted the server workspace
    (tmp_path / "kranto.yaml").write_text("")
    assert lay.config == tmp_path / "kranto.yaml"
    assert lay.db == tmp_path / "data" / "kranto.db" and lay.mcp_servers.name == "mcp-servers"
    loop = paths.LoopLayout(tmp_path)
    assert store.Config(tmp_path).layout.settings == loop.settings
    assert [p.name for p in (loop.settings, loop.db, loop.lock, loop.pid)] == \
        ["loop.yaml", "loop.db", "daemon.lock", "daemon.pid"]


def test_paths_py_is_stdlib_only():
    import ast
    tree = ast.parse(Path(paths.__file__).read_text())
    mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)
            for a in n.names}
    mods |= {n.module.split(".")[0] for n in ast.walk(tree)
             if isinstance(n, ast.ImportFrom) and n.module and not n.level}
    # and the two name modules (kranto.legacy, kranto.product), standard library only too
    froms = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert mods <= {"__future__", "os", "re", "dataclasses", "pathlib", "kranto"}, mods
    assert {m for m in froms if m.startswith("kranto")} <= {"kranto"}, froms


def test_paths_py_is_the_same_in_both_repos():
    afk = pytest.importorskip("kranto.paths")
    assert Path(afk.__file__).read_bytes() == Path(paths.__file__).read_bytes()


def test_no_module_joins_the_homes_names_by_hand():
    """The homes' entries are named in paths.py only (S-8 step 2 and its remainder): its files
    and its directories (``publish/``, ``inbox/``, ``chat/``, ``maintain/``, ``projects/``),
    ``cfg.layout.settings``,
    ``paths.LoopLayout(home).db``, ``paths.Layout(home).mcp_servers``, never ``home / "loop.yaml"``.
    """
    import re
    names = r"loop\.yaml|loop\.db|daemon\.(?:pid|lock|log)|actions\.jsonl|PAUSE|kranto\.yaml|" \
            r"kranto\.yaml|mcp-servers"
    join = re.compile(rf"/\s*[\"'](?:{names})[\"']")
    # and a loop home's directories, joined to the home itself (cfg.home, Path(home))
    dirs = re.compile(r"\bhome\)?\s*/\s*[\"'](?:publish|inbox|chat|maintain|projects)[\"']")
    allowed: set[tuple[str, str]] = set()
    root = Path(paths.__file__).resolve().parents[2]
    bad = []
    for f in sorted((root / "src" / "kranto" / "page").rglob("*.py")):
        rel = str(f.relative_to(root))
        if "__pycache__" in f.parts or rel in ("src/kranto/page/paths.py",):
            continue
        for n, line in enumerate(f.read_text().splitlines(), 1):
            for m in [*join.finditer(line), *dirs.finditer(line)]:
                if not any(rel == a and b in m.group(0) for a, b in allowed):
                    bad.append(f"{rel}:{n}: {line.strip()}")
    assert not bad, "join through paths.py:\n" + "\n".join(bad)
