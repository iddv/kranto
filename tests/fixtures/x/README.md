# X reply fixtures

No fixture here came from a real call to X: no X account, app, key or token was used to make
them, and the suite never reaches X (the conftest guard refuses any socket that is not
loopback).

Each `.json` file starts with `//` lines naming the public page whose schema it follows and the
date it was read. X's endpoint pages (docs.x.com, read 2026-10-17) describe each reply as a
schema rather than printing an example body, so the bodies were written by hand to those
schemas: the field names (`post.fields`, `referenced_posts`, `includes.posts`, `note_post`,
`edit_history_post_ids`, `public_metrics.repost_count`) and shapes are X's; the ids, text and
numbers are made up. `token.json` follows OAuth 2.0's token reply with X's two-hour expiry and
placeholder values, and `credits.json` X's problem shape, since X documents no exact body for
a spent balance.

`tests/fake_x.fixture(name)` reads one, skipping the header lines.
