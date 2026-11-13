"""A cub's own store (protocol): JSON values of at most 64 KiB under
keys of ``[A-Za-z0-9_.:/-]`` (1 to 200 characters), at most ``cubs.<id>.kv_mb`` (8 MiB) and
10,000 keys a cub, held by the host in ``cub_kv`` (the one mutable cub table: last write wins,
one row a key). ``kranto cub remove --purge`` deletes a cub's rows."""

from __future__ import annotations

import json
import re

from ...store import Store, iso, utcnow

KEY = re.compile(r"[A-Za-z0-9_.:/-]{1,200}")
VALUE_BYTES = 65536
MAX_KEYS = 10000


class KVError(Exception):
    """``code``: the protocol's (-32602 a bad key, -32011 a value too large, -32002 the quota,
    -32006 no such key); ``data`` small and typed."""

    def __init__(self, code: int, message: str, data: dict | None = None) -> None:
        super().__init__(message)
        self.code, self.message, self.data = code, message, data or {}


def _key(key) -> str:
    if not isinstance(key, str) or not KEY.fullmatch(key):
        raise KVError(-32602, "a key is 1 to 200 characters of A-Z a-z 0-9 _ . : / -")
    return key


def get(store: Store, cub: str, key) -> dict:
    r = store.query_one("SELECT value, updated_at FROM cub_kv WHERE cub = ? AND key = ?",
                        (cub, _key(key)))
    if r is None:
        raise KVError(-32006, f"no key {key}")
    return {"value": json.loads(r["value"]), "updated_at": r["updated_at"]}


def total(store: Store, cub: str) -> tuple[int, int]:
    r = store.query_one("SELECT COALESCE(SUM(bytes), 0) AS b, COUNT(*) AS n FROM cub_kv "
                        "WHERE cub = ?", (cub,))
    return int(r["b"]), int(r["n"])


def put(store: Store, cub: str, key, value, *, quota_bytes: int) -> dict:
    key = _key(key)
    try:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        raise KVError(-32602, "a value is JSON") from None
    size = len(text.encode("utf-8"))
    if size > VALUE_BYTES:
        raise KVError(-32011, f"a value is at most {VALUE_BYTES} bytes of JSON",
                      {"limit": VALUE_BYTES, "got": size})
    with store.tx():
        old = store.query_one("SELECT bytes FROM cub_kv WHERE cub = ? AND key = ?", (cub, key))
        used, n = total(store, cub)
        if old is None and n >= MAX_KEYS:
            raise KVError(-32002, f"the store holds {MAX_KEYS} keys at most",
                          {"limit_keys": MAX_KEYS})
        after = used - (int(old["bytes"]) if old else 0) + size
        if after > quota_bytes:
            raise KVError(-32002, "the store is full", {"limit_bytes": quota_bytes,
                                                         "total_bytes": used})
        store.query("INSERT INTO cub_kv (cub, key, value, bytes, updated_at) VALUES "
                    "(?, ?, ?, ?, ?) ON CONFLICT (cub, key) DO UPDATE SET value = excluded.value, "
                    "bytes = excluded.bytes, updated_at = excluded.updated_at",
                    (cub, key, text, size, iso(utcnow())))
    return {"bytes": size, "total_bytes": after}


def delete(store: Store, cub: str, key) -> dict:
    key = _key(key)
    with store.tx():
        had = store.query_one("SELECT 1 FROM cub_kv WHERE cub = ? AND key = ?", (cub, key))
        store.query("DELETE FROM cub_kv WHERE cub = ? AND key = ?", (cub, key))
    return {"deleted": had is not None}


def listing(store: Store, cub: str, *, prefix: str = "", after: str | None = None,
            limit: int = 100) -> dict:
    if not isinstance(prefix, str) or len(prefix) > 200:
        raise KVError(-32602, "prefix is text of at most 200 characters")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise KVError(-32602, "limit is from 1 to 500")
    esc = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    rows = store.query("SELECT key, bytes, updated_at FROM cub_kv WHERE cub = ? AND key LIKE ? "
                       "ESCAPE '\\' AND key > ? ORDER BY key LIMIT ?",
                       (cub, esc + "%", after or "", limit + 1))
    keys = [{"key": r["key"], "bytes": r["bytes"], "updated_at": r["updated_at"]}
            for r in rows[:limit]]
    return {"keys": keys, "more": len(rows) > limit}


def purge(store: Store, cub: str) -> int:
    n = total(store, cub)[1]
    store.query("DELETE FROM cub_kv WHERE cub = ?", (cub,))
    return n
