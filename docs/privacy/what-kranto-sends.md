# What Kranto sends

*Made by `kranto telemetry docs` from the allow-list (`src/kranto/telemetry/schema.json`, schema 1). Do not edit by hand.*

Kranto counts how it is used on your machine and, only if you choose `basic` or `detailed`, sends one report a day and an error report within minutes when something fails. A field that is not on this page cannot be sent: Kranto drops anything else before it is written, and every report is checked against this list before it leaves. Nothing is sent before you answer, or with `local` or `off`. With `basic` or `detailed`, each day's report goes between 02:00 and 05:00 UTC the next morning, starting with the first whole day after you chose, to the controller's relay on AWS in the EU (`https://dde6yrzwuxncv.cloudfront.net/v1/logs`), unless `KRANTO_TELEMETRY_ENDPOINT` or `telemetry.endpoint` names another.

Read today's report with `kranto telemetry show` and everything sent with `kranto telemetry show --sent`; stop with `kranto telemetry off`, Settings › Privacy & access, or `DO_NOT_TRACK=1`.

## Usage reports: the notice

**Who.** The controller is The Kranto authors, based in the European Union. Contact: the
maintainer, through https://github.com/iddv/kranto: open an issue asking the maintainer to
contact you, and put no personal data in it. The EU's General Data Protection Regulation and
the ePrivacy rules apply.

**What and why.** Kranto can send its maker one report a day about how it is used, so that
Kranto can be improved, and, when something fails, an error report within minutes, so that the
failure can be found and fixed before you have to tell anyone: the exception's type, where in
Kranto's code it happened, and its message with every word that could be yours removed. The
fields are listed below, and nothing outside that list can be sent. Basic reports have no
identifier, no content of yours, and no time finer than the day (an error report: the hour).
The detailed tier, which you must choose yourself, adds a random install id that is replaced
every 180 days and that you can reset, and how Kranto's assistant tools are used, hour by hour:
which of Kranto's verbs were called, from which door (the page, the console, kranto mcp, the
command line) and by which assistant, how each call ended (done, refused and the kind of
refusal, failed, prepared for your approval, then confirmed or dismissed), how long it took and
the ladder's rung; each assistant session's length, model, place and how it started and ended;
and which of Kranto's slash commands were used, by name. Never a prompt, a reply, a tool's
arguments or results, a file's contents, a topic's name, an id or a path.

**Only if you choose.** Nothing is sent until you answer the question at first run (`kranto
setup`, or the first page of the app); clicking Enter sends nothing. Until you answer, Kranto
counts on your machine only, and you can read those counts with `kranto telemetry show`. You can
change your mind at any time in Settings › Privacy & access, with `kranto telemetry off`, or by setting
`DO_NOT_TRACK=1` (or `KRANTO_TELEMETRY=off`) in Kranto's environment. With `local` or `off`
nothing is sent. With basic or detailed, the first report covers the first whole day after you
chose; each day's report is sent once, between 02:00 and 05:00 UTC the next morning. Error
reports follow the same choice: with basic or detailed they are sent within minutes of an error
(the same error at most once an hour, with a count); with local or off none is kept or sent.
The assistant's usage goes with detailed only; with any other choice none is kept or sent, and
leaving detailed deletes any waiting. The choice is yours alone: an assistant working in Kranto
can prepare it for your approval on the page, but never make it, whatever the assistant settings
say; it may turn reports off.

**Lawful basis.** Your consent (GDPR Art. 6(1)(a); ePrivacy Directive Art. 5(3)). Withdrawing it
is as easy as giving it, and stops all sending from the next day.

**Where it goes.** To a relay run by the controller on Amazon Web Services in the EU (Ireland,
eu-west-1), at https://dde6yrzwuxncv.cloudfront.net/v1/logs: the report enters through Amazon
CloudFront, AWS's network of edge servers, and is stored only in the EU. AWS is a processor
under its standard data processing terms. From there the reports go to a machine the
controller runs. The relay reads your connection's address only to work out a two-letter
country code and to limit how many reports one address can send; it never stores the address
or anything made from it. Nothing is sold, shared or used for anything but improving Kranto. If
you set `KRANTO_TELEMETRY_ENDPOINT` or `telemetry.endpoint`, reports go there instead, and
this notice does not cover that destination.

**How long.** Raw reports: 90 days. Figures and error reports made from basic reports, which
identify no one: 24 months. Detailed reports (with the install id): 13 months, then only
figures without the id.

**Your rights.** You can read everything sent from your install (`kranto telemetry show --sent`,
Settings › Privacy & access). For detailed reports you have the rights of access, erasure and objection:
ask the maintainer to contact you as described under Who (with no personal data and no install
id in the issue), then give the install id Settings › Privacy & access shows. Basic reports carry no
identifier, so the controller cannot find "your" basic reports to delete them; you can delete
your local copies. You may complain to your data protection authority.

**Separately: the update check.** When update checks are on (Settings › System › Updates), Kranto asks
GitHub's API for the newest release once a day; GitHub sees your address under GitHub's
privacy statement. That is not a usage report and is not covered by the choice above.

