# Posting: your own site first, then the sites people use

Kranto writes what you post. Nothing leaves Kranto without your yes: either you post it yourself
in the site's own box, or Kranto posts it after your yes in the confirm dialog. This page is the
reference: which sites, how each is reached, how the posts are written, and what to connect.

## Two ways, and only two

| Way | What happens | Who posts it |
|---|---|---|
| **Open** | Kranto opens the site's own box in your browser with the post written in it. Back in Kranto, **I posted it** moves the draft to Sent as "posted by you". Kranto sends nothing, and makes no request to the site. | You, in the site |
| **Post directly** | Kranto posts the draft with your own posting account, after your yes in the confirm dialog, which shows the account, each post and what goes with it. | You, in Kranto's confirm dialog |

**Open comes first** on every site that has one, even where Kranto could post directly. Posting
directly is the second choice, switched on per site in **Settings › Posting** (off until you do).
A site that has neither is not offered. There is no "copy and open": **Copy** is a plain button on
every draft, for anywhere you like.

## Your own site first

With your blog connected (**Settings › Posting, Sanity**, with your posts' address), **Write a
post › Short posts** writes the blog post first. Each short post is then written **from that post's
own words**, in the site's own form, and **links to the post's address** (your posts' address and
the post's slug, known before you publish it). Its draft page says "Links to your blog post: …. Put
it on your blog before you post this." With no blog connected, a short post is about the card or
the news item and links to its best source.

## The sites

Checked on 13 November 2026 against each site's own documents (the sources below). A site's Open
was not tried with an account: the first real post of each is the owner's, and this table says
"not yet sent for real" until it is.

| Site | Open (the site's box, written for you) | Post directly | Limit, as the site counts | Sent for real |
|---|---|---|---|---|
| **Bluesky** | `https://bsky.app/intent/compose?text=…` | Yes: your handle and an app password (**Bluesky (posting)**) | 300 characters as a reader sees them (an emoji with its skin tone is one) | not yet sent for real |
| **Mastodon** | `https://<your server>/share?text=…` (type your server once in Settings › Posting) | Yes: **Mastodon (posting)** | your server's limit (500 by default), each link counted as 23 | not yet sent for real |
| **X** | `https://x.com/intent/tweet?text=…&url=…` | No: X's API is paid, and Kranto does not use it | 280, the link counted as 23, wide characters as two | not yet sent for real |
| **Threads** | `https://www.threads.com/intent/post?text=…&url=…` | Yes: your own Meta app's token (**Threads (posting)**) | 500 characters, an emoji counted as its bytes | not yet sent for real |
| **LinkedIn** | none: LinkedIn documents no link that fills in a post's text | Yes, and only this way: your own LinkedIn app's token (**LinkedIn (posting)**) | 3,000 characters | not yet sent for real |

**Not possible today** (Settings › Posting lists them with these reasons):

| Site | Why |
|---|---|
| **Substack** | No link fills in a post or a Note, and no API lets an app post (its developer terms cover reading public profile and publication information only). Its terms also forbid the private routes some tools use. |
| **Instagram** | Pictures and video from a public address, not words. |
| **Facebook Pages** | A Page post from your own app stays hidden until Meta reviews the app. |

## How a short post is written

One write, a version for each site you ticked, each written for its site rather than copied:

1. **Compose** through the prose engine every writer uses ([prose.md](prose.md)): your voice card,
   the floor against AI tells, the site's template, its limit and what Kranto attaches, with your
   angle leading. The model is the writer's own when you chose one (Settings › Posting › How you
   write; the writer is "social"); otherwise the reason tier's.
2. **One model call** a site, through the metered client.
3. **Kranto's code keeps only what the site can carry**: any address that is not the post's link
   is taken off, tags past the site's count go, and the limit is kept the site's way (a sentence
   that does not fit is cut at a sentence, and the draft says so).
4. **Check**, then **revise** only the flagged words (a post that opens by announcing its
   structure, a first sentence that claims nothing, a caveat stack): at most two short rounds.
   What is still flagged is shown under the draft.
5. The **link** is added by code, never written by the model; X and Threads take it beside the
   text so their box draws the card. Bluesky posted directly also gets a **link card** (the post's
   title and teaser) and its links and tags marked so they work.

A thread (two or three posts) is written only for a site you switched to Post directly that can
carry one (Bluesky): an Open fills one post. One site's version failing keeps the others, and the
draft line says which.

**The disclosure line** ("Drafted with Kranto.") is a per-site setting, off by default; your own
words for it are the prose profile's disclosure for that site.

## Connecting

**Bluesky (posting)**, for Post directly. "Kranto posts only a draft you approved in the confirm
dialog." In the Bluesky app open Settings, then Privacy and security, then App passwords; add one
named Kranto, with direct messages off. Paste your handle and the app password on Settings ›
Posting, Bluesky (posting) and choose Save and test; Kranto names it @you. An app password can
do more than post: Kranto only ever posts with it. Your reading connection stays separate and
read-only.

**Mastodon (posting)**, for Post directly: as before (Settings › Posting, Mastodon (posting):
your server and an access token with `read:accounts` and `write:statuses`).

**Mastodon's Open** needs only your server's name (Settings › Posting).

**X, Threads**: nothing to connect for Open. Be signed in to the site in your browser.

**LinkedIn (posting)**, the only way Kranto offers LinkedIn (about ten minutes, once). "Kranto
posts to your profile only a draft you approved." You need a LinkedIn Page to attach the app to
(any Page you manage; LinkedIn's Create a company page takes a minute and can stay empty). Open
`linkedin.com/developers/apps`, Create app, name it Kranto, pick your Page, add a small logo.
On its Products tab request **Share on LinkedIn** and **Sign In with LinkedIn using OpenID
Connect**. Then Docs and tools, OAuth Token Tools, Create token: tick `openid`, `profile` and
`w_member_social`, Request access token, sign in and allow. Paste the token on Settings ›
Posting, LinkedIn (posting). LinkedIn's tokens last 60 days: make a new one when Kranto says so.
The post carries a link card Kranto builds (LinkedIn does not read the page), and its words are
sent in LinkedIn's own format, so a "#" or a bracket reads as written and a tag is a tag.

**Threads (posting)**, for Post directly (about ten minutes, once). At
`developers.facebook.com/apps` choose Create app with the use case "Access the Threads API",
name it Kranto. Under Use cases, Customize beside Threads, add `threads_content_publish` and
`threads_manage_insights` (the second lets Kranto read how your posts did). Under
App roles, Roles, Add people, add your own Threads account as a Threads tester, and accept the
invitation in Threads (Settings, Account, Website permissions, Invites). Under User token
generator choose Generate access token, allow, copy it, and paste it on Settings › Posting,
Threads (posting). Kranto refreshes it while you use it (60 days at a time). The app stays in
development mode, for you only. A thread is not written for Threads: a reply needs one more
permission.

## Send at an hour

A post Kranto posts directly (Bluesky, Mastodon, Threads, LinkedIn) can go at an hour you
choose: in its dialog choose **Schedule**, pick the day and time (your own clock), and say yes.

- **Nothing goes without that yes.** Kranto keeps your yes for those words and that time; the
  draft moves to **Scheduled** on Post, its row saying when and where ("Mon 16 Nov, 09:00 ·
  Bluesky").
- **Move or cancel it until then.** Cancel on its row (or its page) and nothing is sent: the
  draft waits on Post again. Change the time from its page (the same dialog). To change its
  words, cancel first: an edited draft is a new draft and needs a new yes.
- **At the hour, Kranto posts it**, exactly as if you had said yes then. It checks once more that
  the draft and its words are the ones you said yes to.
- **If Kranto was stopped at the hour** (the machine was off or asleep) and starts more than ten
  minutes later, it does **not** post late. The draft waits on Post with "Its hour passed while
  Kranto was stopped", Needs you says so, and you post it now or choose a new time.
- A restart keeps the schedule. The preview never posts, and refuses a schedule.

I posted it (Open) is always now: you post it in the site yourself.

## What each site gives back

Once a day for two weeks after a post Kranto sent, then once a week until it is two months old,
Kranto reads its numbers and shows them on Sent, after where it went ("Bluesky · 4 replies, 9
reposts, 31 likes"; a post you posted yourself reads "X · posted by you"). Never the text of anyone's reply: counts only. Read live on 14 November 2026:

| Site | What Kranto reads | With what |
|---|---|---|
| Bluesky | replies, reposts, likes, quotes (`app.bsky.feed.getPosts`) | Bluesky's public read, no sign-in |
| Mastodon | replies, boosts, favourites, and quotes from Mastodon 4.5 (`GET /api/v1/statuses/:id`) | your posting connection |
| Threads | views, likes, replies, reposts, quotes (media insights) | your token, with `threads_manage_insights` |
| LinkedIn | nothing | LinkedIn gives a member's numbers only to approved partners |
| X | nothing | X charges for each read, and Kranto never posts to X itself |

Sent says once, at its foot, which sites gave no numbers. **What was learned**
(`GET /api/post/learned`): with at least 8 posts on each side of a comparison, Settings ›
Posting says what the numbers support under the site (the better hour, one post or a thread, a
link card or none); with fewer, it says nothing rather than guess.

**LinkedIn's 60 days.** An app like Kranto cannot renew a LinkedIn token. A week before the day
it runs out, Needs you says "LinkedIn needs a new token by 12 January (5 minutes)".

## What is stored

| Stored | What | Readers |
|---|---|---|
| `settings` key `post.sites` | the sites ticked, Post directly per site, your Mastodon server, the disclosure per site | `core.sites.choices`, `post_api.posting_read`/`posting_write`; a missing key or one stored as null reads as none |
| `cub_drafts` of the filer `social` | one row a site: `site`, `group` (one write), `parts`, `text`, `link`, `extras`, `prose`, `language`, `card` (Bluesky posted directly) | Post's read (`_short_row`, `short_sheet`, `siblings`), the edit, the asks below |
| `cub_tickets` kinds `post.open` (I posted it), `post.bluesky`, `post.linkedin`, `post.threads`; `post.mastodon` as before | each waits until you answer it; confirmed on the page only; refused on the preview before anything is written. A held ask stays `needs_confirm` until its hour: no new state | `core.tickets`, `core.asks`, Post |
| `post_due` (migration 44) | your yes for an hour: `held`, then `cancelled`, `missed`, `void` or `spent`, one row a change, never edited; `fields_hash` binds it to the words you read | `social.hours` (the lane, Cancel), `post_api` (`_group`, `_hour_of`), `tickets.press_held` |
| `post_reach` (migration 44) | a sent post's first row (`note` `sent`: the site's own ids, the post's shape), then one row a reading (each count null where the site gives none) | `social.reach` (`posts`, `due`, `newest`, `learned`), `post_api._reach_of` |

## Routes

| Route | What |
|---|---|
| `POST /api/post/write` `{about, as: "short", angle}` | Write a post › Short posts (the job) |
| `POST /api/post/angles` `{about, as}` | the three proposed angles |
| `GET /api/post/d/{id}` | a short post's page: `parts` (each counted), `limit`, `extras`, `siblings`, `open`, `open_off`, `direct` |
| `POST /api/post/d/{id}/posted` | I posted it (the page only; never the preview; no request leaves Kranto) |
| `POST /api/tickets/{id}/confirm` `{confirm: true, when}` | a direct send now (`when: "now"`) or at a UTC time ahead: held, not sent |
| `POST /api/post/d/{id}/cancel` | a scheduled post's Cancel (the page; nothing is sent; the draft waits) |
| `GET /api/post/learned` | per site, what the sent posts' numbers support (at least 8 posts a side) |
| `GET`/`POST /api/post/sites` | Settings › Posting's sites and your choices |

## Sources (read 2026-11-13; reach on 2026-11-14)

- Reach, read 2026-11-14: Bluesky's `app.bsky.feed.getPosts` and its `postView`
  (<https://github.com/bluesky-social/bsky>, `lexicons/app/bsky/feed/`; an `at://` address must
  carry the DID); Mastodon's status and its counts (<https://docs.joinmastodon.org/methods/statuses/>,
  <https://docs.joinmastodon.org/entities/Status/>, `quotes_count` from 4.5.0); Threads' insights
  (<https://developers.facebook.com/docs/threads/insights>); LinkedIn's member post analytics
  (<https://learn.microsoft.com/en-us/linkedin/marketing/community-management/members/post-statistics>:
  the Community Management API, for vetted organisations) and its tokens' 60 days with no
  refresh for a self-serve app
  (<https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow>);
  X's pricing (<https://docs.x.com/x-api/getting-started/pricing>).

- Bluesky's compose link: <https://docs.bsky.app/docs/advanced-guides/intent-links>; posts,
  facets and link cards: <https://docs.bsky.app/docs/advanced-guides/posts>.
- Mastodon's share page: Mastodon's own source, `app/helpers/application_helper.rb` and the
  `/share` route (<https://github.com/mastodon/mastodon>); statuses:
  <https://docs.joinmastodon.org/methods/statuses/>.
- X's post link: <https://docs.x.com/x-for-websites/post-button/guides/web-intent>.
- Threads' post link: <https://developers.facebook.com/docs/threads/threads-web-intents>.
- LinkedIn's share link (an address only): <https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/plugins/share-plugin>;
  posting with your own app: <https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/share-on-linkedin>;
  the Posts API (version 2026-10), its little text format and `userinfo`:
  <https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api>,
  <https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/little-text-format>,
  <https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/sign-in-with-linkedin-v2>.
- Threads posting (a container, then publish; the 30 seconds between), tokens and replies:
  <https://developers.facebook.com/docs/threads/posts>,
  <https://developers.facebook.com/docs/threads/get-started/long-lived-tokens>,
  <https://developers.facebook.com/docs/threads/retrieve-and-manage-replies/create-replies>.
- Substack's developer terms: <https://substack.com/api-tos>; Notes:
  <https://on.substack.com/p/notes-faq>.
