"""What an install shows before the owner's confirm (step 4,): the tree's
checks (rule 10), its inventory and findings, the manifest in words, and for an update
the permission delta and the files' diff.

The words here are the source of truth for the install dialog and the command line; the page
draws them as they are (``words``). A finding never refuses an install by itself: the sandbox
is the boundary, and a finding says what the code tries (``imports socket``: it has no network,
so the import does nothing, or hides a try).
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

from ...scrub import secret_shaped
from . import files

# a tree never holds these (the venv is built apart from it and may hold compiled wheels)
NATIVE_SUFFIXES = (".so", ".dll", ".dylib", ".exe", ".pyd", ".bin")
SKIPPED_DIRS = (".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".venv")
TEXT_SUFFIXES = (".py", ".yaml", ".yml", ".json", ".toml", ".txt", ".md", ".cfg", ".ini", "")
RISKY = {
    "socket": "it has no network, so this does nothing, or hides a try",
    "subprocess": "it can start programs only inside its sandbox, with no network",
    "ctypes": "it can call native code inside its sandbox",
    "multiprocessing": "its processes count against its limit",
    "urllib": "it has no network: only Kranto's fetch reaches the web",
    "http": "it has no network: only Kranto's fetch reaches the web",
    "requests": "it has no network: only Kranto's fetch reaches the web",
    "httpx": "it has no network: only Kranto's fetch reaches the web",
}
LICENCES = ((r"Apache License\s*\n?\s*Version 2\.0", "Apache-2.0"),
            (r"MIT License|Permission is hereby granted, free of charge", "MIT"),
            (r"Redistribution and use in source and binary forms", "BSD"),
            (r"Mozilla Public License,? v(?:ersion)?\.? ?2\.0", "MPL-2.0"),
            (r"GNU AFFERO GENERAL PUBLIC LICENSE", "AGPL"),
            (r"GNU LESSER GENERAL PUBLIC LICENSE", "LGPL"),
            (r"GNU GENERAL PUBLIC LICENSE", "GPL"),
            (r"This is free and unencumbered software", "Unlicense"),
            (r"All rights reserved", "proprietary"))
SERVICE_NAMES = {"newsletter": "Newsletter", "mastodon": "Mastodon (posting)"}
# Whose connection a service's calls are made with, in words: the newsletter's is whichever
# platform the owner connects, so it is never named here.
SERVICE_CONNECTIONS = {"newsletter": "your newsletter platform's connection"}


def _service_words(service: str) -> tuple[str, str]:
    from ... import newsletter
    if service in newsletter.legacy_services():
        service = "newsletter"                 # an earlier release's name for the service
    name = SERVICE_NAMES.get(service, service)
    return name, SERVICE_CONNECTIONS.get(service, f"your {name} connection")


class TreeError(ValueError):
    """A tree Kranto refuses to stage, in words."""


# -- the tree -------------------------------------------------------------------------------------


def walk(tree: Path) -> list[str]:
    """Every file of the tree by relative path, after its checks (rules 8 and 10): at most
    3,000 files and 40 MiB; a symlink only to a file inside it; nothing that runs outside
    Python (a native library, an ELF or PE program, a script marked executable)."""
    tree = Path(tree)
    out: list[str] = []
    size = 0
    real = os.path.realpath(tree)
    for dirpath, dirnames, filenames in os.walk(tree, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIPPED_DIRS)
        for name in [*dirnames, *filenames]:
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                target = os.path.realpath(full)
                if os.path.commonpath([real, target]) != real:
                    rel = os.path.relpath(full, tree)
                    raise TreeError(f"{rel} is a link out of the folder (to {os.readlink(full)})")
        for name in sorted(filenames):
            full = Path(dirpath) / name
            rel = full.relative_to(tree).as_posix()
            if full.is_symlink():
                continue
            if full.suffix.lower() in NATIVE_SUFFIXES:
                raise TreeError(f"{rel} is a native library or program: a cub is Python only "
                                "(its packages come from requirements.txt)")
            st = full.stat()
            with open(full, "rb") as f:
                head = f.read(4)
            if head == b"\x7fELF" or head[:2] == b"MZ" and full.suffix not in TEXT_SUFFIXES[:-1]:
                raise TreeError(f"{rel} is a program (ELF or PE): a cub is Python only")
            if head[:2] == b"#!" and st.st_mode & 0o111:
                raise TreeError(f"{rel} is a script marked executable: a cub runs nothing but "
                                "its entry, under Kranto")
            size += st.st_size
            out.append(rel)
            if len(out) > files.MAX_FILES:
                raise TreeError(f"more than {files.MAX_FILES:,} files")
            if size > files.MAX_BYTES:
                raise TreeError(f"more than {files.MAX_BYTES // 1024 // 1024} MiB")
    return out


def copy_tree(src: Path, dest: Path) -> None:
    """``src`` as a cub's tree in ``dest`` (links kept as links: ``walk`` judged them), without
    a checkout's or an editor's leftovers."""
    import shutil
    shutil.copytree(src, dest, symlinks=True,
                    ignore=shutil.ignore_patterns(*SKIPPED_DIRS, "*.pyc"))


# -- the inventory --------------------------------------------------------------------------------


def licence_of(tree: Path) -> str:
    found = sorted(p for p in Path(tree).iterdir()
                   if p.is_file() and re.match(r"(LICEN[CS]E|COPYING)", p.name, re.I))
    if not found:
        return "unknown"
    text = found[0].read_text(errors="replace")[:4000]
    for pattern, name in LICENCES:
        if re.search(pattern, text, re.I):
            return name
    return "unknown"


def _imports(source: str) -> tuple[set[str], list[str]]:
    """The top-level modules a file imports anywhere in it, and what it does that hides an
    import or runs text as code."""
    mods: set[str] = set()
    tricks: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return mods, ["does not parse as Python"]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            mods.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else fn.attr \
                if isinstance(fn, ast.Attribute) else None
            if name in ("__import__", "import_module", "exec", "eval", "compile"):
                tricks.append(f"calls {name}")
            if name == "open" and node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str) and node.args[0].value.startswith("/"):
                tricks.append(f"opens {node.args[0].value[:80]}")
    return mods, tricks


def inventory(tree: Path, paths: list[str]) -> dict:
    """Files and bytes, the modules its code imports, its findings, its licence."""
    tree = Path(tree)
    imports: set[str] = set()
    findings: list[dict] = []
    size = 0
    for rel in paths:
        p = tree / rel
        size += p.stat().st_size
        if p.suffix.lower() not in TEXT_SUFFIXES or p.stat().st_size > 1_000_000:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if secret_shaped(text):
            findings.append({"level": "warn", "text": f"{rel} holds a string shaped like a key "
                                                      "or token"})
        if p.suffix == ".py":
            mods, tricks = _imports(text)
            imports |= mods
            findings += [{"level": "warn", "text": f"{rel} {t}"} for t in sorted(set(tricks))]
    for mod in sorted(imports & set(RISKY)):
        findings.append({"level": "warn", "text": f"imports {mod}: {RISKY[mod]}"})
    return {"files": len(paths), "bytes": size, "imports": sorted(imports),
            "findings": findings, "licence": licence_of(tree)}


def diff(old: Path | None, new: Path) -> dict:
    """Files added, removed and changed between the installed tree and the staged one."""
    def hashes(root: Path | None) -> dict[str, str]:
        if root is None or not root.is_dir():
            return {}
        return {p.relative_to(root).as_posix(): files.file_hash(p)
                for p in sorted(root.rglob("*")) if p.is_file() and not p.is_symlink()
                and not set(p.relative_to(root).parts) & set(SKIPPED_DIRS)}
    a, b = hashes(old), hashes(new)
    added = sorted(set(b) - set(a))
    removed = sorted(set(a) - set(b))
    changed = sorted(k for k in set(a) & set(b) if a[k] != b[k])
    return {"added": added[:40], "removed": removed[:40], "changed": changed[:40],
            "counts": {"added": len(added), "removed": len(removed), "changed": len(changed)}}


# -- the permission delta -------------------------------------------------------------------------


def _items(grants: dict) -> dict[str, set[str]]:
    """Each grant block as a set of comparable items. A kind or a broker service under an
    earlier release's name compares as its own (an alias is not a new permission)."""
    from ... import newsletter
    from .. import tickets
    tickets.kind_names()
    old_services = newsletter.legacy_services()
    g = grants or {}
    ev = g.get("events") or {}
    model = g.get("model") or {}
    out = {"reads": set(g.get("reads") or []),
           "events.publish": set(ev.get("publish") or []),
           "events.subscribe": {f"{s.get('kind')} (from {s.get('min_trust', 'unreviewed')})"
                                for s in ev.get("subscribe") or []},
           "model": {f"tier {t}" for t in model.get("tiers") or []}
           | {f"purpose {p}" for p in model.get("purposes") or []},
           "search": set(g.get("search") or []),
           "http": set((g.get("http") or {}).get("hosts") or []),
           "broker": {f"{'newsletter' if s in old_services else s} {o}"
                      for s, ops in (g.get("broker") or {}).items() for o in ops},
           "requests": {tickets.canonical(k) for k in g.get("requests") or []},
           "storage": {"own"} if g.get("storage", "own") == "own" else set(),
           "stages": set(g.get("stages") or [])}
    return out


