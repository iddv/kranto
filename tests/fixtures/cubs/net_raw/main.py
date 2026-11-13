"""S4: sockets go nowhere; http.fetch goes where it is declared, by Kranto."""
import socket

from bears_cub import Cub, HostError

cub = Cub()


def attempt(fn):
    try:
        fn()
        return "connected"
    except OSError as exc:
        return exc.__class__.__name__
    except HostError as exc:
        return exc.code


@cub.job("probe")
def probe(ctx):
    out = {"loopback_8765": attempt(lambda: socket.create_connection(("127.0.0.1", 8765), 2)),
           "public_443": attempt(lambda: socket.create_connection(("1.1.1.1", 443), 2)),
           "dns": attempt(lambda: socket.getaddrinfo("example.com", 443))}
    for label, url in (("undeclared", "https://example.org/"),
                       ("ip", "https://127.0.0.1/"),
                       ("plain_http", "http://github.com/"),
                       ("port", "https://github.com:8443/")):
        out[label] = attempt(lambda u=url: ctx._transport("http.fetch", {"url": u}))
    got = ctx.http.get("https://api.github.com/zen")
    out["subdomain"] = [got["status"], got["text"]]
    return {"summary": out}
