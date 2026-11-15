"""S6 to S8: a cub that writes the protocol by hand, to break it. It says hello properly,
then misbehaves as the job's method asks; what the host answered goes into its log."""
import json
import os
import sys

sys.path.insert(0, "/opt/kranto/sdk")
from bears_cub import schema  # noqa: E402

LOG = []


def send(obj):
    os.write(1, (json.dumps(obj) + "\n").encode())


def raw(data: bytes):
    os.write(1, data)


def recv():
    buf = b""
    while not buf.endswith(b"\n"):
        part = os.read(0, 1)
        if not part:
            os._exit(0)
        buf += part
    return json.loads(buf)


def call(mid, method, params):
    send({"jsonrpc": "2.0", "id": mid, "method": method, "params": params})
    while True:
        msg = recv()
        if msg.get("id") == mid:
            return msg


data = schema.load_file("/cub/src/cub.yaml")
hello = call(1, "hello", {"api": "cub/1", "id": data["id"], "version": data["version"],
                          "manifest_hash": schema.manifest_hash(data), "sdk": "1.0.0",
                          "python": "3", "handlers": {"jobs": [j["method"] for j in data["jobs"]],
                                                      "events": [], "actions": [], "reads": [],
                                                      "stages": []}})
nid = 10
while True:
    req = recv()
    if "id" not in req:
        continue
    how = req["params"]["method"]
    if how == "in_flight":
        for i in range(10):
            send({"jsonrpc": "2.0", "id": 100 + i, "method": "settings.get", "params": {}})
    elif how == "calls":
        for i in range(2100):
            send({"jsonrpc": "2.0", "id": 100 + i, "method": "settings.get", "params": {}})
            recv()
    elif how == "logs":
        for i in range(1500):
            call(100 + i, "log", {"level": "info", "message": f"line {i}"})
        send({"jsonrpc": "2.0", "id": req["id"], "result": {"line": "logged"}})
    elif how == "no_newline":
        raw(b"x" * (2 * 1024 * 1024))
    elif how == "long_line":
        raw(b'{"jsonrpc": "2.0", "id": 5, "method": "log", "params": {"level": "info", '
            b'"message": "' + b"x" * (5 * 1024 * 1024) + b'"}}\n')
    elif how == "not_json":
        for _ in range(3):
            raw(b"not json\n")
        recv()
    elif how == "probes":
        out = {}
        raw(b'[{"jsonrpc": "2.0", "id": 50, "method": "log", "params": {}}]\n')
        out["batch"] = recv().get("error", {}).get("code")
        out["string_id"] = call("h1", "settings.get", {}).get("error", {}).get("code")
        out["hello_twice"] = call(51, "hello", {}).get("error", {}).get("code")
        out["params_list"] = call(52, "events.publish", ["raw.said", {}]).get(
            "error", {}).get("code")
        send({"jsonrpc": "2.0", "id": req["id"], "result": {"summary": out}})
    elif how == "no_result":
        send({"jsonrpc": "2.0", "id": req["id"]})
    else:
        send({"jsonrpc": "2.0", "id": req["id"], "result": {}})
