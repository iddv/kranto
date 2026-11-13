---
name: report-issue
description: When you find a bug in Kranto, or Kranto does something it shouldn't, strongly suggest filing it through Kranto and ask the owner first; this prepares the issue for them to approve.
argument-hint: "[what went wrong]"
---

Report a problem with Kranto itself: $ARGUMENTS

Ask the owner first ("This looks like a bug in Kranto: shall I prepare an issue for it?").
Prepare nothing until they say yes.

1. **Gather the evidence with Kranto's tools, not files.** `kranto_status` for the version
   (`kranto status` on the command line says it too). For an action that failed, `kranto_outcomes`
   with the build's key, the idea's id or its title: what was done, by whom, when, and the
   refusal's words. For a warning Kranto shows (a refused key, a stopped run), `kranto_incidents`. Add `kranto_get_build` or `kranto_read` for the state around it.
2. **Find the smallest repro**: the page, the button, what it said, what you expected. If you
   re-ran a check by hand, say how and what it showed. Never read or quote a secret, a token
   or the owner's private data.
3. **Write it in plain words**: a title of one line ("Publish anyway is refused after an
   upgrade that changed a check"), then *What happened*, *What should happen*, *How to see it*
   (numbered steps), *Evidence* (the version, the outcome's words, the facts you checked),
   and what you think the cause is, marked as your guess.
4. **Prepare it** with `kranto_factory_issue`: `issue` (the title), `text` (the body),
   `labels` (`["bug"]`, or `["feature"]` or `["docs"]`), `area` (`pipeline`, `harness`,
   `auth`, `budget`, `loop`, `stage`, `watcher`, `term`, `ui` or `check`) and, for a problem
   with the watcher half (topics, sources, News, cubs), `repo: "watcher"`. Leave
   `fingerprint` out: Kranto makes it from the area and the title, and an open issue with the
   same one gets a "seen again" comment instead of a twin.
5. **Tell the owner it is prepared, not filed**: it waits in Needs you (`#/needs`) until
   they choose File issue there, which files it on GitHub. If the tool answers that it can't be prepared, say why in
   one sentence and fix the field it names; never call it filed.
