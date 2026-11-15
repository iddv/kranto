"""Check cub.yaml files against the manifest's JSON Schema with ``jsonschema`` and with Kranto's
own validator, and say where the two disagree (the hand validator is what ships;
this is the cross-check a maintainer runs after editing ``core/cub.schema.json``).

    .venv/bin/python scripts/dev/check_cub_schema.py path/to/cub.yaml [more.yaml ...]

Needs the dev extras (``jsonschema``). Exit 0 when every file passes both, 1 otherwise.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import jsonschema
import yaml

from kranto.core import registry
from kranto.core.manifest import SCHEMA_FILE, ManifestError


def main(paths: list[str]) -> int:
    schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    bad = 0
    for p in paths:
        data = yaml.safe_load(Path(p).read_text(encoding="utf-8"))
        try:
            jsonschema.validate(data, schema)
            js = "ok"
        except jsonschema.ValidationError as exc:
            js = f"refused: {exc.message}"
        try:
            registry.validate_cub(copy.deepcopy(data))
            ours = "ok"
        except ManifestError as exc:
            ours = f"refused: {exc}"
        print(f"{p}\n  json schema: {js}\n  Kranto:       {ours}")
        bad += js != "ok" or ours != "ok"
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
