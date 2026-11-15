# Kranto: the longer explanations

The app explains itself in its titles, its rows and the `?` beside a label. What takes more
than a sentence or two, and is read once, is here. Every `?` that links here lands on its
paragraph.

## Signing in and who may act {#access}

Who may act on Kranto, and as whom. The history, the action log and each round say which of
these did it.

Every click, MCP tool and agent request carries a token. Kranto acts as that token's owner
whatever the request claims, and a request without one is refused.

This browser signs in once with the link `kranto open` prints on the machine Kranto runs on (it
expires in 10 minutes); its code also works in the sign-in box at the top of the list.
Fetching the page itself hands out nothing. Agents never use the sign-in box: each sends its
own token (`kranto token add agent:<name>`, or Settings › Privacy & access › Add an agent).

It is not a wall between programs you run as yourself: any of them can read the token files,
or run `kranto open`. It keeps each door's limits, says truthfully who did what, and keeps
other websites and other users out. A console session's sandbox never sees the tokens.

## The model key {#keys-model}

Judging items, the scout and idea cards go through one provider: the Claude API, OpenRouter,
another OpenAI-compatible endpoint, or Claude Code's login (billed to your Claude plan; chosen
only on purpose, after its terms). A key is tested with one request that runs no model, then
kept in the workspace's `.env`, readable by you only. It never appears in a page, a log or your
settings.

## Setting up {#welcome}

Welcome has three steps and one screen after them. **Which model reads for you?** offers the
ways in as boxes: **A model key** (Paste a key opens the form; the key is tested before it is kept,
and the test is free) and **Your Claude Code login** (one click, with Anthropic's terms sentence
beside it; it uses your Claude plan). **First topic**: a name and one sentence, then **Find places
to read**; while it looks (about two minutes) the page says what it is doing, and a topic's first
watch ticks at most the five places that fit best (the rest stay proposed on its page).
**Ready**: when the first brief comes, what it costs (a key's dollars, or the plan's usage on the
login), whether Claude Code is ready for the console (it asks once whether to trust its folder; that
answer is always yours) and usage reports (off until you turn them on; What they hold
shows the choices). **Start reading** starts the first read and opens **How you write**: paste a
few things you wrote and set four switches (how long, how formal, opinions, emoji), or Skip for
now. Either way the home shows the first hour. The console stays on its rail until setup is done.

## The judge's gate {#models-gate}

The gate is the signal an item needs to be kept (`ingest.signal_threshold`). Judges rate on
their own scales: on 160 live items (2026-10-08) Haiku 5.5's signals were about a quarter of
Haiku 4.5's, and a gate of 0.03 matched 4.5's keeps at 0.20 best (86% of items, against 4.5's
own 90% from one run to the next). So the gate is saved with the judge's model: change the
two together.

## Accounts {#connections}

The logins some sources are read with are on **Settings › Watching** (Logins for sources); the
accounts a draft is sent with are on **Settings › Posting**. An old link to Settings › Accounts
lands on Posting. Only read-only scopes are ever asked for a source's login; nothing is posted,
starred, followed or changed. Tokens stay encrypted on this machine and never appear in the
pages, the logs or an export.

The exceptions are the accounts a draft is sent with, all optional (every draft can be copied
without one), and each sends only when you approve the draft (**Send now** in its dialog), never
while it is in practice. **Newsletter** (Settings › Posting › Newsletter): **Connect a provider** offers each newsletter platform Kranto knows; you paste its
key there, and Save and test only reads and says what is missing (a domain to verify, an
audience to choose). A newsletter cub never names a platform: its issues go out through the one
you connected, and its draft waits in Kranto until you connect one. **Check again** reads again;
**Create the audience** makes one at a platform that has audiences, after a confirm. Kranto's
newsletter guide (docs/newsletter.md) has every platform's steps. **Sanity** (Settings ›
Posting › Sanity): paste the project id, the dataset and a robot token (an Editor token named
`kranto-drafts`); Save and test only reads. A cub's **Send to Sanity**
files a post there as a draft and never publishes it: you read it and publish in Studio (the
examplecom cub's guide, in octo-owner/bearcubs). A form's **Markdown** box keeps your lines as you typed them.

## Watch: a topic first {#watch}

**Watch** opens on your topics. Its words across the top are **Topics**, then the topic you are
on with its own **Sources**, **Evidence** and **Map** ("Topics · Robotics › Sources Evidence Map"):
click a topic under Topics and those three are that topic's. Each has its address:
`#/watch/topic/13` is the topic, `#/watch/topic/13/sources`, `/evidence` and `/map` its pages,
titled "Robotics › Sources" and so on. The crumb says "Watch › Robotics › Sources"; **Robotics ▾**
there switches to another topic and keeps the page (Robotics › Map becomes AI developer tooling ›
Map), or to **All topics**, every topic at once: `#/watch/sources`, `/evidence` and `/map`, titled
"All topics › Sources" (Sources keeps its row of topic chips there). Watch comes back to the last
topic you looked at (this browser remembers it; with none yet, the first topic), so Watch in the top bar, `g w` or
the phone's bar of doors lands on it. A topic's Map is its themes, with the map
above them and the other topics' clusters dimmed. Old addresses land on their new place:
`#/topics/13/sources` and `#/watch/sources?topic=13` open Robotics › Sources. In the drawer the
navigator lists your topics under Watch, the one you are on with its Sources, Evidence and Map
under it, then **All topics**; the crumb's switcher is there too. With no topic yet, Watch says
so, with **Add topic**.

## Your topics {#topics}

**Edit** at the top of a topic's page, and under a topic row's ⋯ in Watch › Topics (with Pause
topic and Archive; the ⋯ shows when you point at the row), opens one sheet: its name, its
description, its sources and its own settings. The description is your words for what the topic
is about: every item is compared with it before any model call, and the topic's idea cards and
briefs read it. A rename is seen everywhere at once (the topic keeps its number,
so its cards, briefs and cubs name it anew). Its sources are the topic's own rows, as on
its page: **Remove** takes a source out of this topic only, keeping its evidence (a source left
with no topic is retired, not read, never read for everything); **Add a source from your
library** links one you already have; a new feed, site or account is **Add source**, or **Scout
more**. Each of those is made at once, with **Undo** in its toast. Paused and News's brief (when
News is on) are its switches. **Save** writes what changed of
its words and switches and says so, with one **Undo** for all of it. **Archive** takes the topic off your lists and stops reading it; its evidence, themes and
ideas stay readable, and Undo (or **Restore** under Archived on Watch › Topics) brings it back.
Nothing is deleted: each change is a new row in the server, with where it came from.

