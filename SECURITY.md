# Security

## Reporting a vulnerability

Please report security problems privately through GitHub:
**Security > Report a vulnerability** on this repository
(https://github.com/iddv/kranto/security/advisories/new). Do not open a
public issue. There is no bug bounty.

Only the latest release is supported. `kranto update` installs it; fixes are
not backported to older releases.

## What runs where

Kranto is one Python package, `kranto`, run as one app: the watcher, the web
server on 127.0.0.1:8765, the page, the `kranto` command and `kranto update`.
On the host, as you, run: the server and its scheduler, every fetch of a
source, `gh` calls with your login when you use them, the fetching of plugins
and MCP servers when you add them, the update helper, and **the console**
(your own Claude Code or Codex beside the page, unsandboxed). The cubs (the
small programs that write and send posts) and Open in Claude Code's sessions
run inside a bubblewrap sandbox. [docs/threat-model.md](docs/threat-model.md)
says what each of these can reach, in plain words.

## Threat model

Kranto is a single-user tool meant to run on your own machine. The points
below are what it defends against, and what it does not.

**Writes need a token; reads are open on loopback.** Since 0.3.6 every
state-changing request needs a kranto token, and the token, not the request
body, says who acts: the browser's session cookie, or
`Authorization: Bearer` (`kranto mcp`, the command line, a named agent). The
tokens live in `~/.config/kranto/tokens/` (directory mode 700, files 600); the
index keeps only their SHA-256. A browser signs in once through a one-time
link that `kranto open` (or `kranto up`) prints, valid for 10 minutes. MCP and
agent tokens may only run actions (`POST /brb/api/act`), within their limits.
`api.require_token: false` in `kranto.yaml` turns this off. What it is not:

- **Reads need no token.** Any process or user that can reach the port can
  read your library, idea cards and settings. Nothing a read returns
  is a secret (no key, no token), but on a machine shared with other users
  the library is readable by them.
- **Not a wall between your own processes.** Anything running as you can
  read the token files or run `kranto open`.
- **The session cookie is the UI token itself,** valid for 400 days, and
  browsers do not separate cookies by port: another web server on localhost
  that you open in the same browser receives it. Signing every browser out
  means rotating the `ui` token (`kranto token rotate ui`).

**It binds to loopback.** The server binds to `127.0.0.1` by default, and
`kranto serve --host` warns if you bind it anywhere else. To reach it from another machine without exposing it, forward the port
over SSH (`ssh -N -L 8766:127.0.0.1:8765 host`). In Docker, publish it as
`-p 127.0.0.1:8765:8765`: the Host check below stops browsers, not a client
on your network that sets the header itself.

**Other sites in your browser cannot read or drive it.** Three checks, all on
every request:

- The `Host` header must be one of the names the server may be reached by:
  loopback names, the address given to `--host`, and any `--allow-host`.
  This defeats DNS rebinding, where a page on an attacker's domain is
  re-pointed at 127.0.0.1 and would otherwise be same-origin with the UI.
- A POST must carry an `Origin` (or `Referer`) that matches the host it was
  sent to. A request with neither is refused. A write that carries a current
  token in `Authorization: Bearer` is exempt: the check is against another
  site's page riding the browser's cookie, and a browser never sends that
  header by itself (a page cannot set it cross-site without a CORS preflight,
  which Kranto never grants). Tools and agents send only their token.
- Responses forbid framing (`X-Frame-Options: DENY`, `frame-ancestors
  'none'`) and set a content security policy that allows only the UI's own
  script, so the UI cannot be clickjacked inside another page.

Request bodies are bounded: form fields at 1MB (Starlette's default), JSON at
64KB, and multipart uploads are refused.

**Source URLs are untrusted.** They can come from a model (the scout) or from
feed content. Before every fetch, including each redirect, the host is
resolved and private, loopback and link-local addresses are refused.
Responses are capped at 5MB. XML is parsed with defusedxml. Known limitation:
the check resolves DNS before the HTTP client connects, so a host that
changes its DNS answer between the two (DNS rebinding) could pass the check.

**Links from feeds are untrusted.** Only absolute http(s) URLs are stored or
rendered. `javascript:` and `data:` links are dropped at write time and again
at render time. Templates autoescape, and the map's JavaScript escapes every
string it inserts as HTML.

**Observation text is untrusted input to models.** Every prompt that includes
third-party text frames it as data and tells the model not to follow
instructions inside it. Inputs are truncated, and outputs are parsed as JSON
or checked for markup. Model output never triggers an action in the server: the
worst a successful prompt injection can do here is write misleading text into
your library, and every such text links back to the raw model response and
the source it came from. Idea-card citations are checked against the cited
observation by a separate call. The console is the exception: it is an
assistant with a shell, and [docs/threat-model.md](docs/threat-model.md) says
what holds and what does not when a text in your library tries to steer it.

**Secrets stay out of files that get shared.** The API key is read from an
environment variable, or from a `.env` file in the workspace, never from
`kranto.yaml`. Delivery URLs can be set either way: in `.env`
(`KRANTO_NOTIFY_URLS`), or in `kranto.yaml` under `notify.urls` and
`notify.heartbeat_ping_url`. Put any URL that carries a token in `.env` if
you might share the YAML. Delivery targets are recorded by scheme and hash,
not by URL. `.env` files are ignored by git.

**Spend has no cap by default, and every cap is configurable.** Every model
call passes one gate that checks the pause switch and, when you set one, the
monthly budget first. A model whose cost cannot be determined is refused. A
rejected key stops the run instead of retrying.

**Updates run code from the release repo.** `kranto update` reads the GitHub
Releases of `iddv/kranto` (once a day by default), downloads the release's
wheels and checks them against the `SHA256SUMS` file and the manifest of the
same release. That checks the download, not who made it: whoever can publish a
release there can ship code that runs as you. A new version installs when you
click Restart to update, or by itself in the quiet window if you set
`update.auto: idle`. Third-party dependencies are version ranges, so a
rollback that has to reinstall online can resolve versions the release was
not tested with. Signed attestations and a constraints file are planned.

## Data

The library holds model-written summaries of third-party content, verbatim
excerpts, and links. Check the terms of the sources you watch before you
publish a library, a bundle, or a screenshot of one.
