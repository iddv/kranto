// The page's entry: the Svelte shell draws the frame and its chrome; every page is
// components, registered in pages/ and drawn in the list and detail panes; the app (lib/app) holds
// the data, the routes and the keys, and the shell reaches it through app().
import { flushSync, mount } from "svelte";
import "./lib/base.css"; // first: the components' own styles come after it
import App from "./App.svelte";
import * as app from "./lib/app";
import "./pages";
import { onPageLoaded } from "./lib/pages.svelte";
import { onArrive, setFetcher } from "./lib/reads.svelte";
import { connect } from "./lib/shell.svelte";
import { upgradeCustom } from "./lib/theme";
import { pageUrl } from "./lib/base";

// The document is drawn at "/" while the page's own server stays under its prefix: a relative
// call ("api/term") goes there, never to the server's own /api/ of the same name.
const fetchAt = window.fetch.bind(window);
window.fetch = ((input: RequestInfo | URL, init?: RequestInit) =>
  fetchAt(typeof input === "string" ? pageUrl(input) : input, init)) as typeof window.fetch;

upgradeCustom(); // a custom theme saved before it had a page of its own (lib/theme.ts)
connect(app);
setFetcher((path) => app.api(path));
// a read that arrives draws the page again (not under a field being typed in; an error always)
onArrive((ok) => {
  if (ok && app.typing()) return;
  flushSync(); // what arrived is on the page before the selection and the hints are worked out
  app.render();
});
// a page's code arrives the first time its route opens: draw it then
onPageLoaded(() => app.render());
export const shell = mount(App, { target: document.body });
