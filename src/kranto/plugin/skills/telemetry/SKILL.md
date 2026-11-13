---
name: telemetry
description: Kranto's usage reports: what is chosen, what would be sent (every field), and how to change it. Choosing to send is the owner's choice on the page only; turning reports off may be done at once.
---

Say where Kranto's usage reports stand, then what the owner can do, in at most eight lines:

1. `kranto_read` with path `/api/settings/telemetry`: the choice (`off`, `local`, `basic`,
   `detailed`, or not answered yet) and what was last sent.
2. What each choice sends, in one line each: `basic`, one small report a day and error
   reports, no identifier; `detailed`, also a random id you can reset and how Kranto's
   assistant tools are used (which verbs were called and how they ended, assistant sessions'
   length, Kranto's slash commands by name), hour by hour. Never prompts, replies, tool
   arguments or results, file contents, topic names, ids or paths.
3. Every field, with an example: `docs/privacy/what-kranto-sends.md` (the page's **What Kranto
   sends**), and `kranto telemetry show` for what is waiting now.
4. **To choose to send** (`basic` or `detailed`): only the owner's own choice on the page applies it. Say so,
   and give the page: Settings › Privacy & access (`#/settings/privacy`). If the owner asks
   you to, run the verb `settings.telemetry` with the mode: it is only **prepared** for them to
   approve there, under every ladder setting. Never edit `kranto.yaml` or run `kranto telemetry
   basic|detailed` for them: both are refused from here.
5. **To stop**: the verb `telemetry.off` turns reports off at once (no approval needed), as does
   `kranto telemetry off`.