**A new topic's first hour.** At the top of a new topic's page, four rows say how far it is, each
with its time: **Sources** (how many are watched), **First read** (when it starts, or how much it
kept), **First brief** and **First ideas**. **Watch these** on a topic never read starts its first
read at once; News is on for a topic you make, and its first brief is written as soon as that read
ends, whatever the hour (about ten minutes after). The first idea cards come after the map, once
30 items are kept across your topics; the row says how many are kept so far, or the next map's
time. The times are Kranto's own next runs, never a promise. When the first read kept little, a line
under the rows says so: a quiet topic takes longer, and more sources or a wider sentence bring
ideas sooner. The four rows leave the page once the topic has its first idea card.

## A topic's sources {#topic-sources}

A topic's page opens with **Sources**: the scout's proposals for it first (Approve, or ✕ to dismiss),
then the five watched sources that keep the most, and **All N ›**, which opens **<topic> ›
Sources** (`#/watch/topic/<id>/sources`). The number in its Facts ("Sources 19 · watched") is the same link. That page says the
topic's own numbers in one line (watched, items a day and what share is kept, the tokens judging
it cost this month, wildcards, proposals, those that could not be fetched), then its rows:
**Proposed**, **Watched** (read every run for this topic), **Wildcards** (unrelated to it, read
with no topic for the patterns they may share) and the rest, each group's meaning beside its
heading. **All topics › Sources** has a row of chips: **All**, each of your topics with what it
watches (its chip opens that topic's Sources) and **No topic** (watched for
no topic: every item is judged). One source can feed several topics: its row says so ("also
feeds LLM tooling and 2 more" on a topic's rows; its topics on All topics › Sources), and its sheet's kind line counts them ("· 4 topics"), with
**Topics** as its first section: each topic it feeds, with that topic's watched sources and kept
items this month, and **Add to another topic**.

**The groups**, on All topics › Sources and a topic's Sources: **Proposed** (found by the scout; nothing
is watched until you approve it), **Watched** (read every run), **Wildcards**, **No topic** (every
item is judged), **Retired**, **Could not be fetched** (proposed, but empty or unreachable when
checked) and **Imported labels** (names on observations imported from Parallax; never read). A
source's sheet says the **Tokens this month** judging its items cost, as a topic's page does for
the topic. ⌘K finds **<topic> › Sources** (and its Evidence and Map) by the word, and **Watch ›
All topics › Sources**.

**Why is this item here?** An observation's sheet names the topics its source feeds ("feeds
Robotics (its only topic)") and, under **Why here**, that it is in a topic's evidence because its
source feeds it, with the similarity it was judged at.

**Add source to a topic.** From a topic (its page, its Sources, its Edit sheet), Add source
opens **Add source to <topic>**: pick a kind, give it an address or a search, Preview, then
Add; the kind's form has the topic set, and **All sources of <topic>** is the way back. A kind
read with your account says who it reads as, or "connect it first under Settings › Watching".

