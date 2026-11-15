# Newsletter

Monday's issue from the week's News briefs, for you to read and send through your newsletter
platform.

**What it does.** Every Monday at 08:00 it reads the briefs News wrote in the last seven days
(for the topics you pick under its Settings, Topics, or every topic), takes their items word for word, asks
the model for a two-sentence intro from the headlines only, and makes a draft: in Kranto until a
newsletter platform is connected, at the platform after. Then it waits for your approval:
Needs you shows the issue with **Send**. You can also compose an issue now from the briefs you pick,
and redraft one (the old one is withdrawn).

**What it asks for.** Topics and briefs to read; one model purpose (`newsletter_intro`, the
reason tier, at most $2 a month); the newsletter's draft operations through Kranto, with your
platform's key, which it never sees; the `send.newsletter` approval (at most 3 a day); its own
small store. It never names a platform: Kranto sends through the one you connected.

**What it never does.** Send anything by itself. Every send is your approval, and in practice
(the default) the approval sends nothing and says so. It reads no
file of yours and has no network.

**Sending for real.** Connect a newsletter platform under Settings › Accounts › Newsletter, Connect a
provider (Kranto's newsletter guide has the steps for each), then turn on **Send for real** in the
issue's Send dialog (or on this cub's page). With `newsletter.send_at` set to a time of day (UTC, such as `09:30`), your approval
schedules the issue for that time instead of sending it now, where the platform can schedule;
until then you can cancel it at the platform.

Settings: `newsletter.enabled`, `newsletter.topics`,
`newsletter.max_items`, `newsletter.subject_prefix`, `newsletter.send_at` (now, or `HH:MM` UTC).
The intro is written in your voice through Kranto's prose engine (docs/prose.md); the old
`newsletter.intro` became your voice card's first line.

**From 1.0.0.** 1.0.0 asked for a platform-named kind and service; Kranto that brought these
names still honours those for one release, so nothing stops working, and `kranto cub update newsletter` moves it to
these neutral names (Send keeps its practice or real mode).
