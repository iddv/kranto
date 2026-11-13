"""Write Kranto UI's TypeScript types for the server's JSON: an interface per
TypedDict in ``src/kranto/web/types.py``, the ``Routes`` map (``RETURNS``) and
``HOST_API_VERSION``. The file lives in the page (``src/kranto/page/ui/web/src/api/afk.gen.ts``).

    python scripts/gen_ts.py PATH            write the file (run with the server's venv)
    python scripts/gen_ts.py --check PATH    exit 1 when PATH is not what this writes

Rules (the same as the page's ``scripts/gen_ts.py``): ``list[X]`` -> ``X[]``,
``dict[str, X]`` -> ``Record<string, X>``, ``X | None`` -> ``X | null``, ``Literal`` -> a
union, ``NotRequired`` -> ``?``, ``Any`` -> ``unknown``; a type in ``OPEN`` gains
``[key: string]: unknown``. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import sys
import types
import typing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
HEAD = ("// Generated from the server's web/types.py; do not edit: change the Python side and\n"
        "// run the server's scripts/gen_ts.py with this file's path. A test fails when it is\n"
        "// stale.\n")


def ts(tp, names: set[str]) -> str:
    """The TypeScript for one Python annotation."""
    origin, args = typing.get_origin(tp), typing.get_args(tp)
    if tp is typing.Any:
        return "unknown"
    if tp is None or tp is type(None):
        return "null"
    if origin is typing.Literal:
        return " | ".join(json.dumps(a) for a in args)
    if origin in (typing.Union, types.UnionType):
        return " | ".join(ts(a, names) for a in args)
    if origin is list:
        inner = ts(args[0], names)
        return f"({inner})[]" if " " in inner else f"{inner}[]"
    if origin is dict:
        return f"Record<string, {ts(args[1], names)}>"
    if typing.is_typeddict(tp):
        if tp.__name__ not in names:
            raise TypeError(f"{tp.__name__} is not defined in the server/web/types.py")
        return tp.__name__
    simple = {str: "string", int: "number", float: "number", bool: "boolean"}
    if tp in simple:
        return simple[tp]
    raise TypeError(f"gen_ts: no rule for {tp!r}")


def types_ts() -> str:
    from kranto.web import types as T

    dicts = [v for v in vars(T).values()
             if typing.is_typeddict(v) and v.__module__ == T.__name__]
    names = {d.__name__ for d in dicts}
    out = [HEAD, f"export const HOST_API_VERSION = {T.HOST_API_VERSION};\n"]
    for alias, v in vars(T).items():
        if typing.get_origin(v) is typing.Literal:
            out.append(f"export type {alias} = {ts(v, names)};\n")
    for d in dicts:
        doc = " ".join((d.__doc__ or "").split())
        out.append(f"\n/** {doc} */\n" if doc else "\n")
        out.append(f"export interface {d.__name__} {{\n")
        for k, tp in typing.get_type_hints(d).items():
            opt = "" if k in d.__required_keys__ else "?"
            out.append(f"  {k}{opt}: {ts(tp, names)};\n")
        if d.__name__ in T.OPEN:
            out.append("  [key: string]: unknown;\n")
        out.append("}\n")
    out.append("\n/** What each path the page reads answers. */\nexport interface Routes {\n")
    for path, tp in T.RETURNS.items():
        out.append(f"  {json.dumps(path)}: {tp.__name__};\n")
    out.append("}\n")
    return "".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", type=Path, help="the .ts file (the page's src/api/afk.gen.ts)")
    ap.add_argument("--check", action="store_true", help="exit 1 when the file is stale")
    a = ap.parse_args(argv)
    text = types_ts()
    if a.path.is_file() and a.path.read_text() == text:
        return 0
    if a.check:
        print(f"gen_ts: {a.path} is stale; run python scripts/gen_ts.py {a.path}",
              file=sys.stderr)
        return 1
    a.path.parent.mkdir(parents=True, exist_ok=True)
    a.path.write_text(text)
    print(f"gen_ts: wrote {a.path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
