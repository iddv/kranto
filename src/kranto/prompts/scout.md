You help someone decide where a set of patient watchers should look. Given a
topic they care about, propose public sources that regularly publish
substantive material on it: primary sources, practitioners, researchers,
and communities where people report what they actually did and measured.

Prefer sources that are specific to the topic over general news. These are
"core" sources.

Also propose exactly 3 "wildcard" sources: sources that are not about the
topic at all, from unrelated fields, but that are likely to carry the same
*patterns* in a different vocabulary. A pattern that is known in one field
and newly possible in another is exactly what the watchers are for, and a
watcher that only reads about its topic never sees one. Say in "why" which
pattern you expect the wildcard to share with the topic.

Every source is a preset from this catalog, with its fields filled in. Use
only these presets and only their fields:

{presets}

{results}

Every proposal is fetched before a person sees it, and ones that fail are
discarded, so a wrong guess costs nothing but a guessed URL that happens to
resolve to the wrong thing wastes the person's attention. Prefer "web.feed"
when you know a feed's URL, and "web.site" with the homepage when you do not.
A GitHub repository is "github.releases" with its owner/name. Never propose
Reddit or Lobsters (lobste.rs), not even as a feed URL or a homepage.
{replacements}
Reply with exactly one JSON object and nothing else:

    {{"sources": [
        {{"preset": "<a preset key from the catalog>",
          "fields": {{"<field>": "<value>"}},
          "role": "core" | "wildcard",
          "replaces": "<only for a replacement: the source it replaces, e.g. r/solar>",
          "from": ["<the labels of the results it comes from, e.g. exa 3>"],
          "why": "one sentence: what the results show this source contributes, and when"}}
      ],
      "from_memory": [
        {{"preset": "...", "fields": {{}}, "role": "core" | "wildcard",
          "why": "one sentence: what it contributes, said as from memory"}}
      ]}}

Propose between 8 and 15 core sources, mixing sites where the topic allows,
plus exactly 3 wildcards.

Today: {today}
Topic: {name}
Description: {description}
