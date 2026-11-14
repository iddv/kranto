# Verbs: everything you can do, for every caller

Every change you can make on a page (add a topic, approve a source, write a post, save a
setting) is a **verb** in one table, `src/kranto/core/verbs.py`. The page actions its routes
as it always has. Everyone else (the console in Kranto, your own Claude Code or Codex over
`kranto mcp`, a script with its own token) runs the same verbs through one door:

```
GET  /api/verbs                       every verb: its words, fields, doors, ladder kind, page
POST /api/verbs/<kind>                run one: {subject: {id}?, fields: {...}?, client?}
GET  /api/verbs/recent?since=<seq>    what assistants did lately, for the page's marks
GET  /api/prepared                    actions an assistant prepared, waiting for you
POST /api/prepared/<uuid>/press       you approve one (the page, signed in)
POST /api/prepared/<uuid>/dismiss     you put one away
GET  /api/settings/assistant          the ladder, as set
POST /api/settings/assistant          {ladder: {kinds: {...}, verbs: {...}}} (you only)
```

A verb calls the same route the page calls, in the same process, so it cannot do on one
surface what it does not do on another. A test (`tests/test_parity.py`) fails when a write
route has no verb, when a verb names a route that is gone, or when a lock is missing.

## Who may run what

The token decides, never the request's body (see `web/auth.py`):

| Caller | Token | The ladder |
|---|---|---|
| you, on the page | the session cookie (`ui`) | not applied: it is you |
| you, in a shell | `cli` | not applied |
| the console in Kranto | `console` | applied |
| your own assistant over `kranto mcp` | `mcp` | applied |
| a named agent | `agent:<name>` | applied |

A client may say who it is (`client`: `claude`, `codex`): those words only name it in
Activity and on the page's mark ("by Claude Code", "by Codex (outside)"). They give it nothing.

## The ladder

Each verb has a **kind**, and for each kind you choose what an assistant does:

| Kind | What is in it | Default |
|---|---|---|
| Reads | a preview, a check | Do it |
| Changes you can undo | add or edit a topic, approve a source, pause, save a setting | Do it |
| Spending | a scout, Run now, Card it now, a cap | Do it (the cost is said first) |
| What leaves Kranto | usage reports, installing a cub, an audience, new words for a waiting post | Ask me in the UI |
| What cannot be undone | archive, remove, roll back, disconnect | Ask me in the UI |
| Keys, tokens and logins | a provider key, a token, an account's credentials | Never (locked) |

**Do it** runs the verb; the answer says where it shows (`page`), the row to mark (`mark`) and
the run in Activity. **Ask me in the UI** runs nothing: the action is *prepared*, with its
fields, and waits on its page and in Needs you for 24 hours until you click it (the page's own
dialog) or dismiss it; the assistant is told that nothing has happened. **Never** refuses and
names the setting. A verb can differ from its kind (`verbs: {topic.add: ask}`).

A few fields wait for you whatever their kind says: `prose.voice`'s `voice`, `disclosure`, `always_add` and `always_remove` (they put words in every later post) are prepared, not done, when an assistant sends them, unless you chose for `prose.voice` itself. An action an assistant prepared and you approved keeps who asked for it: an edited draft says "edited by your assistant".

An action is prepared only when its action would take it: its fields are checked as the route
checks them (their type, their choices, their limits, a field of several the route needs, the
route's own rules: a preset's name, a grade), and a feature that is off says so. A refusal is
in words for every caller, never a status or a response body, and an assistant's refused verb
is in Activity (an assistant's action, skipped, with why). `tests/test_verbs.py`
and `tests/test_parity.py` keep this true.

Three things are locks, not settings: a key, a token or a login is made and pasted by you; a
house confirm (a cub going live, the cubs' master
switch) is always prepared for your approval; and **your usage-report consent**: choosing what
Kranto sends (`settings.telemetry`) is always prepared for your approval on Settings › Privacy &
access, whatever the ladder says, while turning reports off (`telemetry.off`, a change you can
undo) is done at once. What a feature or a cub asks you (send an issue,
post a toot) is approved on the page only.

The ladder is `ask.ladder` in `kranto.yaml`, written by Settings › Assistant:

```yaml
ask:
  ladder: {kinds: {spend: ask}, verbs: {topic.add: do}}
```

A choice for the kind `broker`, which left with Invest, is accepted and ignored.

## Adding a route

A new write route needs a verb in `CORE` (its kind, the button's word, plain words, the ladder
kind, its fields, doors, the page and the mark) or a line in `ROUTE_ALLOW` saying why it is not
one. A feature's or a cub's action is a verb by itself (`f.<feature>.<action>`).
