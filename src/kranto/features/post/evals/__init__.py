"""The prose eval: today's writers against the prose engine, on 20 real
items (10 News brief items, 10 idea cards: ``items.json``), as a blog post and as a Mastodon post.

- ``writers.py`` builds both prompts: the old one exactly as the writers made it before 
  (one tone sentence), and the new one through ``kranto.prose.compose`` with the writers' own
  task lines (read from the cubs' ``main.py``, so they cannot drift apart).
- ``score.py`` turns recorded answers into the scorecard: the checker's score and flags, the
  rhythm against a reference voice card, the share of invented first-person claims (P-5: the
  target is 0) and the blind pairwise judgement.
- ``recorded.json`` holds one live run's answers; ``tests/test_prose_eval.py`` replays it in CI
  with no model.
- ``live.py`` makes a new recording by hand, under a cost cap:
  ``python -m kranto.features.post.evals.live --home <a scratch kranto home> --budget 3``.

Round 2: ``round2.py`` writes each of ten items once from each of three
proposed angles and marks every draft with ``rubric.py`` (the owner's eight rules, P-12);
``recorded2.json`` is its recording, ``owner_read_1.json`` the owner's round-1 read (the
checker's fixtures and the judge's check); ``outline.py`` measures how alike the drafts' shapes
are; ``export.py`` and ``readpage.py`` let any model write from the same prompts and build the
blind page from any set of drafts (``python -m kranto.features.post.evals export|read``).
"""
