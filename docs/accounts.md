# Accounts and their terms

Kranto uses services in your name: a model provider for every install, and only the others you
choose. For each one, this page says what Kranto uses it for, what it needs from you, and what to
check in that provider's own terms. It is not legal advice, and it draws no conclusion about
what a provider allows: terms change, and they bind you, not Kranto. Read their terms.

Checked on 2026-11-13. A date beside a provider is when its terms were last read for this page.

## The model that reads for you

One of these, chosen in Welcome or `kranto setup` (Settings › Watching).

| Provider | What Kranto uses it for | What it needs | What to check in their terms |
|---|---|---|---|
| Anthropic (the Claude API) | judging items, briefs, idea cards, drafts | an API key from the Claude Console | the usage policy and the commercial terms for API keys; set a spending limit on the key |
| Your Claude Code login | the same, billed to your Claude plan | Claude Code installed and signed in; chosen on purpose, never by default | setup shows this line when you choose it: Anthropic's terms describe subscription login as meant for ordinary, individual use and ask developers building products to use API keys. Read the current consumer terms yourself |
| OpenRouter | the same, through a model you pick there | an OpenRouter key | OpenRouter's terms, and those of the model's own provider, which OpenRouter passes on |
| Another OpenAI-compatible endpoint | the same | its address, and a key if it asks for one | the terms of whoever runs the endpoint. A local server is untested |

## The console

| Provider | What Kranto uses it for | What it needs | What to check in their terms |
|---|---|---|---|
| Claude Code | the console beside every page, and Open in Claude Code | Claude Code installed and signed in, on your own plan. Kranto runs the unmodified program under your login and never handles the credential | Anthropic's terms for Claude Code and your plan's usage limits |
| Codex | the console, if you pick it | Codex installed and signed in | OpenAI's terms for Codex |

Kranto works without either.

## Live search

Optional, set on Settings › Watching. Used by the scout to find sources and by News.

| Provider | What it needs | What to check in their terms |
|---|---|---|
| Anthropic's web search | your Anthropic key; searches are billed on it | the same terms as your key |
| Brave Search API | a Brave Search API key | what the plan you chose allows: storing results, and showing them to a model |
| Tavily | a Tavily key | the same |
| Exa | an Exa key | the same |

## Accounts that read with your login

Each is off until you connect it on Settings › Accounts. Each reads only what your account can
already see, with read-only permissions fixed in code. [RESPONSIBLE_USE.md](../RESPONSIBLE_USE.md)
has the scopes and what is kept.

| Site | What it needs | What to check in their terms |
|---|---|---|
| Mastodon | a sign-in on your instance | your instance's terms and rules, which differ from one instance to the next |
| Bluesky | a sign-in (or an app password where sign-in cannot work) | Bluesky's terms and developer guidelines |
| GitHub | a fine-grained token with read-only access to public repositories, or a sign-in | GitHub's terms for API use |
| YouTube | your own Google Cloud project's desktop client | YouTube's API terms and developer policies. Kranto keeps YouTube data at most 30 days because those policies require it |
| Product Hunt | a developer token | Product Hunt's API terms, which limit it to non-commercial use |
| Stack Exchange | an app key (raises the daily allowance; not a login) | the API terms; content is CC BY-SA, so attribute anything you publish from it |
| X | your own developer account and app; X bills that account per post read | the Developer Agreement (last updated 2026-04-27, per X), the Developer Policy and the Display Requirements. The use-case description you give X binds you. Whether a model may read posts for your notes is X's to answer: read the analysis clause yourself or ask X |
| X through Grok | an xAI key (`XAI_API_KEY`); billed per post read plus tokens | xAI's terms for the key |
| Reddit | your own app, approved by Reddit in your name | Reddit's Responsible Builder Policy and Data API Terms. Reddit announced that new access requests end on 31 October 2026, its feeds stop on 13 November 2026, and public Data API access closes in March 2027. Whether personal research counts as commercial use is Reddit's to say |

## Public sources with no account

Feeds, blogs, Hacker News (through Algolia's public API), arXiv, newsletters' public feeds and
YouTube channels' feeds need no account. Their terms still apply to you. Kranto's requests name
themselves (`kranto/<version> (+https://github.com/iddv/kranto)`), arXiv is read no faster than
its terms ask, and a newsletter publication added from the catalog is kept 30 days. Lobsters
asks AI readers not to read it, so the catalog leaves it out. A feed you add by hand is your
decision.

## Where posts go

A post or a newsletter issue goes to one account you connected, only when you click Send. The
newsletter platforms, what each needs and how to connect them are in
[newsletter.md](newsletter.md). Each platform's own terms, and its rules on sending email to
your list, apply to you.
