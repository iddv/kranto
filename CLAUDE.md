# Kranto

Kranto watches the sources you choose, keeps what is worth remembering, and turns it into idea
cards and posts. One Python package, `kranto`: the server (`src/kranto/`), the page
(`src/kranto/page/`, its web UI's source in `src/kranto/page/ui/web/`) and the cub SDK
(`src/bears_cub/`). [CONTRIBUTING.md](CONTRIBUTING.md) has the setup, how work is merged and the
rules the code depends on; `docs/README.md` lists every page.

- Two test suites: `pytest tests` (the server's) and `pytest tests/page` (the page's, with its
  own `tests/page/pytest.ini` and conftest). The page's sources: `npm run check` and `npm test`
  in `src/kranto/page/ui/web`.
- Tests never call a model or the network; use `httpx.MockTransport`, the stubs and the fake
  `claude`s.
- No secret-shaped literals, not even fake ones; build test keys at runtime.
- Library rows are never edited in place; migrations only add, each with its own number.
- Every model call goes through the metered client.
- The page reads the server's library through its JSON API, never its database; the server uses
  the page only through `kranto.page.host_api`.
- The console stays in its sandbox (`src/kranto/page/box/`).
- `docs/design/TENETS.md` (copied in `src/kranto/prompts/`) is sent to the model in every intern
  call: change it only on purpose.
- The product's name and every name computed from it live in `src/kranto/product.py` (and
  `product.ts` for the page). Names from before the rename that an old install still uses live in
  `src/kranto/legacy.py` only. `scripts/ci/scrub.py` holds the tree to both rules.
- Every commit is signed off (`git commit -s`) from a GitHub no-reply address. No tool or agent
  attribution in commits or pull requests.
