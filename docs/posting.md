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
| **Threads** | `https://www.threads.com/intent/post?text=…&url=…` | Not yet (your own Meta app: the next release) | 500 characters, an emoji counted as its bytes | not yet sent for real |

**Not possible today** (Settings › Posting lists them with these reasons):

| Site | Why |
|---|---|
| **Substack** | No link fills in a post or a Note, and no API lets an app post (its developer terms cover reading public profile and publication information only). Its terms also forbid the private routes some tools use. |
| **LinkedIn** | No documented link fills in a post's text: its share link carries an address only. Posting directly needs your own LinkedIn app with "Share on LinkedIn"; that comes in the next release, as Post directly only. |
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

**X, Threads**: nothing to connect. Be signed in to the site in your browser.

## What is stored

| Stored | What | Readers |
|---|---|---|
| `settings` key `post.sites` | the sites ticked, Post directly per site, your Mastodon server, the disclosure per site | `core.sites.choices`, `post_api.posting_read`/`posting_write`; a missing key or one stored as null reads as none |
| `cub_drafts` of the filer `social` | one row a site: `site`, `group` (one write), `parts`, `text`, `link`, `extras`, `prose`, `language`, `card` (Bluesky posted directly) | Post's read (`_short_row`, `short_sheet`, `siblings`), the edit, the asks below |
| `cub_tickets` kinds `post.open` (I posted it), `post.bluesky`; `post.mastodon` as before | each waits until you answer it; confirmed on the page only; refused on the preview before anything is written | `core.tickets`, `core.asks`, Post |

## Routes

| Route | What |
|---|---|
| `POST /api/post/write` `{about, as: "short", angle}` | Write a post › Short posts (the job) |
| `POST /api/post/angles` `{about, as}` | the three proposed angles |
| `GET /api/post/d/{id}` | a short post's page: `parts` (each counted), `limit`, `extras`, `siblings`, `open`, `open_off`, `direct` |
| `POST /api/post/d/{id}/posted` | I posted it (the page only; never the preview; no request leaves Kranto) |
| `GET`/`POST /api/post/sites` | Settings › Posting's sites and your choices |

## Sources (read 2026-11-13)

- Bluesky's compose link: <https://docs.bsky.app/docs/advanced-guides/intent-links>; posts,
  facets and link cards: <https://docs.bsky.app/docs/advanced-guides/posts>.
- Mastodon's share page: Mastodon's own source, `app/helpers/application_helper.rb` and the
  `/share` route (<https://github.com/mastodon/mastodon>); statuses:
  <https://docs.joinmastodon.org/methods/statuses/>.
- X's post link: <https://docs.x.com/x-for-websites/post-button/guides/web-intent>.
- Threads' post link: <https://developers.facebook.com/docs/threads/threads-web-intents>.
- LinkedIn's share link (an address only): <https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/plugins/share-plugin>;
  posting with your own app: <https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/share-on-linkedin>.
- Substack's developer terms: <https://substack.com/api-tos>; Notes:
  <https://on.substack.com/p/notes-faq>.