**Proposals.** What the scout proposes says the topic it is for ("for Robotics"; a
wildcard says it is unrelated and may carry the topic's patterns) and waits under **Proposed**.
Needs you has a row per topic of yours with proposals, and one row for all your project topics'
("15 proposed sources for 7 project topics · Review"); the Sources count in Watch's subnav is
the topic's proposals, or every topic's on All topics.

**Stop it for this topic, or everywhere.** On a topic's rows, a watched source's **⋯** starts
with **Remove from <topic>**: this topic only, its evidence kept; the toast says what it still
feeds ("It still feeds AI developer tooling and 2 more"), with **Undo**. When it is the source's
only topic, the menu says so: Kranto stops reading it, as Retire. **Mute for 7 days**, **Read
less** and **Retire** act on every topic the source feeds and say "everywhere: all 4 topics" when
there is more than one. None asks to confirm: each has Undo (Retire's is **Watch again**).

## Rollups {#rollups}

Compacted weeks: past their retention age, each week's observations are clustered and kept as
rollups with a name, a summary, keywords, a source mix and up to five links.

## What a grade does {#grading}

**Where you grade.** ▲ (useful) and ▼ (not useful) are on idea cards and on evidence: at the end
of their rows (on hover) and under the title of a
card's or an observation's sheet ("Your grade ▲ ▼ · why ▾"). A second click on the same glyph
clears it. After a grade, `why ▾` (or the keys a to f) says why; the why is words for you and
the cards to come, never part of the arithmetic. Themes, messages, sources and News items have
no grade: a theme has **Card it now**, and a source is judged by what you graded of its posts. Keys: 1 ▲, 2 ▼, 0 clears. Review (`#/review`) is this
week's ungraded cards, keys only, about five minutes a week.

**What a ▲ does.** The cards that resemble the one you graded rank higher on every list (Ideas,
a topic's cards, the home). "Resemble" is
read from what Kranto already keeps: the same evidence, the same theme, evidence that reads alike
(the stored embeddings), the same topic when there is nothing else to compare. The card you
graded stays at the top. A grade on a piece of evidence counts half as much as one on a card.

**What a ▼ does.** The cards that resemble it rank lower, the card you graded goes to the
bottom. The next ideas run also orders its themes the same way
and skips one your downvotes sank far enough ("not carded: like 2 cards you downvoted"), until
those grades fade or are outweighed.

**Why a card ranks where it does.** A card moved by your grades says so in one line on its row
("ranked up: like 2 cards you upvoted"), and its sheet's *Why this* names them ("like #111 … and
#112, which you upvoted on 11 Oct"). Nothing a model writes decides any of it: the same grades
give the same order, and a grade counts half after 90 days. The numbers are settings under
`grading:` in kranto.yaml.

**When a source is offered for removal.** When 3 or more of one source's posts were graded ▼ in
90 days, and at most a quarter as many ▲, Needs you asks under Decide: "Remove HN search:
local-first? · 4 of its 5 graded posts were not useful in 90 days". **Remove** stops watching it
after a confirm (its observations stay; Watch again on its page undoes it). **Keep** puts the
row away, and only downvotes given after it count toward asking again. Kranto never removes or
mutes a source by itself. Read less stays one of Mute's choices on the source's sheet.

**Your grades.** Settings › System › Your grades (`#/settings/grades`) says what your grades
changed: how many you gave, the cards that moved and why, the themes of the next ideas run in
their order (and any it skips), and the sources recommended for removal or kept.

**A card's topic, and what cites what.** A card's topic is written with the card: the topic of
yours whose sources most of its evidence came from. An observation's **Cited by** lists every card and News brief that rests on it,
also after the observation itself was compacted.

**Write a post.** An idea card's sheet has **Write a post** first (then Pass,
Later and Details), and so has each item of a brief (the item's own page, where it is the one
primary, and each item on the brief's page). It asks once: "Write a post about this idea?", what
it is about (the card or the item, with its sources linked), as what (a blog post, or for a card
a short post for Mastodon), and that the draft waits on Post and nothing is sent until you choose
Send. **Write draft** answers at once ("Writing the draft. It will be on Post in about a minute.")
and the post is written in the background: one model call, in your site's name and tone
(Settings › Posting), with the card's or the item's own sources linked under it by Kranto, never
by the model. The blog writer is Kranto's own: it is added the first time you ask for a blog post.
When the draft is on Post the page says so; when none could be written (the model did not
answer, say, on an install with no model key) a red line says why and what to check.
The console does the same with `post.write`.

**A draft waits until it is seen.** A draft's ask has no time limit. It leaves the drafts that
wait only when it is sent, declined, or replaced by the next draft of its series (next Monday's
issue replaces this one), and then it is under **Earlier drafts**, where it can still be opened.
A draft's sheet has **Copy** (its markdown on your clipboard) and **Download** (`<title>.md`):
neither needs an account. With an account connected, **Send** is the sheet's primary and opens
the same dialog as Needs you's row; with none, **Copy** is, beside "Connect an account to send".
A source the writer named by a label ("obs 12825") reads as its outlet's name.

**Edit** turns a waiting draft into an editor in place: the title, the words (a long post is one
box of markdown; a short post is a box with its count, red past the site's limit), and under them
what reads like AI, underlined with its plain fix, with **Fix them** (it rewrites only those
words; nothing is kept until you choose Save). **Save** keeps your words as the draft that waits
(it is "edited by you"); the original stays under Earlier drafts, and "Start again from the
original" brings its words back. A send that was waiting for your yes is withdrawn first, and the
page says so. Write a post's question has one optional line, "What do you think?" (and, while How you write is not set up, a "Set up how you write" link): the post builds
on it and speaks for you only from it.

**Settings › Posting › How you write** is your voice card (how you write, in plain words; Draft it
from my samples writes one for you to read), four switches (how long, how formal, opinions,
emoji), "What do you think?" on or off, and your samples. Under Advanced: the other switches, the
checker's strictness and rules, your never, keep and always lists, the guides each site follows,
and a disclosure line for each site. Save keeps what you changed.

**Needs you** shows in the top bar as "Needs you 4" while something waits (a dot on the
wordmark on a phone), the same number as Needs you's own head. What a button in a sheet did is said in
that sheet.

## News: pages you read {#news}

**News › Today** is today's edition, one group a topic. Its head says how much there is ("5
stories in Robotics · about a minute"). Each story is one line: its number, headline and first
outlet, and "full story · 2 min" when it has one; older background folds under "2 from earlier".
One story is open at a time (the first when the page opens): what happened, **Why it matters**,
its outlets and days, its idea when it has one, and three plain buttons: **Read the story** (or
**Write the full story**, which asks first: about 10 cents), **Write a post**, and **Idea from
this**. Click another line, or use the keys `j` and `k`, to open another; the address keeps the open one
(`#/news?s=<brief>.<n>`).

**A story's page** (`#/news/i/<brief>/<n>`; an article's old address `#/news/a/<id>` lands here) is
the story whole: its summary, Why it matters (with the idea the full story found in it, and the
story's idea or Idea from this), the full story when there is one (What happened and its numbers,
the rest under "Read on"), its sources (four shown, then all of them, "in your library ›" opening
your own record of a line), and Next. **A story's idea** is chosen by rule, never by a model: a
card made from the story, else a card citing one of its lines, else a card of the theme its lines
sit in on the latest map. **Idea from this** writes one card on that theme (about 6 cents, it asks
first); a story that is on no theme yet says why ("after tonight's map"). A card's page says
which story is "In the news" for it.

**News › Earlier** is one row a day: the day, its lead headline, "full story" when it has one, and
how many stories; a row opens that day in Today's layout (`#/news/b/<id>`), with when it was
written, the search, the model and what the checks dropped under Details. **News › Topics** is
a row a topic with News's switch; click the row for how often and at what hour, and Brief now.
Every topic's defaults are on Settings › News (the gear at the top of News). News is on for a topic
you make (topics made before this release keep what they had). A new topic's first brief is
written as soon as its first read has kept 8 items, while the read goes on, and once more over the
whole read when it ends (that one takes its place on News: "From the first read. Tomorrow's
covers a day."). Until then News › Today says how far the read is ("reading for the first time, 9
kept of 41").

**Full stories.** After each brief, the story with the most behind it earns a full story: on News
› Today its line says "full story · 3 min", and its page shows it. A full story reads the pages behind the item's observations, the library's
earlier lines on the story, the week's briefs and two live searches, and every paragraph, figure,
date and name in it is checked against those lines before you see it. It has a headline, a
standfirst, a figure the page draws from the article's own data (the story's timeline, the
numbers, a monthly series or who is involved; never a picture a model made), What happened, Why
it matters here, What came before, Who is involved, What to watch next, Related, and its Sources,
each with where it is from and when. When the source page offers a picture, the article shows it
small, credited to the outlet and linked to the original: it is the outlet's, loaded from the
outlet by your browser, and it never goes into anything Kranto publishes (Settings › News,
Pictures from sources, turns it off). An item without an article says why on its page; **Deep
dive now** writes one for it (it asks first: it reads the pages and calls the model once, about
10 cents on the reason model). An article has no grade of its own (grade the evidence it rests
on); Write a post on the item's page writes a post about the item the article deepens. **News › Earlier** lists the articles,
then the briefs. How many
articles a day, how deep they read and which sources count are on Settings › News.

## The home and cubs {#home}

The home is the first screen, in one order that does not change: the date and one sentence
("Today's brief is ready, and one draft waits for you."), the one thing (below), today's brief
(each topic with a brief today, three at most, its first three items and **Read the brief**), the
five newest idea cards with ▲ ▼ and how many are new since your last visit, and one quiet line
(how many topics and sources, when Kranto last read, what comes next, and Activity). A part with
nothing to say is left out. Until a new topic's first brief, the home shows **The first hour**
instead: the read as it goes, the topic's four rows (Sources, First read, First brief, First
ideas) and that you can close the page; the status bar says "Reading for the first time". Needs you holds everything else that waits (the one thing opens it,
and so does ⌘K). `g h` is the home; `kranto` at the top left goes there from any page.

**The doors** are News, Ideas, Watch and Post, in the top bar on every page and, on a phone, in
the bar at the bottom with ✦ for the console. Post is where the drafts your posting cubs write
wait for you; Settings is ⚙.

**While you were away.** If you have not opened the home for three days or more (`home.away_days`
in `kranto.yaml`), the brief and the cards give way to one list of five: the three best cards
written while you were gone (in Ideas' own order, which your grades steer) and the first item of
the two newest briefs; with fewer briefs, more cards. The sentence says how long you were away and
what Kranto wrote, and **Everything since …** under the list opens Ideas. It stays until you open
one of the five or choose **Show today** (a reload before that shows it again); only then does
Kranto count your visit. It is chosen by a rule from what is stored, never by a model.

A cub is anything else Kranto does and anything someone else writes later: Kranto draws its rows
and its page from what it declares, and its page says who made it and its mode (practice or
live). A feature or cub that is off has no row, no account under Settings › Accounts and nothing the console can run; turned on, it
is back where it was.
Adding a cub (Available, Made by Kranto, Add a cub) is a developer's: Cubs shows your installed
cubs and what they ask you unless `cubs.developer: true` is in Kranto's config. A cub never
posts or sends by itself: it asks you. Needs you shows what it asks as one line ("This
week: Eka Robotics… · ready") with the action's own button (**Send**, **Post toot**, **Send to
Sanity**), and the button opens one plain dialog: what it is, whom it goes to, the text drawn and
collapsed with Show all, and **Send now** (or **Schedule**, where the platform can) and Cancel.
What stops it is fixed there: with no account connected the main button connects one in place
and comes back; in **practice** (every cub starts there: an approval sends nothing, and the
dialog says "Nothing was sent (practice)") the dialog has the cub's own **Send for real** switch,
which applies to its later ones too. **Details** has the rest: the draft, when it was asked and
the run that made it, what it rests on (the idea card or the brief is a link), its history, and
Decline. An ask waits until you answer it (it has no time limit), so "Open until" in Details
says so. An ask that was practiced, refused or (before Kranto 0.6) ran out of time, when its draft
is still the newest, stays on its row: its button asks again with the same draft (no new run).
A draft that ran out of time before Kranto 0.6, never approved or declined, waits again by itself.
The card's own Details list what cubs asked on it under Asked of you; Post lists every cub's.
Other people's cubs run from 0.5. When a cub asks which of your topics it should read
(the newsletter does), its Settings page shows your topics to switch on, never a box for ids;
none switched on means every topic.

**The one thing.** Needs you and the home open with one item drawn large, the only bold button on
the screen: the newest thing waiting to go out (an assistant's prepared item, a draft a cub asks
to send), else the oldest thing to fix, else the first to decide. It is chosen by a
rule, never by a model, and Kranto's own trouble (a refused key) is the red band above it instead.
Every other row is one line: its state in a word, its title, at most one fact, its age and one
plain button; the rest is on its page. Needs you shows at most seven things before you scroll
(five on a phone): a long group shows its first rows and **Show all**, a group past them starts
folded to its name and count, and Decide starts folded. Open a group with its ▸ and it stays
open in this browser. Lists say one line a row too: **Ideas** shows Waiting's first fourteen and
**Show all**, with Later, Posted and Passed folded; **Sources** shows Proposed first (Approve, or
✕ to dismiss, with Undo in the toast), the other groups folded; a row's numbers (items a day,
kept, yield) are its sheet's. The idea cards waiting are one row ("6 idea cards wait for Later or Pass");
**Open** takes you to Ideas, where Later and Pass are.

**Details.** What a row, the one thing or a dialog leaves out (its ids and versions, the rules it
meets, its evidence, its run and its history) is one click away: **Details** at the foot of a
decision dialog, beside the one thing's button, and under a cub's ask's Details as **The full
record**. It opens a drawer at the right with the whole record; **Esc** or ✕ closes it. Its last
line names the console's call for the same record (`kranto_details card:<n>`), so the console
and the drawer never disagree.

The home is no longer arranged: its tiles, widgets and Arrange are gone, and a home you arranged
in an earlier release opens in the order above (what you arranged stays in your settings file,
unread).

Once a day Kranto looks for each cub's new version. One that adds no permission and no send, and
runs on your Kranto, is applied by itself: the cub's page says "Updated to 1.2.1 by itself" and
Activity has the run. Any other waits for one click: Needs you says "Newsletter 1.2.0 asks for one
more permission · Review", its page's ⋯ says "Update to 1.2.0" and Home › Cubs lists it under
Staged with what it may now do; one click opens the change and its new permissions, and Update
applies it. Look for an update under About on its Settings page (or `kranto cub update ID` in a
terminal) looks now. `cubs.auto_update: false` in `kranto.yaml` makes every update wait for your approval.

## Post {#post}

Post (`#/post`, the fourth door) is where what Kranto writes for you waits: **Drafts waiting**,
one line a draft (newsletter, blog post or short posts; its title; one fact, like "Monday's
issue"; for short posts the sites as words, "Bluesky ✓ · Mastodon · X", ✓ on those posted; its
age; **Open**); **Sent**, one line a post with where it went; **Where posts go**, one line with
**Sites** (Settings › Posting); and **Earlier drafts**, folded (an issue a newer one replaced, one
you declined), each still openable. A draft waits until you have seen it: it leaves Drafts waiting
only when it is sent, declined, or replaced by the next one of its series. **Open** shows the
draft with Send (the same dialog as anywhere), Copy, Download and Decline; nothing is sent until
you choose Send. **Write a post** in the head asks about what: this week's news (Write draft then
writes it, and it waits here), or an idea (Ideas opens; a card's own Write a post writes about
it). ⚙ is Settings › Posting. Old links to Cubs and its Approvals land here.

**Write a post** asks one thing: "Why does this interest you? One sentence." Beside the box are
three proposals (a claim, a prediction, a question); pick one, change it, or write your own, and
the post opens on it. **Skip** writes without one: the draft then only says what the sources say.
**As** is **Blog post** or **Short posts** for the sites you ticked in Settings › Posting.

**Short posts** go to the sites people use, in one of two ways only. **Open in Bluesky** (or X,
Threads, Mastodon) opens the site's own box with the post written; you post it there yourself, and back
here **I posted it** moves it to Sent as "posted by you" (Kranto sends nothing). Where you switched
a site to **Post directly** (Bluesky, Mastodon and Threads, with their posting account
connected), **Post to Bluesky** sits beside Open and posts it after your yes in the confirm
dialog. Open always comes first. LinkedIn has no Open, so it is offered only as Post directly,
with your own LinkedIn app's token. Your own site comes first too: with your blog connected, Write a post writes the blog post,
and each short post is written from its words and links to it; with no blog, a short post links to
the card's source. Each site's version is written for that site (Bluesky's 300 characters, X's 280
with the link counted as 23), and each says how much of its limit it uses. Copy gives you the
words on any draft. On the preview Open is off and says nothing is posted.

## Settings {#settings}

Settings has seven pages, in the order you set kranto up: **Watching** (the model key and
provider, the model for each job, how often kranto reads, live search, and the logins some
sources are read with), **Posting** (the sites you post short posts to, one line each, with
**Post directly** where Kranto can post after your yes; **Add a site**, where Substack is listed
under "Not possible today" with why; your blog; the newsletter; how you
write), **Assistant**,
**Spend**, **Privacy**, **System** (updates, the service, recent runs, your grades) and
**Appearance**. **Advanced**, folded, has Prompts (every prompt Kranto sends a model, with your
additions or your own full text) and what your settings file switches on by hand (the cub shop).
Every old address lands on its new page: a bookmark to Settings › Accounts lands on Posting, Keys
and Models on Watching, Updates and Health on System, Access on Privacy; the address of a page
that left lands on the Overview.

## A cub's page {#cub-page}

A cub's page looks like the rest of Kranto: Home › Cubs › its name, its glyph, who made it and its
mode, one line of facts, what it is for, what of it runs now, one line when it is not live (and
where to change that), then its lists and Log as the words across the top. Its one blue button is
its main verb (Compose, Draft a post); Stop sits beside it for one that runs; every
other verb is under ⋯ (Update to… when one waits), and ⚙ opens its
Settings page. A row opens in the one sheet, with `j` and
`k`; something you read before you act on it, a newsletter issue or a post, opens as a page of its
own with Confirm at its top. A list with
nothing in it says what will appear and when, in the cub's own words.

## Settings for what Kranto writes and posts {#feature-settings}

What Kranto writes and posts each has its own page: Settings › News, Settings › Newsletter and so
on, at `#/settings/<id>`. Its gear (⚙) in the head opens it, Settings' Overview lists them all
under Features (one added later is there by itself), and ⌘K finds "settings news" and every key by
its words. Each page is drawn the same way: **On and off** (its switch; for a posting job, each
kind of post Practice or For real, and Stop), its settings in their groups, **Advanced** folded
(and the keys written by hand in your settings file, shown, not changed here), for a posting job
what it may add to Needs you and its caps, the **accounts it uses**, its **spend**, and **About**
(what it may do, in words; Look for an update; Remove). A switch changes in one click with Undo;
any other key opens its form in the sheet with Save, Undo and Back to the default. A page says
when its change takes effect.

## What Kranto is doing {#activity}

Everything Kranto does in the background is a run: reading your sources, drawing the map, a
brief, a cub's weekly post, the update check, and every action that does work (Brief now, the
scout, Run ingest now). The top bar says it in one item, in a
word, in both layouts and on the phone (point at it for the rest): "Quiet" with a green dot when
nothing runs (its tooltip: "next: reading your sources at 20:23"); a spinning ring and the count
while something runs ("2 running"; the tooltip names the first); "Paused" while you have paused
everything; a red dot and "1 failed" until you open Activity. While something is still broken it
stays red whatever runs and however often you look: "OpenRouter key refused · reading your
sources stopped" while a model key is refused, "1 failing · reading your sources" while a kind
fails run after run. Click it, or `g a`, or ⌘K "What is Kranto doing?".