def delta(old: dict, new: dict) -> dict:
    """What an update adds and removes, block by block: ``grown`` when anything is added (the
    house confirm, and every kind back to dry), ``high_trust`` when the cub may ask for a
    send or use a broker, ``same`` when nothing changes."""
    a, b = _items(old), _items(new)
    added = {k: sorted(b[k] - a[k]) for k in b if b[k] - a[k]}
    removed = {k: sorted(a[k] - b[k]) for k in a if a[k] - b[k]}
    cap_old = (old.get("model") or {}).get("monthly_usd")
    cap_new = (new.get("model") or {}).get("monthly_usd")
    if cap_new is not None and (cap_old is None or cap_new > cap_old) and cap_new != cap_old:
        added.setdefault("model", []).append(f"up to ${cap_new:g} a month")
    high = bool(new.get("requests") or new.get("broker"))
    return {"added": added, "removed": removed, "grown": bool(added), "high_trust": high,
            "same": not added and not removed}


# -- the manifest in words ------------------------------------------------------------------------


def words(m: dict, grants: dict, *, trust: str, cap_usd: float | None = None,
          topics: list[str] | None = None) -> list[list[str]]:
    """The install dialog's lines, ``[label, sentence]``, from the manifest and its grants."""
    from .. import tickets
    out: list[list[str]] = [["Cub", f"{m.get('title') or m['id']} {m['version']} ({m['id']})"],
                            ["Says", str(m.get("says") or "")]]
    if trust == "unreviewed":
        out.append(["Trust", "Nobody at Kranto has read this code. It runs in a sandbox with "
                             "only what is listed below."])
    elif trust == "owner":
        out.append(["Trust", "Yours: installed from a folder on this machine."])
    else:
        out.append(["Trust", trust])
    if grants.get("reads"):
        where = f" (only topics {', '.join(topics)})" if topics else ""
        out.append(["Reads", f"your library's {', '.join(grants['reads'])}{where}"])
    ev = grants.get("events") or {}
    if ev.get("subscribe"):
        out.append(["Listens for", ", ".join(s["kind"] for s in ev["subscribe"])])
    if ev.get("publish"):
        out.append(["Says on the bus", ", ".join(ev["publish"])])
    model = grants.get("model") or {}
    if model.get("purposes"):
        cap = "no cap of its own" if cap_usd is None else f"at most ${cap_usd:g} a month"
        out.append(["Model", f"{', '.join(model['tiers'] or [])} tier for "
                             f"{', '.join(model['purposes'])}, {cap}"])
    if grants.get("search"):
        out.append(["Searches", f"the web ({', '.join(grants['search'])}), through Kranto"])
    hosts = (grants.get("http") or {}).get("hosts") or []
    if hosts:
        out.append(["Fetches", f"pages from {', '.join(hosts)}, through Kranto"])
    for service, ops in (grants.get("broker") or {}).items():
        name, conn = _service_words(service)
        out.append([name, f"through Kranto, with {conn}, which it never sees: "
                          f"{', '.join(ops)}"])
    for kind in grants.get("requests") or []:
        spec = tickets.KINDS.get(kind)
        title = spec.title if spec else kind
        cap = f", at most {spec.per_day} a day" if spec else ""
        out.append(["Asks you", f"{title} ({kind}){cap}: each waits for your approval, and is "
                                "practice until you turn on Send for real"])
    if grants.get("storage", "own") == "own":
        out.append(["Keeps", "its own data in Kranto (8 MiB unless you change it)"])
    for job in m.get("jobs") or []:
        out.append(["Runs", job.get("says") or f"{job['kind']} every {job['every_hours']:g} h"])
    from bears_cub.widgets import describe
    for w in (m.get("ui") or {}).get("widgets") or []:
        out.append(["Shows on your home, if you add it", describe(w)])
    out.append(["It cannot", "read your files, your keys or another cub's data, reach the "
                             "network except through Kranto, or send anything without your "
                             "approval"])
    return out
