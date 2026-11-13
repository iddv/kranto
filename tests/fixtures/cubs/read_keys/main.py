"""S3: a family it lacks, the host's settings, the files above its folder, a key it never set."""
import json

from bears_cub import Cub, HostError, NotGranted

cub = Cub()


def code(fn):
    try:
        fn()
        return "ok"
    except HostError as exc:
        return exc.code


@cub.job("probe")
def probe(ctx):
    out = {"library_sdk": code(lambda: ctx.read.get("library.observations")),
           "library_host": code(lambda: ctx._transport("reads.get",
                                                       {"name": "library.observations",
                                                        "params": {}})),
           "kv_secret": code(lambda: ctx._call("kv.get", {"key": "secret"}))}
    values = ctx._call("settings.get", {})
    out["settings"] = json.dumps(values)
    for path in ("/cub/src/../../.env", "/cub/.env", "/.env"):
        try:
            with open(path) as f:
                f.read()
            out[path] = "read"
        except OSError as exc:
            out[path] = exc.errno
    out["not_granted_class"] = NotGranted.__name__
    return {"summary": out}
