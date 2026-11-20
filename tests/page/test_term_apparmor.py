"""Where bubblewrap works but the machine refuses the user namespace the console's shell prefix
nests in it for each command (Ubuntu's AppArmor, 24.04 and later), Open in Claude Code does not
claim a sandbox it cannot have: it is off by itself, and the page and ``kranto doctor`` say in
one line what is refused and what to do."""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from kranto.page.box import isolation
from kranto.page.box import sandbox as box
from kranto.page.term import launch

TOKEN = {"CLAUDE_CODE_OAUTH_TOKEN": "set"}


@pytest.fixture
def refused(monkeypatch):
    monkeypatch.setattr(isolation, "isolation", lambda: "bwrap")
    monkeypatch.setattr(isolation, "nested_userns", lambda: False)
    monkeypatch.setattr(isolation, "apparmor_restricts", lambda: True)
    monkeypatch.setattr(launch, "boxed", box.available)


def test_the_box_is_not_offered_where_apparmor_refuses_its_namespace(refused):
    assert not box.available()
    on, why = launch.offered({"enabled": None}, TOKEN)
    assert not on
    assert why.startswith("Open in Claude Code is off: AppArmor refuses the user namespace")
    assert "kernel.apparmor_restrict_unprivileged_userns" in why and "restart Kranto" in why
    assert "\n" not in why
    with pytest.raises(box.SandboxUnavailable, match="AppArmor refuses"):
        box.command(isolation.Path("/tmp"))


def test_the_doctor_says_why_when_it_is_turned_on_anyway(refused, tmp_path, monkeypatch):
    claude = tmp_path / "bin" / "claude"
    claude.parent.mkdir()
    claude.write_text("#!/bin/sh\nexit 0\n")
    claude.chmod(0o755)
    home = tmp_path / "loop"
    home.mkdir()
    (home / "loop.yaml").write_text("term:\n  enabled: true\n")
    status, text = launch.doctor_lines(home, {"PATH": f"{claude.parent}:/usr/bin:/bin", **TOKEN})
    assert status == "warn" and "sessions run without the sandbox: AppArmor refuses" in text
    (home / "loop.yaml").write_text("{}\n")
    status, text = launch.doctor_lines(home, {"PATH": f"{claude.parent}:/usr/bin:/bin", **TOKEN})
    assert status == "warn" and text.startswith("Open in Claude Code is off: AppArmor refuses")


def test_without_apparmor_the_line_names_no_setting_it_cannot_see(monkeypatch):
    monkeypatch.setattr(isolation, "isolation", lambda: "bwrap")
    monkeypatch.setattr(isolation, "nested_userns", lambda: False)
    monkeypatch.setattr(isolation, "apparmor_restricts", lambda: False)
    why = isolation.box_refusal()
    assert "apparmor" not in why.lower() and "run Kranto on the host" in why
    monkeypatch.setattr(isolation, "nested_userns", lambda: True)
    assert isolation.box_refusal() is None


def test_on_this_machine_the_box_claims_what_the_machine_allows():
    """The real probe against a plain nested namespace in bubblewrap (what CI's sandbox job
    runs before and after it lifts the image's AppArmor restriction): they agree, and the
    log shows what the page and the doctor would say."""
    bwrap, unshare = shutil.which("bwrap"), shutil.which("unshare")
    if not bwrap or isolation.isolation() != "bwrap":
        pytest.skip("bubblewrap does not work here")
    raw = subprocess.run([bwrap, "--unshare-all", "--die-with-parent", "--new-session",
                          "--ro-bind", "/", "/", "--proc", "/proc", "--dev", "/dev", unshare,
                          *isolation.NESTED, "true"], capture_output=True, text=True)
    restrict = isolation.apparmor_restricts()
    print(f"\napparmor_restrict_unprivileged_userns: {int(restrict)}; nested namespace in "
          f"bwrap: {'allowed' if raw.returncode == 0 else 'refused: ' + raw.stderr.strip()}")
    print("the box:", "available" if box.available() else "not available")
    print("the page:", launch.offered({"enabled": None}, TOKEN)[1] or "Open in Claude Code is on")
    assert box.available() == (raw.returncode == 0)
    assert (isolation.box_refusal() is None) == (raw.returncode == 0)
    if os.environ.get("KRANTO_EXPECT_NESTED") in ("0", "1"):
        assert box.available() == (os.environ["KRANTO_EXPECT_NESTED"] == "1")
