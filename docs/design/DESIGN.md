# Design principles

Kranto is a self-hosted app that watches the sources you choose with cheap model calls, keeps
what is worth remembering in an append-only library, maps it into themes and turns those into
idea cards, briefs and posts. The principles below are the constraints every change is checked
against. [DECISIONS.md](DECISIONS.md) holds the evidence behind each of them, and
[OPERATING.md](../OPERATING.md) describes the current architecture and how to run it.

Most of these were learned in an earlier, private experiment, Parallax; the numbers in brackets
refer to its experiments. [VISION.md](VISION.md) explains the idea they serve.

---

**Judgment**

1. **Decomposed ratings, multiplied in code.** The model returns `content_quality`,
   `durability` and `opportunity` in [0,1]; code computes `signal` as their product. A single
   self-reported score collapsed to 46% of observations at exactly 0.62 (experiment 10);
   decomposition raised distinct values from 7% to 67%.
2. **Skip is the default.** `{"skip": true}` is a first-class answer. Gate at
   `signal >= 0.20` (experiment 4). `override` with a mandatory `override_reason` lets through
   things the ratings miss; since October 2026 only for an item rated at least 0.3 on every
   rating with a signal of at least a quarter of the gate, so an override cannot empty it.
3. **The prompt is substrate.** [TENETS](TENETS.md) are included in every intern call. "You are
   not trying to be interesting. You are trying to be honest." The summary must carry concrete
   detail: retrieval can only find what the intern wrote down (experiment 14).
4. **Tolerant parsing over prompt coercion.** Strip fences, take the first balanced object; a
   fenced skip is a skip (experiment 16: Haiku fenced about a third of its replies despite
   instructions).
5. **Never score length or keywords** (experiment 4).

**Audit**

6. **Every model call is recorded**: request, raw response, model, tokens, cost, outcome
   (`contributed | gated | skipped | parse_failed | llm_error`). Observations reference their
   call. Non-negotiable.
7. **Append-only is enforced, not conventional.** SQLite triggers reject UPDATE on library
   tables, and DELETE except inside the recorded purge path. Corrections are new rows with
   `supersedes`. The library never mints ids from content it has not seen. Observations and the
   raw third-party text behind them expire after a retention window and are compacted into
   rollups; each removal is recorded.
8. **Embed once at write time; record the model per row.** nomic-embed-text-v1.5, truncated to
   384 dimensions and renormalised, with `search_document:` / `search_query:` prefixes. Never
   mix models in one index; a model change is a new index, not a rewrite.
9. **A verbatim, non-model source excerpt and URL on every observation.**

**Measurement honesty**

10. **Permutation nulls, not convenient baselines.** An early headline result fell from 356x to
    1.4x against a proper null. Check that the null can fail before quoting it (experiment 18).
11. **Report cluster quality in both spaces.** A UMAP-10d silhouette looked like 0.40; in the
    native 384-d space it was 0.067 (experiment 18).
12. **Cross-source means no single source supplies more than 70% of a cluster.** Show the source
    mix wherever a cluster is shown.
13. **Trajectories use shares, not counts,** with the artifact checks: proportional baseline,
    single-source dominance, source-mix shift. In a library that only grows, raw-count slopes
    are always positive; an earlier article generator made exactly that mistake.
14. **Retrieval has a noise floor.** Off-topic queries scored 0.64-0.66 (experiment 14); weak
    matches are labelled weak.
15. **Visuals say what they are.** The density layer is a kernel density estimate over 2-d
    coordinates, not a spectrum.

**Map**

16. **Re-cluster from scratch every snapshot.** Cluster ids are ephemeral; everything durable
    anchors on observation ids (experiment 19).
17. **Identity across snapshots via raw-space centroids,** greedy match under cosine distance
    0.15; never via UMAP coordinates.
18. **Pin determinism** (seeds, `n_init`), clamp parameters for tiny corpora, and fingerprint
    the corpus (sha256 of sorted ids plus model) on every derived artifact.

**Economics**

19. **Inference is a step function** ([VISION](VISION.md)). Tier 0: a local embedding
    prefilter, free. Tier 1: a cheap model screens and judges. Tier 2: a stronger model only
    for work that needs it, such as idea cards and explanations, on request or on a schedule
    with a budget.
20. **All spend goes through one metered client.** Pause and budget are checked before every
    call, not once per run. Unknown pricing is an error, not $0.
21. **Items over the per-run cap roll over, unmarked.** An item is marked seen only after a
    terminal outcome; `llm_error` never consumes an item.

**Shape**

22. **The library is shared; topics are lenses.** An observation belongs to the library, not to
    a topic. Cross-pollination between topics is the point ([VISION](VISION.md),
    "Cross-pollination between topics").
