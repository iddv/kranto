# Toot the pick

The weekly editor's pick, as a short Mastodon post you read and approve.

**What it does.** Every day at 09:00 it looks for an idea card the weekly editor nominated
since its last post. For a new one it asks the model for one short caption of the card's title
and one-liner (no hashtags, nothing the card does not say), within your instance's character
limit (500 until Mastodon is connected), keeps the draft in Kranto, and waits for your approval:
Needs you shows the post with **Post toot**, and its Details name the card it came from. A pick Kranto already built is skipped (announcing a product is another post).
You can also draft a post from any card, and redraft one (the old one is withdrawn).

**What it asks for.** Ideas and topics to read; one model purpose (`toot_caption`, the reason
tier, at most $1 a month); Mastodon's draft and read operations through Kranto, with your
posting account's token, which it never sees; the `post.mastodon` approval (at most 5 a day); its
own small store.

**What it never does.** Post anything by itself, name an account, follow, boost or delete.
Every post is your approval, and in practice (the default) the approval posts nothing and
says so.

**Posting for real.** Connect Mastodon (posting) under Settings › Connections (your instance and an
access token with `read:accounts write:statuses` only), then turn on **Send for real** in the post's dialog (or on this cub's page).
Delete a post on your instance if you change your mind.

Settings: `toot.enabled`, `toot.visibility`, `toot.language`,
`toot.link` (off unless your Kranto is reachable from outside). The post is written in your voice
through Kranto's prose engine (docs/prose.md); the old `toot.tone` became your voice card's first
line, and the form's tone (plain or playful) is a hint for that one post.
