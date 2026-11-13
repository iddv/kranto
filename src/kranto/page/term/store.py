"""Sessions on disk: ``<loop home>/term/<tid>/session.json``, one folder per session (0700),
written whole and atomically. A record outlives its process: after a restart or an idle end,
Open again resumes the same conversation in the same working directory."""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from pathlib import Path

TID_HEX = 4                                         # c3f1a9e2


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.lock = threading.RLock()

    def dir(self, tid: str) -> Path:
        if not valid_tid(tid):
            raise KeyError(tid)
        return self.root / tid

    def new_tid(self) -> str:
        while True:
            tid = secrets.token_hex(TID_HEX)
            if not (self.root / tid).exists():
                return tid

    def get(self, tid: str) -> dict | None:
        try:
            return json.loads((self.dir(tid) / "session.json").read_text())
        except (OSError, ValueError, KeyError):
            return None

    def put(self, rec: dict) -> dict:
        with self.lock:
            d = self.dir(rec["tid"])
            d.mkdir(parents=True, exist_ok=True)
            os.chmod(d, 0o700)
            rec["updated"] = time.time()
            tmp = d / f".session.{os.getpid()}.{threading.get_ident()}.tmp"
            tmp.write_text(json.dumps(rec, indent=1))
            os.replace(tmp, d / "session.json")
            return rec

    def update(self, tid: str, **fields) -> dict:
        with self.lock:
            rec = self.get(tid)
            if rec is None:
                raise KeyError(tid)
            rec.update(fields)
            return self.put(rec)

    def all(self) -> list[dict]:
        if not self.root.is_dir():
            return []
        out = [r for r in (self.get(p.name) for p in self.root.iterdir()
                           if p.is_dir() and valid_tid(p.name)) if r]
        return sorted(out, key=lambda r: r.get("created") or 0, reverse=True)

    def by_subject(self, key: str) -> dict | None:
        """The subject's session that has not been ended for good (End removes it)."""
        return next((r for r in self.all() if r.get("key") == key and not r.get("removed")),
                    None)


def valid_tid(tid) -> bool:
    return isinstance(tid, str) and len(tid) == 2 * TID_HEX and all(
        c in "0123456789abcdef" for c in tid)
