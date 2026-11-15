"""An error, scrubbed: what Kranto may say about an exception outside this process.

One function for every place an error leaves Kranto: the error reports in usage telemetry
(``telemetry/errors.py``), Send this error and ``kranto report``.

``scrub(exc)`` gives a ``Trace``:

- ``type``: the exception's class, as ``TypeError`` (a built-in), ``sqlite3.OperationalError``
  (a library's: its top package and the class), or ``kranto.telemetry.TelemetryError``;
  a class from anywhere else is said as ``Exception``;
- ``frames``: the stack, outermost first. Kranto's own frames (``the server``, ``the page``,
  ``kranto``, ``bears_cub``) as ``module.function:line``; a run of frames from one library
  collapsed to ``[package]`` (``[starlette]``, ``[sqlite3]``); a frame from anywhere else as
  ``[other]``. Never a file path, a value or a local variable;
- ``message``: the exception's message reduced to a template: a word survives only if it is in
  the list of words error messages are made of (``message_word`` in the telemetry allow-list:
  ``object``, ``attribute``, ``NoneType``, ``__format__`` ...), a number becomes ``<n>`` and
  every other word ``<x>``. A name, a path, an address, an email, a key or an id cannot be
  spelled with those words, so none survives;
- ``signature``: 16 hex characters of the SHA-256 of the type and Kranto's own frames without
  their line numbers, so the same error keeps its signature from one release to the next.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import sysconfig
import traceback
from dataclasses import dataclass
from functools import lru_cache

OWN = ("kranto", "kranto.page", "kranto", "bears_cub")
MAX_FRAMES = 40
MAX_MESSAGE = 200
_PART = re.compile(r"[a-z_][a-z0-9_]{0,40}")
_FUNC = re.compile(r"[A-Za-z_<>][A-Za-z0-9_<>]{0,60}")
_PKG = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,59}")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_WORD = re.compile(r"[A-Za-z0-9_]+")
_SEPS = frozenset(" '\"(),.:;[]=-")
_RUN = re.compile(r"<[xn]>(?:[-.:_=]?<[xn]>)+")
_CONTRACTION = re.compile(r"(?<=[A-Za-z])'(?=[a-z]\b)")
_QUOTED = re.compile(r"'[^'\n]{0,300}'|\"[^\"\n]{0,300}\"")
_JOINERS = re.compile(r"[/\\@?&#%+~$|]")


@dataclass(frozen=True)
class Trace:
    type: str
    frames: tuple[str, ...]
    message: str
    signature: str

    @property
    def stack(self) -> str:
        """The frames on one line, outermost first: ``a:12 > [starlette] > b:40``."""
        return " > ".join(self.frames)

    def as_dict(self) -> dict:
        return {"type": self.type, "stack": self.stack, "message": self.message,
                "signature": self.signature}


# -- where a file belongs ------------------------------------------------------------------

@lru_cache(maxsize=1)
def _own_roots() -> tuple[tuple[str, str], ...]:
    """Each of Kranto's packages, by the directory it is installed in."""
    import importlib.util

    out = []
    for name in OWN:
        try:
            spec = importlib.util.find_spec(name)
        except (ImportError, ValueError):
            continue
        for loc in (spec.submodule_search_locations or ()) if spec else ():
            out.append((os.path.realpath(loc), name))
    return tuple(out)


@lru_cache(maxsize=1)
def _lib_roots() -> tuple[tuple[str, bool], ...]:
    """Where libraries live: ``(directory, is the standard library)``, the longest first, so
    a virtualenv's site-packages under the standard library's prefix wins."""
    import contextlib
    import site

    roots: dict[str, bool] = {}
    dirs = []
    with contextlib.suppress(AttributeError):      # an embedded or old interpreter
        dirs += site.getsitepackages()
    with contextlib.suppress(AttributeError):
        dirs.append(site.getusersitepackages())
    paths = sysconfig.get_paths()
    dirs += [paths.get("purelib"), paths.get("platlib")]
    dirs += [p for p in sys.path if p and p.rstrip(os.sep).endswith(("site-packages",
                                                                      "dist-packages"))]
    for d in dirs:
        if d:
            roots[os.path.realpath(d)] = False
    for key in ("stdlib", "platstdlib"):
        if paths.get(key):
            roots.setdefault(os.path.realpath(paths[key]), True)
    return tuple(sorted(roots.items(), key=lambda kv: -len(kv[0])))


@lru_cache(maxsize=4096)
def own_module(filename: str) -> str | None:
    """``kranto.page.loop.gate`` for ``<where the page is installed>/loop/gate.py``; None for a
    file outside Kranto's packages."""
    path = os.path.realpath(filename)
    for root, name in _own_roots():
        if path.startswith(root + os.sep) and path.endswith(".py"):
            rest = [name, *path[len(root) + 1:-3].split(os.sep)]
            if rest[-1] == "__init__":
                rest.pop()
            if all(_PART.fullmatch(p) for p in rest[1:]):
                return ".".join(rest)
    return None


@lru_cache(maxsize=4096)
def package_of(filename: str) -> str:
    """The library a file outside Kranto belongs to (its top package or module), or
    ``other``."""
    path = os.path.realpath(filename)
    for root, _stdlib in _lib_roots():
        if path.startswith(root + os.sep):
            top = path[len(root) + 1:].split(os.sep)[0]
            if top.endswith(".py"):
                top = top[:-3]
            if top in ("site-packages", "dist-packages", "lib-dynload"):
                continue
            return top if _PKG.fullmatch(top) else "other"
    return "other"