**Activity** (`#/activity`) has four groups. Running now:
each run's stage, how long it has run, what it has spent, who started it, **Watch ›** (its trace,
following the step in hand) and **Stop**. Waiting on you: a run that stopped for you, with the one
verb that opens where you answer. Next: each
scheduled run that is on, soonest first, how often, its last run; one that is failing says so in
red. Recent: the last day's runs, done, failed with the reason, skipped with why; the hourly
re-checks that found nothing to do and the usage reports are one line a kind (Show every row).

**Stop** ends a run at its next step, never in the middle of one: reading your sources stops after
the source in hand (what it kept stays; the rest at the next read), a cub's job at its next call
to Kranto. A toast offers Undo for 9
seconds before it asks. A stopped run is due again at its next hourly check, never lost.

**Failures are said once.** A failed run shows in Recent at once, and runs of one kind that
failed the same way are one row there ("4 runs of Reading your sources failed"). A kind that
fails twice in a row, or has been failing for two days, is one row in Needs you › Fix ("The
update check is failing", its one fact "GitHub answered 401"), its verb on Activity (Run again,
Try again) with ⋯ › Dismiss, which puts it away until it fails again, and ⋯ › Send this error;
its title opens what happened. The row goes by itself at its next good run.
Fix is the first group of Needs you, and its rows lead the home's.

