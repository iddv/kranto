# `cub/1`: the protocol between the host and a cub's process

*The protocol between Kranto and a cub's process, in full: every method in both directions with
its request and response shape, its errors, its grant, its limits. The SDK (`src/bears_cub/`)
speaks it for a cub; [cubs.md](cubs.md) is the guide, `src/bears_cub/cub.schema.json` the
manifest's schema. Where it says "§n of the design" or names another design note, that note is
internal; nothing here depends on it. The shapes are written as JSON with types in angle brackets;
`?` marks an optional key; a key not listed is refused (-32602).*

## 1. Transport and framing

| Rule | Value |
|---|---|
| channel | the cub process's **stdin** (host → cub) and **stdout** (cub → host); **stderr** is the cub's log, captured by the host (of the design) |
| framing | one JSON object per line, UTF-8, terminated by `\n` (newline-delimited JSON-RPC 2.0, as MCP's stdio transport). A JSON string may not contain a raw newline (it is escaped). An empty line is ignored. |
| line size | at most **1,048,576 bytes** in either direction. A longer line from the cub: the host answers `-32011` with the id if it can be read, else `null`, then kills the cub (one over-long line is a protocol violation). The host never sends a longer line: a host→cub message that would exceed it is split (event batches) or refused at the source (a read's answer over 1 MiB is an error to the page, not a line). |
| encoding | strict UTF-8; invalid bytes from the cub: `-32700`, counted |
| batches | a JSON array (JSON-RPC batch) is refused with `-32600`; one message per line |
| ids | the cub uses positive integers, increasing; the host uses strings `"h1"`, `"h2"`, … A response carries the request's id unchanged. |
| parse errors | the host answers `{"jsonrpc":"2.0","id":null,"error":{"code":-32700,…}}`; after **3** such lines in one process the host kills it (`failed: protocol`) |
| ordering | the host answers the cub's requests **in the order received** and handles them one at a time; the cub answers the host's one outstanding request (there is never more than one, except `cancel`, `shutdown` and `ping`, which are notifications or may arrive while a request is open) |
| in flight | at most **8** cub→host requests outstanding; the 9th is `-32012` and the cub is killed (`failed: flood`) |
| concurrency | one host→cub request at a time per process (the cub is single-threaded by contract); the SDK is synchronous |
| clock | the host's; a cub has no clock promise (its `time` is the sandbox's, same as the host's) |

## 2. Message shapes

```
request      {"jsonrpc":"2.0", "id": <int|str>, "method": <str>, "params": <object>}
response     {"jsonrpc":"2.0", "id": <int|str>, "result": <object>}
error        {"jsonrpc":"2.0", "id": <int|str|null>, "error": {"code": <int>, "message": <str>, "data"?: <object>}}
notification {"jsonrpc":"2.0", "method": <str>, "params": <object>}      (no id; never answered)
```

`params` is always an object (never positional). `message` is one sentence in words, for the
log and the page, never a secret; `data` is typed and small (`{retry_after_s}`, `{ticket_id}`,
`{limit, got}`).

## 3. Error codes

| Code | Name | Meaning | Who sends |
|---|---|---|---|
| -32700 | parse error | not JSON, not UTF-8 | host |
| -32600 | invalid request | no `method`, a batch, `params` not an object, an id of the wrong type | host, cub |
| -32601 | method not found | unknown method (a `cub/2` method on a `cub/1` host; a handler the manifest names that the entry file did not register) | host, cub |
| -32602 | invalid params | a key not in the shape, a wrong type, a bound passed | host, cub |
| -32603 | internal | the host's bug (logged with the run); the cub's handler raised (its traceback goes to the cub's log, never to the host's reply beyond the exception's class name) | host, cub |
| -32001 | not granted | the manifest (as approved: `grants`) does not list what the call needs | host |
| -32002 | cap reached | the cub's monthly model cap, or its calls-per-day | host |
| -32003 | halted | the cub is paused, disabled, `cubs.STOP` exists, or `cubs.enabled` is false (the process is being shut down; the call cannot proceed) | host |
| -32004 | rate limited | a per-hour window is full; `data.retry_after_s` | host |
| -32005 | schema rejected | a payload, ticket fields, a kv value or a read's answer did not fit its schema; `message` names the key | host |
| -32006 | not found | an object, a ticket, a kv key, an event id | host |
| -32007 | deadline | the host gave up on a host-side call (the model, a fetch, a broker) after its budget | host |
| -32008 | upstream | the service answered with an error (`data.status`, `data.code` scrubbed) | host |
| -32009 | duplicate | a ticket with the same kind and fields is open (`data.ticket_id`); an `events.publish` dedupe key already used (`data.event_id`) | host |
| -32010 | protocol | `hello.api` is not a protocol this host speaks (`data.speaks: ["cub/1"]`); the host then sends `shutdown` | host |
| -32011 | too large | a line, a message field, a value over its limit (`data.limit`, `data.got`) | host |
| -32012 | flood | more than 8 requests in flight, or more than 2,000 requests in one run | host |
| -32013 | not connected | the broker op needs a credential and none is connected (the dialog's Connect is the fix); dry-mode drafting ops never raise this | host |
| -32014 | cancelled | the host cancelled the call (deadline, a stop) while it waited | host |
| -32020 | handler failed | the cub's handler raised; `data.exception` is the class name | cub (the SDK) |

A cub that answers a host request with any error other than `-32020` is logged and the run is
`failed: protocol`. A cub that answers with a malformed response (no `result` and no `error`,
or a `result` that is not an object) is `failed: protocol`.

## 4. The session

```
host: spawn ──────────────────────────────────────────────────────────────────────────▶ time
cub:  ──hello──▶            ◀──result (grants, mode, …)──
host:                                                     ──job.run / event.deliver / action.run / read.run / stage.run──▶
cub:                                                                 ──reads.get──▶ ◀──result──  ──ticket.file──▶ ◀──result──  ──result (the job's)──▶
host:                        (idle: keep-alive up to cubs.idle_s, a ping before reuse)         ──shutdown──▶ (notification); stdin closed; SIGTERM at +5 s; SIGKILL at +8 s
```

1. The host spawns the process (of the design) and waits **10 s** for the cub's `hello`. Anything else first, or nothing: killed, `failed: no hello`.
2. The host answers `hello`. On error (`-32010`, `-32005`) it sends `shutdown` and the run is `failed: hello refused: <message>`.
3. The host sends requests one at a time. Each has a deadline. Between requests the process stays up for `cubs.idle_s` (default 60 s; a page open on the cub's lists keeps it up), then the host sends `shutdown`.
4. `cancel` (notification) may arrive while a host request is open: the cub should finish quickly; the host enforces the deadline regardless.
5. `shutdown` (notification): the cub exits within 5 s. The host closes stdin, waits 5 s, sends SIGTERM to the sandbox (the whole scope dies), waits 3 s, SIGKILL.
6. Before reusing an idle process the host sends `ping`; no `pong` within 5 s: kill, respawn.

A cub that exits by itself (any code) during a request: the request fails `failed: crashed (exit N)`, stderr's tail (2 KiB) is in the run record. The host never restarts a process mid-request; the next request starts a fresh one.

## 5. Cub → host methods

Every method below is checked, in this order, before it does anything: (1) the shape (`-32602`, `-32011`); (2) the cub's state (`-32003`); (3) the grant (`-32001`); (4) the rate window and the caps (`-32004`, `-32002`); then the call, each a `cub_calls` row (service, op, status, ms, bytes in and out).

### 5.1 `hello`

The first message, once per process.

```
params  {"api": "cub/1", "id": <str: the manifest's id>, "version": <str: the manifest's version>,
         "manifest_hash": <str: sha256 the SDK computed over cub.yaml's canonical JSON>,
         "sdk": <str: bears_cub.__version__>, "python": <str: "3.12.3">,
         "handlers": {"jobs": [<method>...], "events": [<method>...], "actions": [<method>...],
                      "reads": [<method>...], "stages": [<method>...]}}
result  {"api": "cub/1", "host": "kranto", "host_version": <str: "0.5.0">,
         "speaks": ["cub/1"], "trust": <str>, "mode": {"<request kind>": "dry"|"live", ...},
         "granted": {"reads": [...], "reads_topics": [<int>...]|null, "events": {"publish": [...], "subscribe": [...]},
                     "model": {"tiers": [...], "purposes": [...], "monthly_usd": <num|null>},
                     "search": [...], "http": {"hosts": [...]}, "broker": {<service>: [<op>...]},
                     "requests": [...], "storage": "own"|"none", "stages": [<id>...]},
         "limits": {"line_bytes": 1048576, "kv_bytes": <int>, "kv_keys": <int>, "calls_per_day": <int>,
                    "model_per_hour": 60, "search_per_hour": 30, "http_per_hour": 60, "tickets_per_day": {<kind>: <int>}},
         "deprecations": [{"method": <str>, "until": <str: host version>, "say": <str>}],
         "run": {"uuid": <str>, "started_at": <iso>}, "tz": <str: "Europe/Amsterdam">, "now": <iso>}
errors  -32010 (api unknown), -32005 (id or version differ from the installed manifest, or manifest_hash differs from the pin:
        "the cub.yaml this process read is not the one approved": the run fails and the cub is paused with the note),
        -32602 (a handler the manifest names is missing from handlers: data.missing = [...])
grant   none
```

The host compares `handlers` with the manifest: every `jobs[].method`, `events.subscribe[].method`, `actions[].method`, `provides[]` and `stages[].entry`'s handler must be registered; a missing one refuses the hello (so a cub never half-works). Extra handlers are ignored.

### 5.2 `log`

```
params  {"level": "debug"|"info"|"warning"|"error", "message": <str ≤ 4000>, "data"?: <object ≤ 4000 bytes JSON>}
result  {}
limits  600 calls a run; past it the host drops them and writes one line "log: 600 lines, the rest dropped"
grant   none
```

Written to the cub's log file with the run uuid. Scrubbed by `scrub` (secret shapes) before writing, like every log line Kranto writes.

### 5.3 `reads.get`

The v1 read surface and the reads first-party features add to it, exactly as `core.api.call` serves them in-process. Text comes back fenced and labelled (`[obs 8231]`).

```
params  {"name": <str: one of the reads below>, "params": <object>}
result  the read's answer (below)
errors  -32001 (the family is not in grants.reads), -32006 (no such object), -32602 (the read's own ReadError, in words), -32601 (no such read)
grant   reads: [<family>]; a cub narrowed to topics (grants.reads_topics) sees only those topics in topics.list, library.*, themes.*, briefs.* and ideas.* (an object outside them is -32006)
rate    600 a run
```

| name | family | params | result |
|---|---|---|---|
| `topics.list` | topics | `{}` | `{"topics": [{"id", "name", "description", "status"}]}` |
| `library.observations` | library | `{"topic_id"?, "since"?: <iso>, "limit"?: 1..100 (40), "sort"?: "new"|"signal", "signal_only"?: bool}` | `{"observations": [{"id", "label", "date", "title", "source", "url", "summary", "why", "signal", "created_at"}], "total"}` |
| `library.search` | library | `{"q": <str ≤ 300>, "topic_id"?, "limit"?: 1..100 (10)}` | `{"observations": [{…as above, "score"}]}` |
| `themes.list` | themes | `{"topic_id"?, "rising"?: bool}` | `{"snapshot_at", "themes": [{"id", "name", "size", "share", "keywords", "rising", "cross_source", "topics"}]}` |
| `themes.get` | themes | `{"id": <str lineage>}` | the theme plus `"observation_ids": [<int>…]` (200 at most) |
| `ideas.list` | ideas | `{"since"?: <iso>, "limit"?: 1..100 (50), "editor_class"?: "nominee"|"candidate"|"note"|"reject"}` | `{"ideas": [{"id", "title", "one_liner", "status", "created_at", "evidence_ids", "editor": {"class", "week", "why"}|null}]}` (`editor` and `editor_class` are additive in 0.5: the weekly editor's verdict on the card, from the card's latest `editor` outcome) |
| `ideas.get` | ideas | `{"id"}` | one idea as above plus `"brief": <fenced str>` |
| `cards.get` | ideas | `{"id"}` | one idea card with what a post about it needs (Kranto 0.6, additive): `{"id", "title", "one_liner", "thesis", "insight", "why", "topic": {"id", "name"}|null, "created_at", "sources": [{"n", "url", "claim", "source", "date"}]}` (every text fenced; `sources` are the card's citations that carry a link, once each) |
| `briefs.list` | briefs | `{"topic_id"?, "since"?: <iso>, "limit"?: 1..100 (20)}` | `{"briefs": [{"id", "topic_id", "date", "headline_count", "created_at"}]}` (News's read, as it is) |
| `briefs.get` | briefs | `{"id"}` | `{"id", "topic_id", "date", "items": [{"headline", "body", "why", "date", "sources": [{"label", "url", "date"}]}], "searched": <str>}` (every text field fenced) |
| `objects.get` | objects | `{"kind": "observation"|"idea"|"theme"|"brief", "id"}` | `{"kind", "object": {…}}` |
| `events.read` | events | as (`reads.get` of it is allowed for symmetry; `events.read` is the same thing) | |
| `spend.mine` | spend | `{}` | `{"cub", "month_usd", "today_usd", "calls", "equiv_usd", "cap_usd": <num|null>, "calls_today", "calls_per_day"}` |
| `grades.mine` | (none) | `{"kind"?: <str>, "since"?: <iso>, "limit"?: 1..200 (50)}` | `{"grades": [{"id", "target": "cub:<id>:<kind>", "target_id", "verdict": "useful"|"not_useful"|"wrong", "chips": [...], "line", "created_at"}]}`: the owner's grades on this cub's own cards; no grant needed (they are about the cub) |

### 5.4 `events.read`, `events.ack`

```
events.read   params {"kind": <str: a subscribed kind>, "limit"?: 1..100 (100), "since"?: <int>}
              result {"events": [{"id", "ts", "kind", "feature", "trust", "subject_kind", "subject_id", "payload"}], "cursor": <int: the cub's cursor for this kind before this read>, "more": <bool>}
              The events after the cub's cursor (or after `since` when given, which never moves the cursor), of that kind, at or above the subscription's min_trust, oldest first.
events.ack    params {"kind": <str>, "last_id": <int>}
              result {"cursor": <int>}
              Moves the cub's cursor for `kind` to last_id if it is higher (a lower id is a no-op). At least once: a run that reads and dies before it acks reads the same events again.
errors        -32001 (not subscribed to kind), -32602
grant         events.subscribe lists the kind
rate          600 a run
```

### 5.5 `events.publish`

```
params  {"kind": <str: one of the manifest's events.publish>, "payload": <object ≤ 2000 bytes, strings ≤ 200, depth ≤ 3>,
         "subject"?: {"kind": <str>, "id": <str|int>}, "dedupe"?: <str ≤ 80>}
result  {"event_id": <int>, "duplicate": <bool>}
errors  -32001 (kind not declared), -32005 (payload too big or deep: "the reader fetches documents through a read"). A reused dedupe key is not an error: the result is the first event's id with duplicate true (so a retried run is harmless).
grant   events.publish lists the kind
rate    200 an hour
```

The host adds `feature = <cub id>`, `trust`, `run_uuid`, `origin = "cub"`. A payload is a fact, never an instruction.

### 5.6 `model.complete`

```
params  {"purpose": <str: one of model.purposes>, "tier": "judge"|"reason" (one of model.tiers),
         "messages": [{"role": "system"|"user"|"assistant", "content": <str>}] (≤ 20 messages, ≤ 400,000 characters in all),
         "max_tokens"?: 1..4096 (800), "temperature"?: 0..1 (0.2), "schema"?: <object: a JSON schema the reply must fit>,
         "retry_truncated"?: <bool> (false)}
result  {"text": <str>, "structured": <object|null>, "model": <str>, "prompt_tokens": <int|null>, "completion_tokens": <int|null>,
         "cost_usd": <num>, "equiv_usd": <num|null>, "call_id": <int>, "truncated": <bool>}
errors  -32001 (purpose or tier not declared; any other key, e.g. tools, provider, model: "no tools, no provider or model of its own"),
        -32002 (the cap: data.spent_usd, data.cap_usd), -32004 (60 an hour), -32007 (the provider did not answer in 300 s), -32008 (the provider refused)
grant   model.purposes and model.tiers; the cap is cubs.<id>.monthly_usd, else the manifest's monthly_usd, else the trust tier's default (owner: none; others: 5)
rate    60 an hour, 300 s each
```

The host calls `ScopedLLM.complete(purpose, tier, messages, prompt_version=f"cub:{id}@{version}", run_uuid, max_tokens, temperature, schema, retry_truncated)`: the same metered client first-party features get, recorded in `llm_calls` under the cub's purpose (its line on Spend). The SDK's `fence(label, text)` wraps strangers' text; the host does not inspect prompt text.

### 5.6a `prose.compose`, `prose.check`, `prose.revise` (Kranto 0.7, SDK 1.3.0: `ctx.prose`)

The owner's prose profile ([prose.md](prose.md)): their voice card, samples, lists and switches, Kranto's floor and a site's template.

```
prose.compose  params {"material": {"take"?, "title"?, "facts"?, "format"?, "hint"?: <str>}, "site"?: <str>, "kind"?: <str>,
                       "task"?: <str: the writer's instruction>, "language"?: <str>, "limits"?: <object>, "features"?: <str>}
               result {"messages": [{"role", "content"}], "take": <bool: the owner wants to be asked>, "disclosure": <str|null>}
prose.check    params {"text": <str ≤ 100,000>, "site"?, "kind"?, "limits"?, "take"?: <str>,
                       "sources"?: <str ≤ 100,000: the material the text was written from (SDK 1.4)>}
               result {"score": 0..100, "verdict": <str>, "flags": [{"start", "end", "text", "rule", "words", "fix", "group",
                       "strength", "scope"}], "counts", "grade", "words", "strictness", "site", "kind"}  (local: no model call)
prose.revise   params {"text", "flags"?: <list: from prose.check; else the host checks>, "purpose", "tier", "site"?, "kind"?,
                       "limits"?, "take"?, "sources"?}
               result {"text", "flags", "score", "verdict", "rounds": 0..2, "changed": [{"start", "end", "before", "after"}]}
errors  -32001 (no model purpose granted; revise: its purpose or tier not granted), -32602, -32011 (too large);
        revise also model.complete's -32002, -32004, -32008
grant   model: a cub that may write may use the profile; revise's calls are model.complete's under the cub's purpose and cap,
        each recorded in cub_calls as one
```

With `sources` (SDK 1.4.0), `check` also flags a person's name or a handle the material does not have (`salt.person`: salt jabs at the thing, never at a person); the blog and toot cubs pass their card's or item's words. A host before it refuses the key (-32602).

`compose` puts the writer's task first, then Kranto's floor and the guides the owner chose for the site, their voice card, the switches in words, the site's limits and features as given, the 3 samples closest to the material (by embedding) inside `<example>` fences, and the material with the take first, fenced. `revise` rewrites only the flagged spans: every byte outside them is the input's.

### 5.7 `search.run`

```
params  {"q": <str ≤ 300>, "kind"?: "web"|"discussion"|"code"|"papers" ("web"), "recency"?: "day"|"week"|"month"|"year"|null, "n"?: 1..20 (10)}
result  {"query", "live": <bool>, "backend": <str|null>, "searched_at": <iso>, "note": <str|null>,
         "hits": [{"label": "exa 1", "url", "title": <fenced>, "date", "snippet": <fenced>, "backend", "rank"}], "block": <str: the dated, numbered, fenced block a prompt takes>}
errors  -32001 (kind not in search), -32004 (30 an hour), -32007 (30 s)
grant   search: [kind]; counted under the cub's name (search.callers.<id>)
```

No page fetching: a hit's `url` is a string the cub may show or cite, not fetch (unless its host is in `http.hosts`).

### 5.8 `http.fetch`

```
params  {"url": <str: https://<host in http.hosts or a subdomain>/…, ≤ 2048>, "headers"?: {"Accept"?: <str>, "Accept-Language"?: <str>} (nothing else), "max_bytes"?: 1..2097152 (2097152)}
result  {"status": <int>, "url": <str: after redirects, same host rule>, "content_type": <str|null>, "bytes": <int>, "truncated": <bool>,
         "text": <str|null: utf-8 text when the content type is text/* or application/json|xml, with the fence's <<</>>> runs shortened>, "body_b64": <str|null: otherwise, base64>}
errors  -32001 (the host is not declared, or the scheme is not https), -32602 (an IP literal, a userinfo, a port other than 443), -32004 (60 an hour), -32002 (calls_per_day), -32007 (20 s), -32008 (a non-2xx: data.status; the body is still returned when it is text, so an API error can be read)
grant   http.hosts; GET only in cub/1
```

The host performs the GET with `sources.base.HTTP` (public addresses only: a declared name that resolves to a private address is refused; follows at most 3 redirects, each to a declared host; no credential ever; the cub's name in the User-Agent comment).

### 5.9 `broker.call`

```
params  {"service": <str>, "op": <str>, "args": <object: the op's args schema>}
result  the op's typed result (per adapter)
errors  -32001 ((service, op) not granted, or op is a perform op), -32013 (needs a credential, none connected), -32004 (read ops 60 an hour; draft ops 20 a day), -32002 (calls_per_day), -32007 (60 s), -32008 (the service's error: data.status, data.code), -32005 (args do not fit the op's schema)
grant   broker: {service: [op]}
```

Every call is a `cub_calls` row with `service` and `op`; the response passed to the cub is the adapter's typed result only, never raw headers or the body.

### 5.10 `ticket.file`, `ticket.list`, `ticket.get`

```
ticket.file  params {"kind": <str: one of requests>, "fields": <object: the kind's typed fields>,
                     "because"?: {"events"?: [<int>…≤50], "observations"?: [<int>…≤50], "briefs"?: [<int>…≤50], "ideas"?: [<int>…≤50], "trends"?: [<trend key>…≤50], "labels"?: [<str ≤ 20>…]},
                     "subject"?: {"kind": <str>, "id": <str|int>}}
             result {"ticket_id": <int>, "state": "needs_confirm", "expires_at": <iso>, "mode": "dry"|"live"}
             errors -32001 (kind not granted), -32005 (fields: exactly the kind's keys, each in bounds; a draft_ref that names no draft of this cub), -32009 (an open ticket with these fields: data.ticket_id), -32004 (the kind's per_day: data.retry_after_s), -32003
ticket.list  params {"subject"?: {"kind", "id"}, "open"?: <bool>, "limit"?: 1..100 (50)}
             result {"tickets": [<ticket>]}
ticket.get   params {"ticket_id": <int>}
             result <ticket> = {"id", "kind", "state", "fields", "because", "subject_kind", "subject_id", "note", "expires_at", "created_at", "resolved_at": <iso|null>, "mode": <"dry"|"live": the mode at filing, informational>}
             errors -32006 (not this cub's ticket)
grant        requests lists the kind (file); none for list and get (a cub sees its own tickets only)
rate         file: the kind's per_day; list and get: 600 a run
```

`because` ids are kept as given (the confirm dialog links them); the host checks they are integers, not that they exist. `ideas` (idea card ids) since Kranto 0.5.9: a ticket names the card it rests on, never as a label. `trends` (keys, `[a-z][a-z0-9_-]{1,40}`) is still accepted so an older cub's ticket files, and nothing links it.

### 5.11 `kv.get`, `kv.put`, `kv.delete`, `kv.list`

```
kv.get     params {"key": <str>}                                   result {"value": <any JSON>, "updated_at": <iso>} | error -32006
kv.put     params {"key": <str>, "value": <any JSON ≤ 65536 bytes>} result {"bytes": <int>, "total_bytes": <int>}
kv.delete  params {"key": <str>}                                   result {"deleted": <bool>}
kv.list    params {"prefix"?: <str>, "after"?: <str>, "limit"?: 1..500 (100)}  result {"keys": [{"key", "bytes", "updated_at"}], "more": <bool>}
key        1..200 characters of [A-Za-z0-9_.:/-]
errors     -32001 (storage: none), -32011 (value > 64 KiB), -32002 (quota: data.limit_bytes, data.total_bytes; or keys > 10,000)
grant      storage: own
rate       2,000 a run
quota      cubs.<id>.kv_mb (default 8) and 10,000 keys
```

### 5.12 `settings.get`

```
params  {}
result  {"values": {"<id>.<key>": <value>, …}, "core": {"live": [<kind>…], "monthly_usd": <num|null>, "calls_per_day": <int>, "enabled": true, "trust": <str>}}
grant   none (its own section and the core's keys for it)
```

Values are the ones in force at the call (a settings.changed event arrives on the bus too, if subscribed).

## 6. Host → cub methods

The cub answers each within its deadline. The SDK dispatches to the handler the manifest names; a handler that raises answers `-32020`.

### 6.1 `job.run`

```
params  {"kind": <str>, "method": <str>, "run_uuid": <str>, "deadline_s": <int>, "mode": {<kind>: "dry"|"live"}, "topic_id"?: <int> (per: topic), "trigger": "schedule"|"event"|"owner"|"cli", "events"?: [<int>…] (the ids that made it due, with on:)}
result  {"status"?: "ok"|"degraded"|"skipped" ("ok"), "summary"?: <object ≤ 4000 bytes: what the run did, shown on Health and the cub's page>, "line"?: <str ≤ 200: one sentence for the log>}
deadline the job's deadline_s (manifest; 600 default; 3600 at most)
```

Recorded as a `runs` row of kind `<id>.<job>` with the summary; `job.finished` on the bus. `skipped` does not reset the interval (as every job). A cub that answers with `-32020` or any error: `failed`, the back-off applies (of the design).

### 6.2 `event.deliver`

```
params  {"kind": <str>, "method": <str>, "events": [<event>… ≤ 100], "run_uuid": <str>, "deadline_s": 120, "mode": {…}}
result  {"handled": <int: the last event id handled, ≤ the batch's last id>}
deadline 120 s
```

The host advances the cursor to `handled` (a cub may stop early and say so: the rest comes next tick). An error keeps the cursor; after 8 consecutive failures on the same first id the host advances past that batch, writes a `cub_calls` row `events deliver skipped` with the ids, and shows "skipped 12 events after 8 failures" on the cub's page (a poison event never blocks a cub forever).

### 6.3 `action.run`

```
params  {"kind": <str>, "method": <str>, "fields": <object: the action's declared fields, checked by the host>, "door": "ui"|"cli", "subject"?: {"kind", "id"}, "run_uuid": <str>, "deadline_s": 30, "mode": {…}}
result  {"ok"?: <bool> (true), "say"?: <str ≤ 200: the toast>, "refresh"?: [<read name>…]: reads whose cache the host drops}
deadline 30 s (the page waits on it: an action does little; a job does the work)
```

### 6.4 `read.run`

```
params  {"name": <str: one of provides>, "params": <object: the query string's keys, strings>, "deadline_s": 10}
result  <object ≤ 262,144 bytes JSON: what the page's list, tile, row or choice read expects (the manifest's shape rules: {"count": n}, {"rows": [...]}, {"<group key>": [...]}, {"choices": [{value, word}]})>
deadline 10 s; the host caches the answer for 10 s per (name, params) and drops it on an action's `refresh` or a job's end
```

A result over the size, or not an object: the page gets an error ("the cub's answer did not fit"), the cub's log a line.

### 6.5 `stage.run` (code stages)

```
params  {"id": <str: the stage's id>, "method": <str>, "build": {"task": <str>, "round": <int>, "flow": "lean"|"simple"|"v5", "anchor": <str>},
         "mounts": {"product": "/work/product", "product_rw": <bool>, "in": "/work/in", "out": "/work/out"},
         "reads": [<str>…], "gives": [<str>…], "writes": [<glob>…], "deadline_s": <int: cap.timeout_s>, "mode": "dry"|"live",
         "product_url"?: <str: with needs_running, phase 2>, "run_uuid": <str>}
result  {"status": "ok"|"warn"|"fail", "line": <str ≤ 140>, "counts"?: <object>}
deadline cap.timeout_s
```

The stage writes `findings.json`, `artifacts/` and (through the rw copy) its patch under the mounts; `result.json` is written by the SDK from the result. The host copies `/work/out` to the round's `stages/<cub>.<stage>/` and applies Of the cub→host methods a stage run may call `log`, `model.complete`, `settings.get`, `kv.*`, `ticket.file` (post.* and send.* only) and `http.fetch`; `reads.get`, `events.*`, `search.run` and `broker.call` are `-32001` during a stage run (a stage is about the tree) unless the cub also declares them for its jobs, in which case they work as for a job.

### 6.6 `ping`, `cancel`, `shutdown`

```
ping      request  params {}            result {"pong": true}        (5 s)
cancel    notification params {"id": <the open host request's id>, "why": "deadline"|"stop"|"shutdown"}
shutdown  notification params {"why": "idle"|"stop"|"update"|"remove"|"host"}
```

## 7. Idempotency, ordering and delivery, in one table

| Thing | Rule |
|---|---|
| a job run | at most once per due slot; a run interrupted (crash, deadline, update) is `failed` and the slot is retried with back-off; the cub makes its own work idempotent with `kv` (the SDK's `ctx.once(key)` helper) |
| event delivery (push and pull) | at least once; cursor per (cub, kind); `events.ack` is monotonic; a poison batch is skipped after 8 failures and said |
| `events.publish` | exactly once per `dedupe` key per cub (the key is kept for ever in `cub_dedupe`); without a key, every call appends |
| `ticket.file` | exactly one open ticket per (kind, fields) at a time (`-32009` returns the open one's id); a resolved ticket's fields may be filed again |
| `kv.put` | last write wins; one key, one row |
| `broker.call` drafting ops | each call makes a new draft (a new `draft_ref`); the cub keeps the ref in `kv` to reuse it |
| the confirm | exactly once per ticket (the atomic state move); a performer's `unknown` is never retried by Kranto |
| responses | in the order of requests, per direction |

## 8. Versioning

- `cub/1` is additive: a host may add methods, optional params and result keys; it never removes or changes one. A cub must ignore result keys it does not know.
- A method's removal or a changed shape is `cub/2`; a `cub/2` host answers a `cub/1` hello with `speaks: ["cub/1", "cub/2"]` and serves `cub/1` for two minor releases of Kranto after `cub/2` ships.
- `hello.deprecations` names methods going away one minor ahead; the SDK logs a warning when it calls one.
- The manifest's `schema` is independent of the protocol's major: schema 1 is additive (new optional keys); a key the host does not know is refused at install, never at runtime.
- The SDK's version is semver; `hello.sdk` is recorded in the run; a host may refuse an SDK older than `cubs.min_sdk` (a setting, default none) with `-32010` and `data.min_sdk`.
