# My cub

Drafts one short post a week from your library's strongest observation, for you to read and
approve. It is a cub for [Kranto](https://github.com/iddv/kranto): Kranto runs it in its own
sandbox, with no network, no files of yours and no key, and asks you before anything leaves.

**What it asks for** (Kranto shows you this in words before it installs):

- reads your topics and library;
- one model purpose, `my_cub`, at most $1 a month;
- a Mastodon draft that Kranto holds (`statuses.draft`);
- to **ask you** to post (`post.mastodon`): each post is a ticket you confirm on the page.

**Install** from this folder: `kranto cub add ./my-cub`. It starts in **dry mode**: pressing
Confirm on its ticket posts nothing until you turn posting live on the cub's page.

**Test** without Kranto: `pip install bears-cub-sdk pytest && pytest`.