**A refused key stops everything, so it is said first.** When your model provider refuses the key
(it expired, it is wrong, it ran out of credit), every run that calls a model fails at once:
reading your sources, idea cards, a cub's model calls. Kranto says it once, from the first failure:
as a red band above everything on the home and on Needs you (in both layouts and on the phone,
above the console's sheet), and never again as a row of Needs you: "Your OpenRouter key was
refused (expired) at 08:15 on 25 Oct. Stopped until it is renewed in Settings › Watching: reading
your sources and idea cards", with **Renew the key** (Settings › Watching › Watching model) and
**Dismiss**. The kinds it stops have no Fix rows of their own, the Watch door says "reading is
failing since 25 Oct", and the runs' "run failed" messages fold into it. It goes by itself as soon
as a later call to the same provider works (whatever run made it) or the key test in Settings ›
Watching passes; Dismiss puts it away until it happens again. `kranto status` says it on its first
line.

**"Preview: a copy of your data from … Nothing is posted; no update or usage report goes out."**
On the preview (a second Kranto built from a branch, on a copy of your data, `kranto-preview` in
the server's `docs/preview.md`) this is the status bar's first cell, and on the phone a strip above
the doors. There nothing is posted: an approval says "This is the preview: nothing is sent", no
kind can be turned live, no report or update goes out, and Check for updates says updates are off.
A model key's test still asks its provider (that is how a key is checked). Every other install
never shows it.

**Healthy, Degraded or Paused, and why.** The status bar's first word (and the home's line, in
both layouts and on the phone) is Kranto's health. When it is not Healthy, the words after it say
why in one line, and a click opens that run's trace: "The last read of your sources failed at 12:42: a safety
filter at OpenRouter declined one item", "The last read of your sources at 06:35 had problems: OpenRouter
sent 1 empty reply (read again next run)", "3 of 12 judge calls failed in the last 24 hours: …",
"Watching is paused". One empty reply never fails a run: it
is tried again like any hiccup, and if it is still empty the item waits for the next run and the
run is "done with problems". An item a safety filter declines is set aside and not sent again. The
console answers "why is Kranto degraded?" from the same words (`kranto_incidents`).

**Low credit is not a refused key.** When the provider only asks Kranto to wait (OpenRouter's
"would exceed your available credits given your current in-flight requests"), the key works: the
call is tried again, and if it still waits the band is amber, "OpenRouter credit is low: calls
wait and try again", and goes at the next call that works. A key with no credit left at all is
"out of credit" and stops until credit is added.

**The band is for Kranto itself.** Only what stops Kranto's own work raises it: a refused model key,
and Kranto's core (the service, the scheduler, the database). No feature or cub can: their blocked
states (a sign-in expired, a cub stopped) are one Needs you row each, first in Fix, with the button that fixes it, and the line on the cub's tile;
they do not turn the top bar red. `kranto status` says the same: Kranto's own on an `INCIDENT` line, a
feature's on a `NEEDS YOU` line. Any of them can be dismissed.

Each page also says its own: a topic's page its sources
being read, a cub's page its job running or failed, Settings › System › Updates the check.
The home's quiet line says when Kranto last read and what comes next, with Activity at its end. A run's trace (Watch ›, Trace ›) heads with the run in one line ("Reading your sources · source 2
of 8 · 3 model calls · $0.02") and grows while it runs. The runs' marks are kept 30 days, at most
20,000 (Settings › System › Activity changes both; the foot of Activity says them); the runs
themselves are kept as before.

## The layout {#layout}

One layout: the home and its doors, News, Ideas, Watch and Post, in the top bar on every page.
Each door is one column with its words across the top (Watch: Topics, then the topic's Sources ·
Evidence · Map), every object opens in a sheet over the page, and a phone has the doors in a bar
at its foot, with ✦ for the console.

Every page starts the same way: "Home › the door" above, its glyph and name (the door's, when the
page is one of the door's words), one line of facts, at most one blue button with ⋯ (the other
verbs) and ⚙ (the door's settings) beside it, the line of what runs for it, then its words
underlined.

A button says what it does, with no "…" after it: one that asks before it acts (Confirm,
Publish, Remove) opens its question first, and nothing happens until you answer. Something you
read (a brief, a news item, an issue) opens as a page; something you act on (an idea, a
source) opens in the sheet, with Open in full where it has a page too.

Until now there was a second layout, Classic (the navigator on the left). It is gone: a settings
file that says `shell: {layout: classic}` opens in this one, and Kranto keeps what the file says
rather than rewriting it. Until 0.5.8 two switches said it, `shell.home` and `shell.doors`; Kranto
still reads them, and draws this layout either way.

## Updates {#updates}

Kranto checks GitHub once a day. An update backs up, installs, restarts and checks itself, and
rolls back on its own if the new version does not come up.

**Stable or nightly.** You choose your line under Settings › System › Updates › Channel. New
installs are on **stable**: releases the maintainer made stable once the work in them was done,
and fixes as soon as they are checked. Stable is always a choice the maintainer makes, never a
matter of time. **Nightly** is a new version from main, several a day: new features arrive there
first, a version may break (one whose pages fail on your data rolls itself back), and you click
to update, since a nightly never installs by itself. A feature that is not finished can
reach stable switched off: its setting's stable default keeps the old behaviour until the
maintainer turns it on in a later stable release, whose notes say so. Moving from nightly to
stable never downgrades: you stay on your version (`kranto status` says "moving to stable at the
next promotion") until a newer stable is released. `main` follows every merge from git and
suits a development machine. The old `rc` channel reads as nightly.

**Promote to stable** (the maintainer's install only, `update.maintainer: true` in
`kranto.yaml`). Whenever nightly is ahead of stable, Needs you has one row: "Nightly 0.6.0-dev3
can become stable 0.6.0", with what is in it (the pull requests since the last stable, the big
changes named, each setting that stays off on stable) and the health checks. A rollback of the
version, a new error that still occurs, or a page failing on your data or on the odd installs
blocks the action, and the row says which. A check that could not be read is said in the row
(for example when the error reports cannot be read yet) and does not block. Time on nightly is shown as information
only; nothing is promoted because time passed. The action opens a confirm that reads back what
it carries; Promote starts the release gate on this machine, which cuts the stable release from
that version, checks it (install, update, roll back, every page) and releases it, about an hour;
the row says each step, and if one fails the release stays held and the row says where.

To check now, click the version ("Kranto 0.5.10 · Check for updates": in the status bar, on
Settings' Overview, and Check for updates under Settings › System › Updates), or ⌘K "Check for
updates". The answer is said where you clicked: you're on the latest, a new version is ready
(Restart to update, also ⌘K "Update Kranto"), or why the check failed and what to do. While the
repositories are private, a check needs a GitHub login that can see them: run `gh auth login` on
the machine Kranto runs on. When the check has failed for more than two days, the top bar says
"Can't check for updates" (point at it for the reason). An update ready says "Update" there,
without its versions: Settings › Updates says them. The top bar holds nothing else daily: what
runs is on Activity, the tokens used today on Settings › Spend, and Feedback is under ⚙.

Restart to update waits for a running job, backs up both databases and the settings,
installs the new version, restarts and checks it. If the new version does not come up, Kranto
puts the previous one back by itself; the data is never rolled back. If the old version did
not stop when asked and had to be killed, the update's line under Settings › System › Updates says so:
the new version runs, and the warning is worth reporting.

Before it keeps a new version, kranto reads every page it serves once, on your own data: every
topic, every list's first page, the home, each cub's page, the activity (only reads; nothing
is changed). If one fails (an error, or no answer), the new version is put back the same way,
and Needs you says "0.5.x broke on your data and was rolled back", with **Send this error**
(see [When something can't be read](#errors)). From a terminal, `kranto doctor --routes` runs
the same check on the running Kranto.

## Ideas {#ideas}

**Ideas** lists Kranto's idea cards, grouped by where each one is: **Waiting** (in your order: what
you graded ▲ and what reads like it first), **Later** (put off; it comes back by itself on the day
it names), **Posted** (a draft was written about it) and **Passed**. **Pass** on a card asks why
in one chip and grades it not useful: it moves to Passed and its sources learn from it. **Later**
puts it off for a week. Both are kept with the card in Kranto; nothing else changes. A card is
`#/ideas/<number>`, and an old link to one (`card:143`, or the id an earlier release gave a card
it took in) still opens it. With no card yet, Ideas says when the first come: after the map, once
30 items are kept, and how many are kept so far. The console reads the same list in the same
order (`kranto_list_ideas`, `kranto_get_idea`), and Later is the verb `idea.later`.

## Kranto's memory {#memory}

Settings › System › Service › **Memory** is the most memory Kranto's service may use (`service.memory`,
in GB; MemoryHigh is 1 GB under it, where the system starts slowing kranto down). **Auto** takes it
from this machine's memory (half of it, at most 4 GB). Save applies it at once to the running
service, with Undo, and the row shows what Kranto uses now. It is Kranto's own systemd drop-in
(`~/.config/systemd/user/kranto.service.d/30-memory.conf`): change it here, or ask the console,
rather than by hand. A Kranto that is not running as its service (one started in a terminal)
says so and changes nothing.

## The console {#console}

The panel on the right of every page is your own Claude Code (or Codex), as it runs in a
terminal, in Kranto's folder, with Kranto's tools. It is open when Kranto opens (Settings ›
Assistant can say otherwise; on a phone it starts as ✦ in the bar of doors); **›** folds it to
a rail, **–** to one item in the top bar (✦ and its name, beside ⚙), and this browser remembers
which.
Drag its left edge to make it wider or narrower (320 px to 60% of the window); this browser
keeps the width, a double-click on the edge resets it, and with the edge focused the arrow keys
step it (shift for bigger steps, Enter resets). `⌘J` (ctrl J) opens it or puts the keys in it from anywhere;
`ctrl+]` gives them back to the page. Moving between pages never touches it: the same screen,
the same conversation. Reloading the page brings the same screen back; when Kranto restarts, the
conversation resumes. **⋯ › New conversation** starts over (the old one stays in its
`/resume`). **⋯ › End this session** asks once, ends it and starts a fresh session in the same
panel at once, with a clean prompt; the one that ended is kept under **⋯ › Previous sessions**,
which resumes any of them (Claude Code's; Codex resumes only its last). **–** only hides the
panel: nothing ends.

**Three questions to start.** An empty console (no conversation yet, or a new one nobody has
typed in) offers three questions above its prompt, each with a line saying what comes back:
"What is new in Robotics?" (the topic of the page you are on, else the one with the newest
brief), "Which idea should I look at?", and on a card or a brief "Write a post about this"
(elsewhere "Write a post about this week's news"). A click starts the session if none runs, types
the question and sends it; the question names the card or the brief, since the assistant is not
told which page you are on. A post it writes waits on Post as a draft; sending is yours.

**On a phone you can read and approve. Start a conversation on a wider screen.** ✦ in the bar
of doors opens a sheet, not a terminal: **Waiting for your yes** (each item an assistant
prepared, with **Review**, the same dialog as anywhere) and **What it last said** (the first
lines of its newest reply, read from its own transcript, with the page it linked). **Open the
terminal full screen anyway** is there for whoever wants it.

A change to the console's skills (turning a feature on or off brings or takes away its skill)
reaches it at its next start: the plugin's copy is written when it starts. **Restart the console
now** on Settings › Assistant takes it at once.

When an action of yours or of the assistant's did not happen, ask it why: it reads the last
actions on the idea or the source (`kranto_outcomes`), each with the reason it was refused, before
any log. The same reason is in Activity. Asked why Kranto warns about
something (a refused key, low credit, "Degraded"), it reads the warning itself (`kranto_incidents`):
the status bar's word and why, what raised it, when, whether later calls worked and what clears it. When it finds a bug in Kranto
itself, it offers to file it (`/kranto:report-issue`): it prepares the issue, and your approval in
Needs you files it.

The head says who it is and on what: the assistant (Claude Code first, Codex if you pick it;
Codex works with fewer extras: no status line, and its spend is not reported), its model, what
the conversation cost so far, and its permission mode (auto mode by default: it decides edits
and commands itself; Kranto's own tools are Kranto's to decide, by your ladder).

What it does through Kranto's tools shows on the page it changed and in Activity, marked with its
name; what your ladder keeps for you (sending, publishing, archiving) is prepared, and waits for
your approval on its page and in Needs you (on an idea or a source it waits in that one's
sheet, where you can click it). What Kranto refuses it is said to it in words, and Activity keeps
it: "An assistant's action, skipped", with why. Keys, logins and approving what a cub asks are never
its. Kranto's secrets (`data/secrets`, `.env`, the tokens) are refused to it.

**Settings › Assistant** sets what it starts with. Whose configuration and the permission mode
are read when it starts: changing one offers **Restart the console now**, which ends the session
and starts it again with the same conversation (picking the other assistant offers to switch).
With your own configuration, the MCP servers you added load too; ⋯ in the console and the
setting name them. Your own Claude Code or Codex outside Kranto gets the same tools: Settings ›
Assistant › Use Kranto from your own client › **Add Kranto to my own Claude Code…** (or Codex)
shows the exact commands and files first and changes nothing outside Kranto's folder until you
click Add; asked in the console, it prepares the same change for you there. `kranto assistant
global claude|codex` does it from a terminal.

## Open in Claude Code {#claude-code}

`c` on an idea opens the real Claude Code about it, in a panel at the bottom of the pane, as
wide as you drag its left edge. It works in its own empty folder, starts with what Kranto knows
about it, and asks before every edit and command, as it does in a terminal. While the terminal
has the keys, every key is its own; `ctrl+]` gives them back to the page.

It changes nothing of Kranto by itself. Kranto's actions come to you as cards above the terminal,
with the session's reason: **Confirm** runs one as your own approval, **Dismiss** drops it. A
host it was refused comes as a card too: **Allow** opens it for this session only. While the panel is closed,
cards that wait are a row in Needs you; **Open** shows them.

Where `bwrap` works, the session cannot see your GitHub login, SSH keys, Kranto's tokens or data,
or its own Claude token, and reaches only `api.anthropic.com` and the hosts you allowed. Its
cost counts in Settings › Spend under Claude Code, within the daily cap.

Closing the panel leaves it running; one nobody watches that prints nothing for an hour ends,
and Open again resumes the conversation. **End** ends it for good and removes its copy, unless
a card still uses it. **Continue outside** ends it here and shows two commands for your own
terminal: `cd … && claude --resume …` (your own Claude Code and permissions, with Kranto's tools)
and `kranto term open <id>` (the page's limits).

It turns on by itself where Kranto has bubblewrap and a Claude token (`claude setup-token`)
in its environment; `kranto doctor` says whether both are there, and the setup guide has the
steps. `term.enabled` in `loop.yaml` set false turns it off, and `true` turns it on without
bubblewrap (with a warning). While it is off, `c` says how to turn it on.

Which token it logs in with: your Claude login token first, so a session runs on your Claude
plan. Without one, it would bill your Claude API key. The watcher's key, saved under Settings ›
Watching into Kranto's `.env`, is not used until you choose **Use the API key** in the panel
(`term.allow_api_key`, kept in your settings); a key you put in Kranto's unit yourself is used as
before. On an API key, a Find these
with Claude Code session runs on the watcher's reasoning model (or `term.model`), and its button
says so. When the Claude API refuses a session's request (no credit, a rejected key, a usage
limit), the panel and the Add source page say so in red.

It replaced the chat (0.3.70): old chat threads stay on disk, unread.

## Where a change takes effect {#effect}

Every Save says when what you changed is used, in one of these sentences:

- **Applies at once.** The next request or call reads it (a key, a provider, watching's caps).
- **From the next check.** The next update check.
- **From the next run.** The next ingest, map or ideas run.
- **After a restart (kranto down, kranto up).** Read once when Kranto starts: how often sources
  are read, delivery, the home and the port.

## Feedback {#feedback}

**Feedback** (⚙ › Send feedback in the top bar, ⌘K's **Send feedback**, Settings › Overview, **Tell us** on
every red line, and **Send this error** where Kranto says an error's id: see
[When something can't be read](#errors)) sends a bug, an idea or a question to Kranto's GitHub
as an issue, from you:
[Send feedback](./#/?feedback=1).

Pick the kind and write what happened, or what you would like. **Include details** (on) adds,
and shows you before anything is sent: Kranto's version, the layout, the page's route as its
pattern (`#/topics/:id/ideas`, never an id), the browser and the OS family, the last update
check and its error, and the last few errors the page said. Tokens, paths under your home, the
host name, your topics' and ideas' names and anything an error quoted are taken out first.

- **File it** shows up when your own `gh` is installed, logged in and can open issues on the
  repository. It shows the exact title, labels and body, then files the issue as you. Kranto
  sends nothing of its own: no Kranto account, no token of Kranto's, no relay.
- **Open on GitHub** opens GitHub's new-issue page with the title, the body and the labels
  filled in; you click Submit there. The link holds about 6,000 characters, so the oldest
  errors are left out first (the sheet says so).

The draft stays in this browser while the sheet is closed, and is cleared once filed. With no
network the sheet says GitHub can't be reached and keeps the draft. The issues go to
`iddv/kranto`, Kranto's release repository; `feedback.repo` in your settings names another (a
fork's own). There is no screenshot upload: GitHub's page takes a pasted one.

### When something can't be read {#errors}

One thing Kranto cannot read never takes a page down. A row of a list that cannot be read
stays in its list's place as one line under the page's title, **Couldn't read this source**
(or idea, topic, run…), with its name and a short error id; the rest of the page works
as always. When a whole page or read fails, its red line says Kranto's version and the error
id, with **Try again**. Activity's **Failing** rows have the id too.

Each has **Send this error**: Feedback, with the error's report added and shown in full before
anything is sent. The report is Kranto's own: the error id, the kind of error, the lines of
Kranto's code it went through (`module.function:line`, no values), Kranto's version, your OS and
`kranto doctor`'s summary (how many checks passed, and the names of those that did not). It
never carries your data, a path in your home or a token. From a terminal, `kranto report`
writes the same report for the newest error (`kranto report <id>` for another) to one file and
prints where.