**Separately: Feedback.** Feedback (in the app's header) sends nothing by itself. File it
files the issue you read, through your own `gh` login, on Kranto's repository on GitHub; Open on
GitHub opens GitHub's new-issue page with it filled in, and you submit it there. Either way it
is a GitHub issue under GitHub's privacy statement, readable by whoever can see that repository,
and what it carries is shown to you before it is sent. That is not a usage report and is not
covered by the choice above.

## Every report: what kind of install sent it

| Field | Type | Tier | Example | Why |
|---|---|---|---|---|
| `schema` | whole number 1 to 1 | basic | 1 | the version of this list |
| `tier` | one of: basic, detailed | basic | basic | which fields may follow |
| `version` | text matching the pattern `version` | basic | 0.3.82 | errors and update health by version |
| `channel` | one of: stable, nightly, rc, main | basic | stable | the update channel |
| `os` | one of: linux, darwin, windows, other | basic | linux | the operating system family |
| `distro` | one of: debian, fedora, arch, suse, alpine, nixos, macos, other | basic | debian | install bugs by family; never the version string |
| `arch` | one of: x86_64, arm64, other | basic | x86_64 | the processor family |
| `python` | one of: 3.12, 3.13, 3.14, other | basic | 3.12 | the Python minor version |
| `run_mode` | one of: systemd, foreground, docker, other | basic | systemd | how Kranto runs: the service, the foreground or a container |
| `install_id` | text matching the pattern `uuid4` | detailed only | a random id | detailed only: a random id, replaced every 180 days or when you reset it |
| `country` | text matching the pattern `country` | added by the server | DE | set by the receiving server from the connection, never by Kranto; the address is discarded |
| `relay_dropped` | whole number 0 to 100000 | added by the server | 0 | set by the receiving server: keys from a newer Kranto it did not know yet, dropped |
| `relay_other` | whole number 0 to 100000 | added by the server | 0 | set by the receiving server: routes and actions from a newer Kranto it did not know yet, counted as other |

## The daily report (basic and detailed)

Placeholders in angle brackets stand for one field per value: `actions.<action>` is `actions.publish`, `actions.retry` and so on.

| Field | Type | Example | Why |
|---|---|---|---|
| `day` | text matching the pattern `day` | 2026-10-17 | the day the report covers (UTC): the only time in it |
| `install_age_weeks` | whole number 0 to 52 | 3 | weeks since the install began, capped at 52: retention by cohort |
| `milestones.<milestone>` | true or false | True | set once and then true: the funnel, without an identifier |
| `actions.<action>` | whole number 0 to 100000 | 4 | how often each button or command was used; never what it was used on |
| `actions_by_origin.<origin>` | whole number 0 to 100000 | 2 | which doors are used: the page, kranto mcp, the command line, the loop |
| `actions_refused` | whole number 0 to 100000 | 0 | actions refused or failed |
| `pages.<node>` | whole number 0 to 100000 | 9 | page views by page; never which object was open |
| `pages.load_ms_p50` | whole number 0 to 600000 | 420 | how long pages take to show |
| `watch.items_judged` | whole number 0 to 1000000 | 453 | the watcher's volume, not its content |
| `watch.items_kept` | whole number 0 to 1000000 | 251 | items kept as observations |
| `watch.cards_written` | whole number 0 to 10000 | 3 | idea cards written |
| `watch.usd_cents` | whole number 0 to 10000000 | 55 | what watching cost that day, in cents |
| `watch.sources_by_kind.<source_kind>` | whole number 0 to 999 | 12 | which kinds of source are used; never a URL |
| `topics_count` | whole number 0 to 999 | 3 | how many topics (capped at 999) |
| `sources_count` | whole number 0 to 999 | 33 | how many sources (capped at 999) |
| `api.requests` | whole number 0 to 100000000 | 4120 | requests the server answered |
| `api.latency_ms_p50` | whole number 0 to 600000 | 18 | how fast the server answers (median) |
| `api.latency_ms_p95` | whole number 0 to 600000 | 140 | how fast the server answers (95th percentile) |
| `api.latency_ms_p99` | whole number 0 to 600000 | 600 | how fast the server answers (99th percentile) |
| `api.errors_4xx` | whole number 0 to 100000000 | 12 | requests refused |
| `api.errors_5xx` | whole number 0 to 100000000 | 0 | requests that failed |
| `api.slow.<route>` | whole number 0 to 100000000 | 3 | requests over a second, by route pattern; never the address's ids |
| `update.checked` | whole number 0 to 1000 | 1 | update checks that worked |
| `update.check_failed` | whole number 0 to 1000 | 0 | update checks that failed |
| `update.applied` | whole number 0 to 1000 | 1 | updates applied |
| `update.rolled_back` | whole number 0 to 1000 | 0 | updates rolled back |
| `update.failed` | whole number 0 to 1000 | 0 | updates that failed |
| `update.stop_warning` | whole number 0 to 1000 | 0 | updates where the old server did not stop cleanly |
| `update.from_version` | text matching the pattern `version` | 0.3.81 | the version the last update came from: upgrade paths |
| `errors.<fingerprint>` | whole number 0 to 1000000 | errors.KeyError:kranto.page.loop.gate.hold:212: 2 | errors by class and the lines of Kranto's own code they passed through; never the message |
| `errors.other` | whole number 0 to 1000000 | 0 | errors past the twentieth distinct one that day |
| `settings.caps_set` | one of: none, watch, deep_dive, several | none | whether spend caps are used |
| `settings.term_enabled` | true or false | False | whether Open in Claude Code is on |
| `settings.auto_update_idle` | true or false | False | whether updates apply by themselves when idle |
| `models.judge` | one of: claude-haiku-5-5, claude-sonnet-5-5, claude-opus-5-5, claude-fable-5-1, claude-sonnet-5, claude-haiku-4-5, other | claude-haiku-5-5 | the watcher's judge model |
| `models.reason` | one of: claude-haiku-5-5, claude-sonnet-5-5, claude-opus-5-5, claude-fable-5-1, claude-sonnet-5, claude-haiku-4-5, other | claude-sonnet-5-5 | the watcher's reasoning model |
| `provider` | one of: openrouter, anthropic, openai_compat, claude_code | openrouter | which model provider the watcher uses |
| `dropped_fields` | whole number 0 to 100000000 | 0 | values the allow-list dropped that day: a check on Kranto itself |
| `sample_rate` | whole number 1 to 100 | 100 | reserved for sampling: 100 means everything |

Where the placeholders' values come from:

- `<action>`: one per action Kranto has (the buttons and commands: `src/kranto/page/telemetry.json`, `action`)
- `<fingerprint>`: text matching `^[A-Z][A-Za-z0-9_]{0,63}(:kranto(\.[a-z_][a-z0-9_]{0,40}){0,6}\.[A-Za-z_<>][A-Za-z0-9_<>]{0,60}:\d{1,6}){1,5}$` (the exception's class and up to five lines of Kranto's own code; never its message)
- `<milestone>`: setup_done, first_topic, first_source, first_idea, first_update
- `<node>`: one per page of the app (`src/kranto/page/telemetry.json`, `node`)
- `<origin>`: ui, mcp, cli, auto, honesty, agent
- `<route>`: /, /api/activity, /api/activity/dismiss, /api/activity/{uuid}/stop, /api/archive, /api/archive/themes, /api/archive/themes/{lineage_id}, /api/asks, /api/assistant/global, /api/catalog, /api/clusters, /api/connections, /api/connections/{conn_id}/disconnect, /api/connections/{conn_id}/test, /api/connections/{provider}/credentials, /api/cubs, /api/cubs/check, /api/cubs/fetch, /api/cubs/jobs, /api/cubs/jobs/{job}, /api/cubs/jobs/{job}/cancel, /api/cubs/settings, /api/cubs/{id}, /api/cubs/{id}/apply_update, /api/cubs/{id}/disable, /api/cubs/{id}/dry, /api/cubs/{id}/enable, /api/cubs/{id}/install, /api/cubs/{id}/live, /api/cubs/{id}/log, /api/cubs/{id}/remove, /api/cubs/{id}/resume, /api/cubs/{id}/run, /api/cubs/{id}/stop, /api/cubs/{id}/update, /api/errors, /api/errors/{error_id}, /api/events, /api/explain, /api/f/{feature}/act/{action}, /api/f/{feature}/settings, /api/f/{feature}/{name}, /api/features, /api/feedback, /api/feedback/vocabulary, /api/grades/summary, /api/health, /api/hold, /api/home, /api/home/visit, /api/ideas, /api/ideas/{idea_id}, /api/ideas/{idea_id}/later, /api/ideas/{idea_id}/outcome, /api/map, /api/newsletter, /api/newsletter/audience, /api/newsletter/check, /api/observations, /api/observations/{obs_id}, /api/observations/{obs_id}/remove, /api/post, /api/post/angles, /api/post/d/{id:int}, /api/post/d/{id:int}.md, /api/post/d/{id:int}/cancel, /api/post/d/{id:int}/edit, /api/post/d/{id:int}/posted, /api/post/learned, /api/post/sites, /api/post/write, /api/post/write/dismiss, /api/prepared, /api/prepared/{uuid}/{what}, /api/prompts, /api/prompts/preview, /api/prompts/{pid}, /api/prompts/{pid}/reset, /api/prompts/{pid}/restore, /api/prompts/{pid}/versions/{n:int}, /api/prompts/{pid}/versions/{n:int}/note, /api/prose, /api/prose/check, /api/prose/learn, /api/prose/revise, /api/prose/writer-key, /api/prose/voice, /api/prose/voice/draft, /api/read/{name}, /api/requests, /api/requests/{id}, /api/requests/{id}/confirm, /api/requests/{id}/decline, /api/review/queue, /api/rollups, /api/runs, /api/runs/{uuid}, /api/search, /api/seen, /api/selfcheck/paths, /api/settings/assistant, /api/settings/activity, /api/settings/models, /api/settings/reading, /api/settings/service, /api/settings/spend, /api/settings/telemetry, /api/settings/telemetry/page, /api/settings/telemetry/report, /api/setup, /api/setup/check, /api/setup/finish, /api/setup/provider, /api/setup/search, /api/setup/search/callers, /api/shell, /api/sources, /api/sources/approve, /api/sources/from-text, /api/sources/from-text/{batch:int}, /api/sources/preview, /api/sources/{source_id}, /api/sources/{source_id}/fetch, /api/sources/{source_id}/keep, /api/sources/{source_id}/mute, /api/sources/{source_id}/retention, /api/sources/{source_id}/status, /api/spend/topics, /api/status, /api/telemetry/view, /api/themes/{lineage}/card, /api/tickets, /api/tickets/{id}, /api/tickets/{id}/again, /api/tickets/{id}/ask, /api/tickets/{id}/confirm, /api/tickets/{id}/decline, /api/today, /api/tokens, /api/tokens/{name}/{what}, /api/topics, /api/topics/{topic_id:int}, /api/topics/{topic_id:int}/sources, /api/topics/{topic_id:int}/start, /api/topics/{topic_id:int}/status, /api/topics/{topic_id}/scout, /api/update, /api/update/cancel, /api/update/check, /api/update/promote, /api/update/rollback, /api/update/settings, /api/verbs, /api/verbs/recent, /api/verbs/{kind}, /api/watch/resume, /api/websearch, /api/websearch/fetch, /api/whoami, /auth/code, /auth/open, /auth/signout, /brb, /brb/{path:path}, /clusters, /clusters/{cluster}/explain, /connections, /connections/{conn_id:int}/{action}, /connections/{provider}/callback, /connections/{provider}/credentials, /connections/{provider}/device, /connections/{provider}/device/poll, /connections/{provider}/start, /feed.xml, /grade/{target}/{target_id}, /health, /ideas, /library, /map, /obs/{obs_id}, /obs/{obs_id}/explain, /pause, /resume, /rollups, /run/{kind}, /sources, /sources/{source_id}/status, /static, /topics, /topics/{topic_id}/scout, /watches, other
- `<source_kind>`: rss, hackernews, reddit, arxiv, bluesky, mastodon, github, youtube, producthunt, stackexchange, parallax, other

## Error reports (basic and detailed)

Error reports follow your choice exactly: with `basic` or `detailed`, when something fails in Kranto (a request, a scheduled job, one row of a list, the build loop, an update's self-check) an error report is sent within minutes; with `local`, `off`, before you answer, or with `DO_NOT_TRACK=1`, none is kept or sent, and choosing `local` or `off` deletes any waiting. Each report goes with the fields above (`basic`: no identifier; `detailed`: the install id too) and a time no finer than the hour. The same error is reported at most once an hour, with a count of how often it happened; at most 4 batches of at most 10 reports go in an hour, and at most 50 reports a day. Read the reports waiting with `kranto telemetry show --errors` (`--wire` for the exact bytes) and every batch sent with `kranto telemetry show --sent`, or in Settings › Privacy & access.

| Field | Type | Example | Why |
|---|---|---|---|
| `signature` | text matching the pattern `signature` | 9c1e5a07d2f44b18 | a hash of the type and Kranto functions it passed through: the same error has the same signature on every install and release |
| `type` | text matching the pattern `exc_type` | TypeError | the exception's class: a built-in, a library's (its package and the class) or Kranto's own |
| `where` | one of: ui, api, scheduler, loop, build, cli, job, row, update, console | api | where it happened: a request (api), a scheduled job (scheduler, job), one row of a list (row), the build loop (loop), an update's self-check (update), a Kranto tool call in an assistant's session (console) |
| `route` | one of: /, /api/activity, /api/activity/dismiss, /api/activity/{uuid}/stop, /api/archive, /api/archive/themes, /api/archive/themes/{lineage_id}, /api/asks, /api/assistant/global, /api/catalog, /api/clusters, /api/connections, /api/connections/{conn_id}/disconnect, /api/connections/{conn_id}/test, /api/connections/{provider}/credentials, /api/cubs, /api/cubs/check, /api/cubs/fetch, /api/cubs/jobs, /api/cubs/jobs/{job}, /api/cubs/jobs/{job}/cancel, /api/cubs/settings, /api/cubs/{id}, /api/cubs/{id}/apply_update, /api/cubs/{id}/disable, /api/cubs/{id}/dry, /api/cubs/{id}/enable, /api/cubs/{id}/install, /api/cubs/{id}/live, /api/cubs/{id}/log, /api/cubs/{id}/remove, /api/cubs/{id}/resume, /api/cubs/{id}/run, /api/cubs/{id}/stop, /api/cubs/{id}/update, /api/errors, /api/errors/{error_id}, /api/events, /api/explain, /api/f/{feature}/act/{action}, /api/f/{feature}/settings, /api/f/{feature}/{name}, /api/features, /api/feedback, /api/feedback/vocabulary, /api/grades/summary, /api/health, /api/hold, /api/home, /api/home/visit, /api/ideas, /api/ideas/{idea_id}, /api/ideas/{idea_id}/later, /api/ideas/{idea_id}/outcome, /api/map, /api/newsletter, /api/newsletter/audience, /api/newsletter/check, /api/observations, /api/observations/{obs_id}, /api/observations/{obs_id}/remove, /api/post, /api/post/angles, /api/post/d/{id:int}, /api/post/d/{id:int}.md, /api/post/d/{id:int}/cancel, /api/post/d/{id:int}/edit, /api/post/d/{id:int}/posted, /api/post/learned, /api/post/sites, /api/post/write, /api/post/write/dismiss, /api/prepared, /api/prepared/{uuid}/{what}, /api/prompts, /api/prompts/preview, /api/prompts/{pid}, /api/prompts/{pid}/reset, /api/prompts/{pid}/restore, /api/prompts/{pid}/versions/{n:int}, /api/prompts/{pid}/versions/{n:int}/note, /api/prose, /api/prose/check, /api/prose/learn, /api/prose/revise, /api/prose/writer-key, /api/prose/voice, /api/prose/voice/draft, /api/read/{name}, /api/requests, /api/requests/{id}, /api/requests/{id}/confirm, /api/requests/{id}/decline, /api/review/queue, /api/rollups, /api/runs, /api/runs/{uuid}, /api/search, /api/seen, /api/selfcheck/paths, /api/settings/assistant, /api/settings/activity, /api/settings/models, /api/settings/reading, /api/settings/service, /api/settings/spend, /api/settings/telemetry, /api/settings/telemetry/page, /api/settings/telemetry/report, /api/setup, /api/setup/check, /api/setup/finish, /api/setup/provider, /api/setup/search, /api/setup/search/callers, /api/shell, /api/sources, /api/sources/approve, /api/sources/from-text, /api/sources/from-text/{batch:int}, /api/sources/preview, /api/sources/{source_id}, /api/sources/{source_id}/fetch, /api/sources/{source_id}/keep, /api/sources/{source_id}/mute, /api/sources/{source_id}/retention, /api/sources/{source_id}/status, /api/spend/topics, /api/status, /api/telemetry/view, /api/themes/{lineage}/card, /api/tickets, /api/tickets/{id}, /api/tickets/{id}/again, /api/tickets/{id}/ask, /api/tickets/{id}/confirm, /api/tickets/{id}/decline, /api/today, /api/tokens, /api/tokens/{name}/{what}, /api/topics, /api/topics/{topic_id:int}, /api/topics/{topic_id:int}/sources, /api/topics/{topic_id:int}/start, /api/topics/{topic_id:int}/status, /api/topics/{topic_id}/scout, /api/update, /api/update/cancel, /api/update/check, /api/update/promote, /api/update/rollback, /api/update/settings, /api/verbs, /api/verbs/recent, /api/verbs/{kind}, /api/watch/resume, /api/websearch, /api/websearch/fetch, /api/whoami, /auth/code, /auth/open, /auth/signout, /brb, /brb/{path:path}, /clusters, /clusters/{cluster}/explain, /connections, /connections/{conn_id:int}/{action}, /connections/{provider}/callback, /connections/{provider}/credentials, /connections/{provider}/device, /connections/{provider}/device/poll, /connections/{provider}/start, /feed.xml, /grade/{target}/{target_id}, /health, /ideas, /library, /map, /obs/{obs_id}, /obs/{obs_id}/explain, /pause, /resume, /rollups, /run/{kind}, /sources, /sources/{source_id}/status, /static, /topics, /topics/{topic_id}/scout, /watches, other | /api/topics/{topic_id:int} | the route's pattern when it happened in a request; never the address or its ids |
| `job` | one of: ingest, snapshot, compact, xrecheck, deepdive, ideas, heartbeat, update, telemetry, cubs.gc, cubs.updates, invest.scan, invest.mark, invest.track, radar.run, news.brief, loop, other | ingest | the job's kind when it happened in one (a cub's job is other) |
| `message` | text of at most 200 characters: only the words listed below, `<x>`, `<n>` and punctuation | unsupported format string passed to NoneType.__format__ | the message as a template: only the words listed below survive, a number is <n>, any other word, a path, an address or a quoted value is <x> |
| `stack` | text matching the pattern `stack` | [starlette] > kranto.web.topics_api.one_topic:226 > kranto.source_health._status:209 | where in Kranto's code: each of Kranto's own functions as module.function:line, a library's frames as [its package]; never a file path, a value or a variable |
| `verb` | one of: topic.add, topic.edit, topic.sources, topic.pause, topic.resume, topic.archive, topic.restore, topic.scout, source.add, source.approve, source.from_text, source.retire, source.reapprove, source.dismiss, source.fetch, source.retention, source.mute, source.keep, source.preview, connection.test, connection.disconnect, connection.credentials, connection.device, connection.start, library.explain, observation.remove, idea.later, theme.card, post.write, post.edit, prose.check, prose.voice, prose.learn, feedback.add, today.seen, kranto.pause, kranto.resume, job.run_now, watch.resume, run.stop, activity.dismiss, activity.settings, settings.service_memory, settings.models, settings.spend, settings.reading, settings.search_callers, settings.telemetry, telemetry.off, setup.finish, setup.check, setup.provider, setup.search, prose.writer_key, token.add, token.change, prompt.preview, prompt.save, prompt.reset, prompt.restore, prompt.note, update.check, update.apply, update.cancel, update.rollback, update.settings, update.hold, update.release_hold, cub.check, cub.fetch, cub.install, cub.update, cub.apply_update, cub.remove, cub.enable, cub.disable, cub.stop, cub.resume, cub.dry, cub.live, cub.run, cub.cancel_job, cubs.settings, feature.setting, ticket.confirm, ticket.decline, ticket.again, newsletter.check, newsletter.audience, assistant.ladder, assistant.global, f.news.toggle, f.news.write_now, f.news.article_now, other | topic.add | the console's own errors (where console): the verb whose tool call failed or timed out; never its fields |
| `count` | whole number 1 to 1000000 | 3 | how often it happened since this signature was last reported |

Where the values come from:

- `<where>`: ui, api, scheduler, loop, build, cli, job, row, update, console
- `<job>`: ingest, snapshot, compact, xrecheck, deepdive, ideas, heartbeat, update, telemetry, cubs.gc, cubs.updates, invest.scan, invest.mark, invest.track, radar.run, news.brief, loop, other
- `<route>`: the route patterns listed under `api.slow.<route>` above
- the words a message may keep (any other word becomes `<x>`, a number `<n>`): `a`, `about`, `above`, `accept`, `accepted`, `access`, `acquire`, `address`, `after`, `again`, `all`, `allowed`, `already`, `an`, `and`, `another`, `answer`, `any`, `are`, `argument`, `arguments`, `as`, `ascii`, `assignment`, `at`, `attempt`, `attribute`, `attributes`, `await`, `awaitable`, `aware`, `bad`, `base`, `be`, `been`, `before`, `between`, `blob`, `block`, `body`, `bool`, `bound`, `bounds`, `broken`, `build`, `busy`, `but`, `by`, `byte`, `bytes`, `call`, `callable`, `called`, `calling`, `can`, `cannot`, `card`, `certificate`, `changed`, `char`, `character`, `characters`, `check`, `circular`, `class`, `client`, `close`, `closed`, `code`, `codec`, `column`, `columns`, `commit`, `compare`, `comparison`, `complex`, `concatenate`, `config`, `conflict`, `connect`, `connection`, `constraint`, `contain`, `contains`, `content`, `control`, `convert`, `coroutine`, `could`, `cub`, `cursor`, `data`, `database`, `date`, `datetime`, `day`, `decimal`, `decode`, `defined`, `deleted`, `deletion`, `delimiter`, `denied`, `depth`, `dict`, `dictionary`, `did`, `directory`, `disk`, `division`, `do`, `does`, `domain`, `double`, `due`, `during`, `each`, `element`, `empty`, `encode`, `encoding`, `end`, `enough`, `equal`, `error`, `escape`, `event`, `exceeded`, `exception`, `exist`, `exists`, `expected`, `expecting`, `expression`, `extra`, `failed`, `failure`, `false`, `few`, `field`, `fields`, `file`, `float`, `for`, `format`, `found`, `free`, `from`, `frozenset`, `full`, `function`, `generator`, `given`, `got`, `greater`, `group`, `handling`, `has`, `hashable`, `have`, `header`, `host`, `hour`, `http`, `id`, `if`, `immutable`, `import`, `in`, `incomplete`, `index`, `indices`, `initialized`, `input`, `instance`, `instances`, `int`, `integer`, `integers`, `interrupted`, `into`, `invalid`, `is`, `item`, `items`, `iterable`, `iteration`, `iterator`, `job`, `json`, `key`, `keys`, `keyword`, `large`, `larger`, `length`, `less`, `likely`, `limit`, `line`, `list`, `literal`, `local`, `lock`, `locked`, `malformed`, `many`, `mapping`, `match`, `maximum`, `may`, `memory`, `message`, `method`, `minute`, `missing`, `mode`, `module`, `month`, `more`, `most`, `must`, `naive`, `name`, `near`, `negative`, `network`, `no`, `non`, `none`, `not`, `nothing`, `number`, `object`, `occurred`, `of`, `offset`, `on`, `one`, `only`, `open`, `operand`, `operation`, `or`, `ordinal`, `other`, `out`, `overflow`, `page`, `parse`, `partially`, `passed`, `path`, `pattern`, `permission`, `pipe`, `port`, `position`, `positional`, `positive`, `process`, `property`, `protocol`, `query`, `quotes`, `range`, `read`, `readonly`, `real`, `received`, `recursion`, `referenced`, `refused`, `remains`, `report`, `request`, `required`, `requires`, `reset`, `resource`, `response`, `result`, `returned`, `route`, `row`, `rows`, `run`, `running`, `s`, `schema`, `scheme`, `second`, `sequence`, `server`, `set`, `should`, `size`, `slice`, `smaller`, `source`, `ssl`, `start`, `started`, `status`, `still`, `stop`, `stopped`, `str`, `string`, `subscriptable`, `such`, `support`, `supported`, `syntax`, `table`, `t`, `take`, `takes`, `than`, `that`, `the`, `this`, `thread`, `time`, `timed`, `timeout`, `timezone`, `to`, `token`, `too`, `topic`, `true`, `tuple`, `type`, `types`, `unable`, `unavailable`, `unbound`, `unconverted`, `unexpected`, `unique`, `unknown`, `unpack`, `unreachable`, `unsupported`, `unterminated`, `update`, `url`, `utf`, `value`, `values`, `variable`, `verify`, `version`, `was`, `were`, `when`, `while`, `with`, `without`, `would`, `write`, `year`, `zero`, `None`, `NoneType`, `True`, `False`, `__aenter__`, `__aexit__`, `__await__`, `__bool__`, `__call__`, `__contains__`, `__delitem__`, `__enter__`, `__eq__`, `__exit__`, `__float__`, `__format__`, `__ge__`, `__getattr__`, `__getitem__`, `__gt__`, `__hash__`, `__index__`, `__init__`, `__int__`, `__iter__`, `__le__`, `__len__`, `__lt__`, `__new__`, `__next__`, `__round__`, `__setitem__`, `__str__`

## The assistant's usage (detailed only)

With `detailed`, and only then, Kranto also sends how its assistant tools are used, hour by hour: with `basic`, `local`, `off`, before you answer, or with `DO_NOT_TRACK=1`, none is kept or sent, and leaving `detailed` deletes any waiting. The hours that have ended go together, at most 200 records a request and 3 requests an hour (a long session is one request an hour, not one a call), with the resource above (the install id included) and a time no finer than the hour. A Kranto tool call that fails or times out in an assistant's session is an error report (`where: console`, above), which follows the error reports' choice. Read what waits with `kranto telemetry show --assistant` (`--wire` for the exact bytes) and every batch sent with `kranto telemetry show --sent`.

**Your consent is yours.** Choosing `basic` or `detailed` is done by you on the page (Settings › Privacy & access) or in your own terminal: an assistant working in Kranto can prepare the choice for your approval (verb `settings.telemetry`), never make it, under every assistant setting; `kranto telemetry basic|detailed` is refused inside an assistant's session. Over HTTP only the page, signed in, can choose them: a token (the command line's, an assistant's) is refused, and so is everyone when the server's tokens are switched off. An assistant may turn reports off at once (verb `telemetry.off`). The first time Kranto's plugin starts in an install that never answered, it shows one line pointing to `/kranto:telemetry` and this setting, and never again.

### `kranto.verb`: a verb's calls in one hour

One record per hour, verb, door, assistant, outcome, refusal kind and rung, counted by Kranto itself at the verbs' door (so Codex and any client without hooks are covered), and for the page's own clicks by their route.

| Field | Type | Example | Why |
|---|---|---|---|
| `verb` (always) | one of: topic.add, topic.edit, topic.sources, topic.pause, topic.resume, topic.archive, topic.restore, topic.scout, source.add, source.approve, source.from_text, source.retire, source.reapprove, source.dismiss, source.fetch, source.retention, source.mute, source.keep, source.preview, connection.test, connection.disconnect, connection.credentials, connection.device, connection.start, library.explain, observation.remove, idea.later, theme.card, post.write, post.edit, prose.check, prose.voice, prose.learn, feedback.add, today.seen, kranto.pause, kranto.resume, job.run_now, watch.resume, run.stop, activity.dismiss, activity.settings, settings.service_memory, settings.models, settings.spend, settings.reading, settings.search_callers, settings.telemetry, telemetry.off, setup.finish, setup.check, setup.provider, setup.search, prose.writer_key, token.add, token.change, prompt.preview, prompt.save, prompt.reset, prompt.restore, prompt.note, update.check, update.apply, update.cancel, update.rollback, update.settings, update.hold, update.release_hold, cub.check, cub.fetch, cub.install, cub.update, cub.apply_update, cub.remove, cub.enable, cub.disable, cub.stop, cub.resume, cub.dry, cub.live, cub.run, cub.cancel_job, cubs.settings, feature.setting, ticket.confirm, ticket.decline, ticket.again, newsletter.check, newsletter.audience, assistant.ladder, assistant.global, f.news.toggle, f.news.write_now, f.news.article_now, other | topic.add | the verb's name (what kind of change), never what it was used on |
| `surface` (always) | one of: ui, console, mcp, cli, agent | console | the door it came through: the page (ui), the console, kranto mcp (mcp), the command line (cli), a named agent |
| `client` (always) | one of: claude-code, codex, other, none | claude-code | which assistant asked (from its token or session), none for the page and the command line |
| `outcome` (always) | one of: ok, refused, failed, prepared, confirmed, dismissed | ok | done, refused, failed, prepared for your approval, or that action later confirmed or dismissed |
| `refusal` | one of: door, reads_only, never, locked, fields, subject, signed_out, starting | never | a refusal's kind (never its words): the wrong door, reads only, off by your ladder, a lock, bad fields, no subject, signed out, still starting |
| `rung` (always) | one of: owner, do, ask, never, lock | do | the ladder's rung in force: you yourself (owner), Do it, Ask me, Never, or a lock |
| `count` (always) | whole number 1 to 1000000 | 4 | how many such calls in that hour |
| `ms_p50` | whole number 0 to 600000 | 180 | how long they took (median, milliseconds) |
| `ms_max` | whole number 0 to 600000 | 950 | how long the slowest took (milliseconds) |

One, exactly as it would be posted (before gzip):

```json
{
 "resourceLogs": [
  {
   "resource": {
    "attributes": [
     {
      "key": "service.name",
      "value": {
       "stringValue": "kranto"
      }
     },
     {
      "key": "host.arch",
      "value": {
       "stringValue": "x86_64"
      }
     },
     {
      "key": "kranto.channel",
      "value": {
       "stringValue": "stable"
      }
     },
     {
      "key": "kranto.distro",
      "value": {
       "stringValue": "debian"
      }
     },
     {
      "key": "kranto.install_id",
      "value": {
       "stringValue": "8a1f3c52-1111-4222-8333-444455556666"
      }
     },
     {
      "key": "os.type",
      "value": {
       "stringValue": "linux"
      }
     },
     {
      "key": "kranto.python",
      "value": {
       "stringValue": "3.12"
      }
     },
     {
      "key": "kranto.run_mode",
      "value": {
       "stringValue": "systemd"
      }
     },
     {
      "key": "kranto.schema",
      "value": {
       "intValue": "1"
      }
     },
     {
      "key": "kranto.tier",
      "value": {
       "stringValue": "detailed"
      }
     },
     {
      "key": "service.version",
      "value": {
       "stringValue": "0.3.82"
      }
     }
    ]
   },
   "scopeLogs": [
    {
     "logRecords": [
      {
       "attributes": [
        {
         "key": "event.name",
         "value": {
          "stringValue": "kranto.verb"
         }
        },
        {
         "key": "kranto.client",
         "value": {
          "stringValue": "claude-code"
         }
        },
        {
         "key": "kranto.count",
         "value": {
          "intValue": "4"
         }
        },
        {
         "key": "kranto.ms_max",
         "value": {
          "intValue": "950"
         }
        },
        {
         "key": "kranto.ms_p50",
         "value": {
          "intValue": "180"
         }
        },
        {
         "key": "kranto.outcome",
         "value": {
          "stringValue": "ok"
         }
        },
        {
         "key": "kranto.refusal",
         "value": {
          "stringValue": "never"
         }
        },
        {
         "key": "kranto.rung",
         "value": {
          "stringValue": "do"
         }
        },
        {
         "key": "kranto.surface",
         "value": {
          "stringValue": "console"
         }
        },
        {
         "key": "kranto.verb",
         "value": {
          "stringValue": "topic.add"
         }
        }
       ],
       "body": {
        "stringValue": "kranto.verb"
       },
       "severityNumber": 9,
       "severityText": "INFO",
       "timeUnixNano": "1793174400000000000"
      }
     ],
     "scope": {
      "name": "kranto.telemetry",
      "version": "1"
     }
    }
   ]
  }
 ]
}
```

### `kranto.session`: one assistant session

One record per session that ended (or went idle for 12 hours), from Kranto's plugin hooks in Claude Code and Codex. The session's id pairs its start with its end on your machine, as a hash, and is never sent.

| Field | Type | Example | Why |
|---|---|---|---|
| `assistant` (always) | one of: claude-code, codex, other | claude-code | which assistant the session was |
| `model` | one of: claude-haiku-5-5, claude-sonnet-5-5, claude-opus-5-5, claude-fable-5-1, claude-sonnet-5, claude-haiku-4-5, other | claude-sonnet-5-5 | its model, when it is one of the listed (else other) |
| `place` (always) | one of: console, outside | console | the console in Kranto's page, or your own assistant outside it |
| `profile` | one of: full, compact | full | Kranto's tools as the full list or the compact profile |
| `start` | one of: startup, resume, clear, compact, other | startup | how it started: new, resumed, after /clear, after a compaction |
| `end` | one of: clear, logout, prompt_input_exit, exit, idle, other | prompt_input_exit | how it ended, as the assistant says it |
| `minutes` (always) | whole number 0 to 100000 | 42 | how long the session lasted, in whole minutes |
| `turns` | whole number 0 to 100000 | 9 | how many answers the assistant gave |
| `tool_calls` | whole number 0 to 100000 | 14 | how many of Kranto's tools it called |
| `tool_failures` | whole number 0 to 100000 | 1 | how many of those failed or timed out |
| `commands` | whole number 0 to 100000 | 2 | how many of Kranto's slash commands were used |

One, exactly as it would be posted (before gzip):

```json
{
 "resourceLogs": [
  {
   "resource": {
    "attributes": [
     {
      "key": "service.name",
      "value": {
       "stringValue": "kranto"
      }
     },
     {
      "key": "host.arch",
      "value": {
       "stringValue": "x86_64"
      }
     },
     {
      "key": "kranto.channel",
      "value": {
       "stringValue": "stable"
      }
     },
     {
      "key": "kranto.distro",
      "value": {
       "stringValue": "debian"
      }
     },
     {
      "key": "kranto.install_id",
      "value": {
       "stringValue": "8a1f3c52-1111-4222-8333-444455556666"
      }
     },
     {
      "key": "os.type",
      "value": {
       "stringValue": "linux"
      }
     },
     {
      "key": "kranto.python",
      "value": {
       "stringValue": "3.12"
      }
     },
     {
      "key": "kranto.run_mode",
      "value": {
       "stringValue": "systemd"
      }
     },
     {
      "key": "kranto.schema",
      "value": {
       "intValue": "1"
      }
     },
     {
      "key": "kranto.tier",
      "value": {
       "stringValue": "detailed"
      }
     },
     {
      "key": "service.version",
      "value": {
       "stringValue": "0.3.82"
      }
     }
    ]
   },
   "scopeLogs": [
    {
     "logRecords": [
      {
       "attributes": [
        {
         "key": "event.name",
         "value": {
          "stringValue": "kranto.session"
         }
        },
        {
         "key": "kranto.assistant",
         "value": {
          "stringValue": "claude-code"
         }
        },
        {
         "key": "kranto.commands",
         "value": {
          "intValue": "2"
         }
        },
        {
         "key": "kranto.end",
         "value": {
          "stringValue": "prompt_input_exit"
         }
        },
        {
         "key": "kranto.minutes",
         "value": {
          "intValue": "42"
         }
        },
        {
         "key": "kranto.model",
         "value": {
          "stringValue": "claude-sonnet-5-5"
         }
        },
        {
         "key": "kranto.place",
         "value": {
          "stringValue": "console"
         }
        },
        {
         "key": "kranto.profile",
         "value": {
          "stringValue": "full"
         }
        },
        {
         "key": "kranto.start",
         "value": {
          "stringValue": "startup"
         }
        },
        {
         "key": "kranto.tool_calls",
         "value": {
          "intValue": "14"
         }
        },
        {
         "key": "kranto.tool_failures",
         "value": {
          "intValue": "1"
         }
        },
        {
         "key": "kranto.turns",
         "value": {
          "intValue": "9"
         }
        }
       ],
       "body": {
        "stringValue": "kranto.session"
       },
       "severityNumber": 9,
       "severityText": "INFO",
       "timeUnixNano": "1793174400000000000"
      }
     ],
     "scope": {
      "name": "kranto.telemetry",
      "version": "1"
     }
    }
   ]
  }
 ]
}
```

### `kranto.command`: a slash command's uses in one hour

One record per hour, Kranto slash command and assistant. Only a prompt that starts with `/kranto:` is looked at, and only the command's name is kept.

| Field | Type | Example | Why |
|---|---|---|---|
| `command` (always) | one of: kranto, add-topic, status, telemetry, report-issue | status | one of Kranto's slash commands (/kranto:status), by name; never the rest of what you typed |
| `assistant` (always) | one of: claude-code, codex, other | claude-code | in which assistant |
| `count` (always) | whole number 1 to 100000 | 1 | how often in that hour |

One, exactly as it would be posted (before gzip):

```json
{
 "resourceLogs": [
  {
   "resource": {
    "attributes": [
     {
      "key": "service.name",
      "value": {
       "stringValue": "kranto"
      }
     },
     {
      "key": "host.arch",
      "value": {
       "stringValue": "x86_64"
      }
     },
     {
      "key": "kranto.channel",
      "value": {
       "stringValue": "stable"
      }
     },
     {
      "key": "kranto.distro",
      "value": {
       "stringValue": "debian"
      }
     },
     {
      "key": "kranto.install_id",
      "value": {
       "stringValue": "8a1f3c52-1111-4222-8333-444455556666"
      }
     },
     {
      "key": "os.type",
      "value": {
       "stringValue": "linux"
      }
     },
     {
      "key": "kranto.python",
      "value": {
       "stringValue": "3.12"
      }
     },
     {
      "key": "kranto.run_mode",
      "value": {
       "stringValue": "systemd"
      }
     },
     {
      "key": "kranto.schema",
      "value": {
       "intValue": "1"
      }
     },
     {
      "key": "kranto.tier",
      "value": {
       "stringValue": "detailed"
      }
     },
     {
      "key": "service.version",
      "value": {
       "stringValue": "0.3.82"
      }
     }
    ]
   },
   "scopeLogs": [
    {
     "logRecords": [
      {
       "attributes": [
        {
         "key": "event.name",
         "value": {
          "stringValue": "kranto.command"
         }
        },
        {
         "key": "kranto.assistant",
         "value": {
          "stringValue": "claude-code"
         }
        },
        {
         "key": "kranto.command",
         "value": {
          "stringValue": "status"
         }
        },
        {
         "key": "kranto.count",
         "value": {
          "intValue": "1"
         }
        }
       ],
       "body": {
        "stringValue": "kranto.command"
       },
       "severityNumber": 9,
       "severityText": "INFO",
       "timeUnixNano": "1793174400000000000"
      }
     ],
     "scope": {
      "name": "kranto.telemetry",
      "version": "1"
     }
    }
   ]
  }
 ]
}
```

Where the values come from:

- `<verb>`: one per verb Kranto has (`core/verbs.py`; the build loop's as `b.<action>`), else other
- `<surface>`: ui, console, mcp, cli, agent
- `<client>`: claude-code, codex, other, none
- `<refusal>`: door, reads_only, never, locked, fields, subject, signed_out, starting
- `<command>`: kranto, add-topic, status, telemetry, report-issue

## Never, in any tier

- topic names and descriptions
- source URLs and names
- card, observation and idea text
- repo names and owners
- product names
- code
- prompts and model replies
- chat or terminal content
- the words of a grade
- tokens, keys and the .env
- emails and user names
- host names and file paths
- IP addresses (the receiving server reads the address only to derive a country code and discards it)
- the time zone, the locale, the screen size
- version strings of the kernel or distribution
- your GitHub login
- anything in data/secrets

The list has no field of a type that could carry them: text exists only as a closed list of values or a fixed pattern.
