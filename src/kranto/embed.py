"""Text embeddings.

Production uses nomic-embed-text-v1.5 through fastembed (ONNX, CPU), with
Matryoshka truncation from 768 to 384 dimensions and renormalisation. Nomic
is trained with task prefixes: stored text is embedded as
``search_document: ...`` and queries as ``search_query: ...``. Mixing them up
degrades retrieval quietly, so the two paths are separate methods.

Vectors are float32 and unit-norm, so cosine similarity is a dot product.
One library uses one embedding model; ``model_name`` is recorded on every row.

Memory (MEM, 2026-10-20). A model run's working memory grows with the batch times the square
of its longest text: fastembed's default batch of 256, padded to the longest, put a first
backfill (40 texts of about 630 tokens in one batch) past 3 GB, and onnxruntime's CPU arena
kept that peak for the life of the process. So texts are embedded shortest first in small
batches whose size times longest length squared stays under ``BATCH_BUDGET``, the arena is
off (memory goes back after each run), one run happens at a time per embedder (the server
shares one between its jobs and requests), and a text is read up to ``MAX_TOKENS`` (the
prefilter's text is at most 2000 characters, about 600 tokens; longer text has never been
embedded by any caller, so no stored vector changes).
"""

from __future__ import annotations

import contextlib
import hashlib
import re
import threading
import time
from typing import Protocol

import numpy as np

EMBED_DIM = 384
NOMIC_MODEL = "nomic-ai/nomic-embed-text-v1.5"
NOMIC_MODEL_NAME = "nomic-embed-text-v1.5@384"
# At most this many texts a model run, and at most this many characters squared times the
# texts in it (four texts of 2,100 characters, measured at about +470 MB over the loaded
# model; a batch of 40 such texts went past 3 GB).
MAX_BATCH = 4
BATCH_BUDGET = 4 * 2100 ** 2
MAX_TOKENS = 1024
# A server lets go of the model after this long unused (NomicEmbedder.drop_if_idle).
IDLE_SECONDS = 600


class Embedder(Protocol):
    model_name: str
    dim: int

    def embed_documents(self, texts: list[str]) -> np.ndarray: ...

    def embed_query(self, text: str) -> np.ndarray: ...


def _normalise_rows(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (matrix / norms).astype(np.float32)


@contextlib.contextmanager
def _no_prepacking():
    """While the model loads, its session also skips prepacking: onnxruntime otherwise keeps
    a second, repacked copy of the weights (the loaded model measured 871 MB with it, 581 MB
    without, no slower). fastembed exposes only the arena option, so its hook for session
    options is extended here; a fastembed without that hook loads as before."""
    try:
        from fastembed.common.onnx_model import OnnxModel
        base = OnnxModel.__dict__["add_extra_session_options"].__func__
    except (ImportError, KeyError, AttributeError):
        yield
        return

    def add(cls, session_options, extra_options):
        base(cls, session_options, extra_options)
        session_options.add_session_config_entry("session.disable_prepacking", "1")

    # fastembed's own hook, patched for the block and put back after it
    OnnxModel.add_extra_session_options = classmethod(add)  # type: ignore[method-assign,assignment]
    try:
        yield
    finally:
        OnnxModel.add_extra_session_options = classmethod(base)  # type: ignore[method-assign,assignment]


def batches(texts: list[str]) -> list[list[int]]:
    """The indexes of ``texts`` in model runs: shortest first (a batch is padded to its
    longest), at most ``MAX_BATCH`` a run and at most ``BATCH_BUDGET`` characters squared
    times the texts in it; a text past the budget on its own runs alone."""
    out: list[list[int]] = []
    for i in sorted(range(len(texts)), key=lambda i: len(texts[i])):
        longest = len(texts[i]) ** 2                    # sorted: the newcomer is the longest
        if out and len(out[-1]) < MAX_BATCH and (len(out[-1]) + 1) * longest <= BATCH_BUDGET:
            out[-1].append(i)
        else:
            out.append([i])
    return out


class NomicEmbedder:
    model_name = NOMIC_MODEL_NAME

    def __init__(self, dim: int = EMBED_DIM, cache_dir: str | None = None, *,
                 factory=None) -> None:
        self.dim = dim
        self._cache_dir = cache_dir
        self._model = None
        self._factory = factory
        self._lock = threading.Lock()
        self._used = 0.0

    def _load(self):
        if self._model is None:
            factory = self._factory
            if factory is None:
                from fastembed import TextEmbedding as factory
            kwargs = {"cache_dir": self._cache_dir} if self._cache_dir else {}
            with _no_prepacking():
                self._model = factory(NOMIC_MODEL, enable_cpu_mem_arena=False, **kwargs)
            tokenizer = getattr(getattr(self._model, "model", None), "tokenizer", None)
            if tokenizer is not None:
                tokenizer.enable_truncation(max_length=MAX_TOKENS)
        return self._model

    def _embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        with self._lock:
            model = self._load()
            for batch in batches(texts):
                full = np.asarray(list(model.embed([texts[i] for i in batch],
                                                   batch_size=len(batch))), dtype=np.float32)
                out[batch] = full[:, : self.dim]
            self._used = time.monotonic()
        return _normalise_rows(out)

    def drop_if_idle(self, idle_seconds: float | None = None) -> bool:
        """Let go of the model when it has not been used for ``idle_seconds``: a server reads
        its sources every few hours, and between reads the model was most of its memory
        (measured: 649 MB with it, 98 MB without). The next embed loads it again (2 to 3 s).
        True when it was dropped. ``idle_seconds``: ``IDLE_SECONDS`` by default."""
        idle_seconds = IDLE_SECONDS if idle_seconds is None else idle_seconds
        if self._model is None or time.monotonic() - self._used < idle_seconds:
            return False
        if not self._lock.acquire(blocking=False):
            return False                                # an embed is running: it is not idle
        try:
            self._model = None
        finally:
            self._lock.release()
        return True

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self._embed([f"search_document: {t}" for t in texts])

    def embed_query(self, text: str) -> np.ndarray:
        return self._embed([f"search_query: {text}"])[0]


_TOKEN = re.compile(r"[a-z0-9]+")


class StubEmbedder:
    """Deterministic embeddings for tests, with no model download.

    Uses the hashing trick over lowercase word tokens: texts that share words
    get similar vectors, so search and clustering tests exercise real geometry.
    """

    model_name = "stub-hashing@384"

    def __init__(self, dim: int = EMBED_DIM) -> None:
        self.dim = dim

    def _vector(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        for token in _TOKEN.findall(text.lower()):
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "little") % self.dim
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[index] += sign
        if not vec.any():
            vec[0] = 1.0
        return vec

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return _normalise_rows(np.stack([self._vector(t) for t in texts]))

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_documents([text])[0]
