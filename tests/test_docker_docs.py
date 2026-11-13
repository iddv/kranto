"""Every `docker run -p` or compose port the docs show binds to 127.0.0.1:
Kranto's Host check stops a browser on another site, not a client on the LAN, so a published
port must not reach the network."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = [*ROOT.glob("*.md"), *ROOT.glob("docs/**/*.md"), *ROOT.glob("packages/**/*.md"),
        ROOT / "Dockerfile"]
PORT = re.compile(r"(?:-p|--publish)[ =](\S+)")


def test_every_published_port_in_the_docs_is_loopback_only():
    seen = 0
    for f in DOCS:
        if not f.is_file():
            continue
        for n, line in enumerate(f.read_text().splitlines(), 1):
            if "docker" not in line and not line.lstrip().startswith("-p"):
                continue
            for spec in PORT.findall(line):
                seen += 1
                assert spec.startswith("127.0.0.1:"), f"{f.relative_to(ROOT)}:{n}: {spec}"
    assert seen >= 1                                 # the README's docker run is checked


def test_security_md_says_what_the_host_check_does_not_stop():
    text = (ROOT / "SECURITY.md").read_text()
    assert "127.0.0.1:8765:8765" in text and "not a client" in text
