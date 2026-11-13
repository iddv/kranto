"""Names from before the rename, still honoured on an install made then (``kranto.legacy``):
each is read where it is, nothing is moved, and a new install gets the new names."""
from __future__ import annotations

import ast
from pathlib import Path

from kranto import legacy, product
from kranto.paths import Layout

OLD_ENV = legacy.ENV_PREFIXES[0]


def test_an_old_variable_counts_as_the_new_one_unless_the_new_one_is_set():
    env = {OLD_ENV + "HOME": "/old", OLD_ENV + "UNIT": "x.service", "KRANTO_UNIT": "y.service",
           "BRB_LOOP_HOME": "/loop", "PATH": "/bin"}
    seen = legacy.adopt_env(env)
    assert env["KRANTO_HOME"] == "/old"                 # adopted
    assert env["KRANTO_UNIT"] == "y.service"            # the new name wins
    assert env["KRANTO_LOOP_HOME"] == "/loop"
    assert sorted(seen) == sorted([OLD_ENV + "HOME", OLD_ENV + "UNIT", "BRB_LOOP_HOME"])
    assert "PATH" not in seen


def test_forgetting_drops_the_old_names_and_only_the_copies_made_from_them():
    env = {OLD_ENV + "HOME": "/old", "KRANTO_HOME": "/old", OLD_ENV + "UNIT": "a",
           "KRANTO_UNIT": "b", "KRANTO_OTHER": "c"}
    legacy.forget_env(env)
    assert env == {"KRANTO_UNIT": "b", "KRANTO_OTHER": "c"}


def test_a_new_home_has_the_new_settings_file_and_library(tmp_path):
    (tmp_path / "data").mkdir()
    assert Layout(tmp_path).config == tmp_path / product.HOME_FILE
    assert Layout(tmp_path).db == tmp_path / "data" / product.DB_FILE


def test_an_old_home_keeps_its_settings_file_and_library_where_they_are(tmp_path):
    (tmp_path / "data").mkdir()
    for name in reversed(legacy.HOME_FILES):           # the oldest first, then the newer
        (tmp_path / name).write_text("{}\n")
        assert Layout(tmp_path).config == tmp_path / name
    (tmp_path / "data" / legacy.DB_FILE).write_bytes(b"")
    assert Layout(tmp_path).db == tmp_path / "data" / legacy.DB_FILE
    # once the new file exists it wins
    (tmp_path / product.HOME_FILE).write_text("{}\n")
    assert Layout(tmp_path).config == tmp_path / product.HOME_FILE


def test_the_config_folder_is_the_old_one_until_the_new_one_holds_a_home(tmp_path):
    new = tmp_path / ".config" / product.CONFIG_DIR
    assert legacy.config_dir(tmp_path) == new                  # a new install
    old = tmp_path / ".config" / legacy.CONFIG_DIR
    old.mkdir(parents=True)
    assert legacy.config_dir(tmp_path) == old                  # made before the rename
    # a stray new folder (made by hand, or a scratch instance's own pointer and tokens) does
    # not pull the old install away from its tokens and logins
    new.mkdir()
    (new / "home.kranto-test").write_text("/x\n")
    (new / "tokens.kranto-test").mkdir()
    assert legacy.config_dir(tmp_path) == old
    (new / "home").write_text("/kb\n")                        # an install's own pointer
    assert legacy.config_dir(tmp_path) == new


def test_the_old_units_pointer_is_its_plain_home_file(tmp_path):
    from kranto import paths

    old = tmp_path / ".config" / legacy.CONFIG_DIR
    old.mkdir(parents=True)
    assert paths.pointer_path(tmp_path, legacy.UNIT) == old / "home"
    assert paths.pointer_path(tmp_path, "other.service") == old / "home.other"


def test_the_preview_never_serves_an_old_installs_folders(tmp_path):
    from kranto import preview

    assert set(legacy.live_homes()) <= set(preview.LIVE_HOMES)
    assert legacy.UNIT in preview.LIVE_UNITS and product.UNIT in preview.LIVE_UNITS


def test_the_two_name_modules_are_standard_library_only():
    for mod in (product, legacy):
        tree = ast.parse(Path(mod.__file__).read_text())
        names = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        froms = {(n.level, n.module) for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        # ``import product``: the update helper's standalone copy, beside product.py
        assert names <= {"os", "product"}, (mod.__name__, names)
        assert froms <= {(0, "__future__"), (0, "pathlib"), (0, "typing"), (1, None)}, \
            (mod.__name__, froms)


def test_the_page_settings_old_section_reads_as_the_new_one():
    old = {legacy.LOOP_SECTION: {"url": "http://127.0.0.1:1"}, "concurrency": 1}
    assert legacy.loop_settings(old) == {"kranto": {"url": "http://127.0.0.1:1"},
                                         "concurrency": 1}
    both = {legacy.LOOP_SECTION: {"url": "a"}, "kranto": {"url": "b"}}
    assert legacy.loop_settings(both) == both


def test_the_unit_is_named_else_the_old_one_when_only_it_is_installed(tmp_path):
    units = tmp_path / ".config" / "systemd" / "user"
    env = {"HOME": str(tmp_path)}
    assert legacy.unit_name(env) == product.UNIT               # a new install
    units.mkdir(parents=True)
    (units / legacy.UNIT).write_text("[Unit]\n")
    assert legacy.unit_name(env) == legacy.UNIT                # made before the rename
    (units / product.UNIT).write_text("[Unit]\n")
    assert legacy.unit_name(env) == product.UNIT               # both: the new one
    assert legacy.unit_name({**env, "KRANTO_UNIT": "x.service"}) == "x.service"
    old_var = legacy.ENV_PREFIXES[0] + "UNIT"
    assert legacy.unit_name({**env, old_var: "y.service"}) == "y.service"
    assert legacy.unit_name({"HOME": "/nowhere", "XDG_CONFIG_HOME": str(tmp_path / ".config")}) \
        == product.UNIT


def test_a_unit_store_is_in_the_old_folder_on_an_old_install(tmp_path):
    env = {"HOME": str(tmp_path)}
    assert legacy.unit_store("tokens", env) == tmp_path / ".config" / product.CONFIG_DIR / "tokens"
    old = tmp_path / ".config" / legacy.CONFIG_DIR
    old.mkdir(parents=True)
    units = tmp_path / ".config" / "systemd" / "user"
    units.mkdir(parents=True)
    (units / legacy.UNIT).write_text("[Unit]\n")
    assert legacy.unit_store("tokens", env) == old / "tokens"   # the old unit is the default
    assert legacy.unit_store("claude", {**env, "KRANTO_UNIT": "kranto-test.service"}) \
        == old / "claude.kranto-test"


def test_mcp_answers_to_the_name_it_was_started_as():
    assert legacy.mcp_server_for("/home/user/.local/bin/" + legacy.COMMAND) == legacy.MCP_SERVER
    assert legacy.mcp_server_for("kranto") == product.MCP_SERVER
    assert legacy.mcp_server_for(None) == product.MCP_SERVER
    assert f"mcp__{legacy.MCP_SERVER}__{legacy.MCP_SERVER}_" in legacy.MCP_ALLOW_PREFIXES
    assert legacy.alias_notice().endswith("both commands work.")


def test_the_compat_set_names_the_old_distributions():
    assert set(legacy.COMPAT_DISTS) == set(legacy.DISTS)
    assert legacy.TOOL == legacy.COMPAT_META == legacy.COMMAND
