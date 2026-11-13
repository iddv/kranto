"""The runner Kranto starts inside a cub's sandbox:

    python -I -S -B -u /opt/kranto/sdk/bears_cub/_run.py --sdk /opt/kranto/sdk --src /cub/src
        --entry main.py --manifest /cub/src/cub.yaml [--site /cub/venv/lib/python3.12/site-packages]

``-I -S`` leave the interpreter with the standard library alone; this file builds ``sys.path``
itself: the SDK, the cub's own venv (as a site directory, so its ``.pth`` files work), the
cub's folder, then the standard library, and nothing else. It reads ``cub.yaml`` for the
``hello`` (its id, version and hash), loads the entry file, and serves ``cub/1`` on stdin and
stdout until the host closes the pipe. The cub's stderr is its log.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys


def _path(sdk: str, site: str | None, src: str) -> None:
    stdlib = [p for p in sys.path if p]
    sys.path[:] = [sdk]
    if site:
        import site as site_mod
        site_mod.addsitedir(site)
    sys.path.append(src)
    sys.path.extend(p for p in stdlib if p not in sys.path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bears_cub._run")
    ap.add_argument("--sdk", required=True)
    ap.add_argument("--src", required=True)
    ap.add_argument("--entry", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--site")
    args = ap.parse_args(argv)
    _path(args.sdk, args.site, args.src)

    from bears_cub import schema
    from bears_cub.cub import the_cub
    from bears_cub.wire import Session

    data = schema.load_file(args.manifest)
    digest = schema.manifest_hash(data)
    # the pipe is the protocol's: a cub's print() goes to its log, never between two messages
    wire_in, wire_out = sys.stdin.buffer, sys.stdout.buffer
    sys.stdout = sys.stderr
    entry = f"{args.src.rstrip('/')}/{args.entry}"
    spec = importlib.util.spec_from_file_location("cub_main", entry)
    if spec is None or spec.loader is None:
        print(f"bears_cub: cannot load {args.entry}", file=sys.stderr)
        return 2
    module = importlib.util.module_from_spec(spec)
    sys.modules["cub_main"] = module
    spec.loader.exec_module(module)
    session = Session(the_cub(), cub_id=str(data.get("id")), version=str(data.get("version")),
                      manifest_hash=digest, rfile=wire_in, wfile=wire_out)
    return session.serve()


if __name__ == "__main__":
    code = main()
    # the reader thread may still be in a read on stdin: leave without the interpreter's
    # shutdown, which would wait on that read's lock (and abort)
    import os
    sys.stderr.flush()
    os._exit(code)