# -- the parts -----------------------------------------------------------------------------

def frames_of(tb) -> tuple[str, ...]:
    """The scrubbed frames of a traceback, outermost first; the innermost ``MAX_FRAMES`` when
    there are more."""
    out: list[str] = []
    for fs in traceback.extract_tb(tb):
        mod = own_module(fs.filename)
        if mod is not None:
            fn = fs.name if _FUNC.fullmatch(fs.name or "") else "<unknown>"
            out.append(f"{mod}.{fn}:{int(fs.lineno or 0)}")
            continue
        entry = f"[{package_of(fs.filename)}]"
        if not out or out[-1] != entry:
            out.append(entry)
    return tuple(out[-MAX_FRAMES:])


def type_name(exc: BaseException | type) -> str:
    cls = exc if isinstance(exc, type) else type(exc)
    name = cls.__name__ if _NAME.fullmatch(cls.__name__ or "") else ""
    mod = getattr(cls, "__module__", "") or ""
    if not name:
        return "Exception"
    if mod == "builtins":
        return name
    top = mod.split(".")[0]
    if top in OWN:
        parts = mod.split(".")
        if all(_NAME.fullmatch(p) for p in parts):
            return f"{mod}.{name}"
        return f"{top}.{name}"
    module = sys.modules.get(mod)
    filename = getattr(module, "__file__", None)
    if filename and package_of(filename) == top and _NAME.fullmatch(top):
        return f"{top}.{name}"
    if top in sys.stdlib_module_names and _NAME.fullmatch(top):
        return f"{top}.{name}"
    return "Exception"


@lru_cache(maxsize=1)
def vocabulary() -> frozenset[str]:
    """The words a message template may keep (the allow-list's ``message_word``)."""
    from .telemetry import schema

    return frozenset(schema.own()["enums"]["message_word"])


def known_word(word: str, vocab: frozenset[str] | None = None) -> bool:
    vocab = vocab if vocab is not None else vocabulary()
    return word in vocab or word.lower() in vocab


def _words(text: str, vocab: frozenset[str]) -> str:
    """Each word kept or replaced; between words, only the separators and the marks
    (``\\x00`` an apostrophe in a word, ``\\x01`` ``<x>``, ``\\x02`` ``<n>``)."""
    def seps(s: str) -> str:
        return "".join(c if c in _SEPS or c in "\x00\x01\x02" else " " for c in s)

    out, at = [], 0
    for m in _WORD.finditer(text):
        out.append(seps(text[at:m.start()]))
        w = m.group(0)
        out.append(w if known_word(w, vocab) else "\x02" if w.isdigit() else "\x01")
        at = m.end()
    out.append(seps(text[at:]))
    return "".join(out)


def template(message: str, vocab: frozenset[str] | None = None) -> str:
    """``message`` reduced to a template (see the module's doc): a quoted part with any word
    not in the vocabulary is ``'<x>'``; a run of text with a ``/``, ``@``, ``?`` or the like
    (a path, an address, an email) is ``<x>``; then each word not in the vocabulary is
    ``<x>`` (``<n>`` for a number)."""
    vocab = vocab if vocab is not None else vocabulary()
    text = _CONTRACTION.sub("\x00", str(message or "")[:1000])

    def quoted(m: re.Match) -> str:
        q, inner = m.group(0)[0], m.group(0)[1:-1]
        clean = _words(inner, vocab)
        ok = "\x01" not in clean and "\x02" not in clean and not _JOINERS.search(inner)
        return q + (clean if ok else "\x01") + q

    text = _QUOTED.sub(quoted, text)
    text = " ".join("\x01" if _JOINERS.search(chunk) else chunk for chunk in text.split())
    s = _words(text, vocab).replace("\x00", "'").replace("\x01", "<x>").replace("\x02", "<n>")
    s = _RUN.sub("<x>", s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > MAX_MESSAGE:
        s = s[:MAX_MESSAGE]
        cut = s.rfind(" ")
        s = s[:cut] if cut > 0 else ""
    return s


def signature(type_: str, frames: tuple[str, ...] | list[str]) -> str:
    own = [f.rsplit(":", 1)[0] for f in frames if not f.startswith("[")]
    return hashlib.sha256("\n".join([type_, *own]).encode()).hexdigest()[:16]


def scrub(exc: BaseException) -> Trace:
    """The exception as it may leave Kranto. Never raises."""
    try:
        t = type_name(exc)
        frames = frames_of(exc.__traceback__)
        try:
            raw = str(exc)
        except Exception:  # noqa: BLE001 - a message that cannot be made is an empty one
            raw = ""
        return Trace(t, frames, template(raw), signature(t, frames))
    except Exception:  # noqa: BLE001 - the trace of an error never raises one
        return Trace("Exception", (), "", signature("Exception", ()))


def failure(type_: str, message: str = "") -> Trace:
    """A failure known only by a name and a message (a job's run that failed without raising,
    a rolled-back update): no frames."""
    t = type_ if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}(\.[A-Za-z_][A-Za-z0-9_]{0,63}){0,6}",
                              str(type_ or "")) else "Exception"
    return Trace(t, (), template(message), signature(t, ()))
