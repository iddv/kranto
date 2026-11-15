"""Write the usage reports' lists again after a verb was added or removed (TEL, 2026-10-27):

    .venv/bin/python scripts/dev/telemetry_lists.py

- ``src/kranto/telemetry/schema.json``'s ``verb`` enum: the server's own verbs and the
  built-in features' (``core.verbs``), then ``other``; the page's ``b.<action>`` are added
  from its ``action`` enum when the lists are merged;
- ``docs/privacy/what-kranto-sends.md`` (``kranto telemetry docs``).

``tests/test_telemetry_assistant.py`` fails until it is run. The relay's own copy of the list
left Kranto with ``ops/`` (cut 2): ``kranto telemetry schema`` prints the whole
list for the maintainer's next relay deploy; a new verb reaches the relay as ``other`` until
then."""
import json
import re
from pathlib import Path

from kranto.core import verbs
from kranto.telemetry import docs
from kranto.telemetry import schema as S

ROOT = Path(__file__).resolve().parents[2]


def verb_enum() -> None:
    p = ROOT / "src" / "kranto" / "telemetry" / "schema.json"
    s = p.read_text()
    kinds = [v.kind for v in verbs.CORE] + [v.kind for v in verbs.feature_verbs()] + ["other"]
    lines, cur = [], '    "verb": ['
    for k in kinds:
        item = json.dumps(k) + ", "
        if len(cur) + len(item) > 96:
            lines.append(cur.rstrip())
            cur = "             "
        cur += item
    lines.append(cur.rstrip().rstrip(",") + "],")
    s, n = re.subn(r'    "verb": \[[^\]]*\],', lambda m: "\n".join(lines), s, count=1)
    assert n == 1, "schema.json has no verb enum"
    json.loads(s)
    p.write_text(s)
    S.reset()


if __name__ == "__main__":
    verb_enum()
    (ROOT / "docs" / "privacy" / "what-kranto-sends.md").write_text(docs.page())
    print("verb list and the field page written")
