// Where the page's own files and its own server live: "/brb/" under Kranto's server (the page
// itself is drawn at "/"), "/" on the page's small server alone. Read once from the address
// this module was loaded from (…/static/v<version>/app/…); where that is not under static/
// (the dev server's /src/…), the document's own folder.
export const PAGE: string = ((): string => {
  try {
    const at = new URL(import.meta.url).pathname;
    const i = at.search(/\/static\//); // the page's own files, wherever it is served
    if (i >= 0) return at.slice(0, i + 1);
    const here = typeof location === "undefined" ? "/" : location.pathname;
    return here.slice(0, here.lastIndexOf("/") + 1) || "/";
  } catch {
    return "/";
  }
})();

/** a path of the page's own (``api/term``, ``static/brand/x.svg``) as an address that works
 * wherever the document is drawn; an absolute path or a full URL is left as it is */
export const pageUrl = (p: string, base: string = PAGE): string =>
  /^(?:[a-z][a-z0-9+.-]*:|\/)/i.test(p) ? p : base + p;
