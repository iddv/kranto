# tests

Everything CI runs (`test`; the cub sandbox suite in `cubs-sandbox.yml`). The tests are flat
`test_*.py` files found by their prefix (`test_cub_*`, `test_web*`). Nothing here
calls a model or the network: `conftest.py` makes the home a temp dir and builds the fakes, and
`_shims/` puts a `claude` and a `gh` that refuse first on `PATH`.

| Beside the tests | What it is |
|---|---|
| `conftest.py`, `__init__.py` | the suite's fixtures: a workspace, a store, a fake model transport, the app |
| `_shims/` | the `claude` and `gh` that refuse |
| `fake_anthropic.py`, `fake_xai.py`, `fake_search.py`, `fake_x.py`, `fake_resend.py`, `fake_ibkr_official.py` | stand-ins for the model providers, live search, X, the newsletter platform and the broker |
| `brbfake.py` | the page as Kranto sees it, without the page: a stand-in `kranto.page.host_api` |
| `cubhelp.py` | a fixture cub installed by writing its folder, pin and registry row; the runtime that runs it |

## Fixtures

| Fixture | Read by |
|---|---|
| `cubs` | `cubhelp`, `test_cub_*` (install, runtime, security, surfaces, rename …): small cubs that each do one thing (echo, a flooder, an escape attempt, a filer) |
| `cub_manifests` | `test_manifest_schema` |
| `evals` | `test_evals`, `test_eval_runs`, `test_evals_api`: a frozen eval set written by `scripts/dev/eval_fixtures.py` |
| `odd_install` | `test_odd_install`, `scripts/dev/odd_install.py` and `odd_walk.sh`: an install with every stored value a writer can produce (null, empty, missing), and an upgraded one |
| `x` | `fake_x`, `test_x_sources`: X API answers |
