# How the web UI's components are written

The shell is Svelte (`App.svelte`, `shell/`, `lib/`) and every page is components here, behind
the same `#/` routes; the old hand-written module they moved out of, one page per release, went
in. These rules keep the pages as they were drawn before, and safe. Tests
enforce the ones marked (t).

## Svelte 5, runes only

- `compilerOptions.runes: true` (t): `$state`, `$derived`, `$effect`, `$props`, `$bindable`.
  Svelte 4 syntax (`export let`, `$:`, `on:click`) does not compile. Events are attributes:
  `onclick={save}`.
- TypeScript in every component (`<script lang="ts">`), `strict` on. `npm run check` runs
  `svelte-check --fail-on-warnings`: a type error or an accessibility warning fails CI.
- No SvelteKit, no router library: the routes are the page's hash routes, read as data.

## Never write HTML

- No `{@html}`, `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval(`,
  `new Function`, `srcdoc` or `javascript:` anywhere in `src/` (t). Svelte escapes every
  `{expression}`; nothing may bypass it.
- Markdown (READMEs, charters) is rendered from a syntax tree into components, as the
  old page does with text nodes.
- A link whose address comes from data goes through one `Link` component with the old
  page's filter (http, https or relative only).

## Styling: tokens only

- `../static/kranto.css` (the tokens, light and dark) and `../static/looks.css` (the themes)
  stay the global stylesheets; `theme.js` stays first in `<head>`. No Tailwind, no
  component library.
- A component's `<style>` uses `var(--…)` tokens for every colour, never a `#hex`, `rgb(` or
  `hsl(` literal. A rule moves out of `kranto.css` into a component only when it is that
  component's alone.
- Keep the ids, classes, roles and aria-labels the old page had: the browser tests and the
  click stories find things by them (`CONTRACT.md` (t)).
- Svelte trims the white space at the start and end of an element's or a block's content
  (`<strong>Paused. </strong>`, `{#if x} · <b>`): write a space that matters as a string,
  `{" · "}`, or the words run together.

## Data

- A page moves by registering its list and pane components for its route's node in
  `pages/index.ts`, with `lazy()` (docs/ui.md, "A moved page"); it builds from `ui/` (the
  old page's DOM: `List`, `Group`, `Row`, `Pane`…) and reads with `read()`. Its Python tests
  that read the old functions move to Vitest beside it (`*.svelte.test.ts` when they need
  runes), and the old functions are deleted in the same PR.
- The routes are `lib/nodes.json`, the key map `lib/keys.json` and the tips `ui/tips.json`:
  data the Python tests read too. The app (`lib/app/`: the data and the press, the routes and
  the draw, the rows and the keys, the chrome's facts, the palette's items) is the one service
  object; the shell and the pages reach it through `app()`, and the tests stub it
  (`pages/testing.svelte.ts`).

- Reads go through the typed client; its types are generated from Python
  (`scripts/dev/gen_page_ts.py`), never written by hand.
- Writes go through the registry's actions with their generated types; a confirm-class
  action cannot be called without `confirm`.
- The server never makes a request wait on GitHub or a model; the page must not either.

## Dependencies and the build

- Seven direct dependencies at exact versions (t), installed with `npm ci --ignore-scripts`.
  A new one needs a reason in its PR.
- The build is one module script and its CSS from this origin (t: the page's policy is
  `script-src 'self'`), within 200 KB gzipped (`scripts/dev/build_ui.py`).
- Tests: Vitest with jsdom, beside the file they test (`*.test.ts`). When a page moves, its
  Python tests that read the old page's text move here with it, listed in the PR.
