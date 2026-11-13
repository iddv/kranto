"""``python -m kranto.features.post.evals <export|read|round2|live> ...``: the prose eval's
tools (``__init__``'s docstring says what each is for). ``export`` and ``read`` call no model."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

USAGE = ("usage: python -m kranto.features.post.evals export --items <ids> --out DIR "
         "[--sites blog,toot] [--angles FILE]\n"
         "       python -m kranto.features.post.evals read --drafts DIR --out read.html "
         "--key key.md [--index FILE] [--seed N]\n"
         "       python -m kranto.features.post.evals round2 --home HOME --out DIR "
         "[--budget 3]\n"
         "       python -m kranto.features.post.evals live --home HOME [--budget 3]")


def _export(argv: list[str]) -> int:
    import json

    from . import export
    ap = argparse.ArgumentParser(prog="evals export", description=export.__doc__.split("\n")[0])
    ap.add_argument("--items", default="", help="item ids from items.json, comma-separated "
                                                "(default: every item)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--sites", default="blog", help="blog, toot or both")
    ap.add_argument("--angles", help="a JSON file: item -> {kind: sentence}, or a round-2 "
                                     "record (recorded2.json)")
    a = ap.parse_args(argv)
    angles = None
    if a.angles:
        raw = json.loads(Path(a.angles).read_text(encoding="utf-8"))
        if isinstance(raw.get("items"), dict):          # a round-2 record
            angles = {iid: {x["kind"]: x["text"] for x in r.get("angles") or []}
                      for iid, r in raw["items"].items()}
        else:
            angles = raw
    rows = export.export(Path(a.out), [i for i in a.items.split(",") if i] or None,
                         tuple(s for s in a.sites.split(",") if s), angles=angles)
    print(f"{len(rows)} prompts in {a.out} (each as .json and .txt; index.json lists them)")
    return 0


def _read(argv: list[str]) -> int:
    from . import readpage
    ap = argparse.ArgumentParser(prog="evals read",
                                 description=readpage.__doc__.split("\n")[0])
    ap.add_argument("--drafts", required=True, help="DIR/<writer>/<name>.md")
    ap.add_argument("--out", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--index", help="the export's index.json (labels each post)")
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--title", default="Posts by several writers: which would you post?")
    a = ap.parse_args(argv)
    got = readpage.build(Path(a.drafts), Path(a.out), Path(a.key),
                         index=Path(a.index) if a.index else None, seed=a.seed, title=a.title)
    print(f"{got['posts']} posts by {', '.join(got['writers'])}: {a.out} (key: {a.key})")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0 if argv else 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "export":
        return _export(rest)
    if cmd == "read":
        return _read(rest)
    if cmd == "round2":
        from . import round2
        return round2.main(rest)
    if cmd == "live":
        from . import live
        return live.main(rest)
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
