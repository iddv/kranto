# tests

Everything CI runs. The tests are flat `test_*.py` files found by their prefix
(`test_term_*`, `test_trace_*`, `test_mcp_*`, `test_browser_*`). Nothing here calls a model or
the network: `conftest.py` makes `HOME` a temp dir, refuses connections off loopback and puts
the refusing `claude` and `gh` of `_shims/` first on `PATH`. A test measured at 5 s or more is
marked `slow` from `.test_durations` and runs in CI's `slow` lane. `test_tree.py` keeps what
left with the factory (builds, the loop, projects, maintenance, the lab) out of the tree.

| Beside the tests | What it is |
|---|---|
| `conftest.py`, `__init__.py` | the suite's rules (above) and the lanes' markers |
| `_shims/` | the `claude` and `gh` that refuse |
| `fake_*.py` | stand-ins for Claude Code (print, stream, terminal) and the Anthropic API |
| `app_common.py`, `auth_common.py`, `term_common.py`, `webui.py` | shared helpers: the page's settings folder and app, a signed-in client, a terminal session, the web UI's sources |
| `budget.py`, `budget.js`, `budget_allow.json`, `contrast.js` | the page's size budget and the colour-contrast check the browser tests run |
| `ui/` | the page's text budget (`text_budget.json`) and its check |

## Fixtures

Every folder and file under `fixtures/` and the tests that read it. `fixtures/conftest.py`
keeps pytest from collecting a fixture's own files.

| Fixture | Read by |
|---|---|
| `api_routes.json` | `test_api_routes` (every route the page's server serves) |
| `host_cubs.json` | `test_browser_buttons` |
| `trace` | `test_trace_*`, `test_browser_trace` |
