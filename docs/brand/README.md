# The mark, the colour and the name

Kranto's look is small on purpose: one mark, one colour, the name in lowercase. There is no
character, animal or figure, on any public face.

## The mark

A lowercase **k** on a rounded square, drawn on a 64 by 64 grid: white on indigo in light mode,
dark on pale indigo in dark mode.

- The source: [`src/kranto/page/ui/static/brand/mark.svg`](../../src/kranto/page/ui/static/brand/mark.svg).
- The favicons and app icons beside it (`favicon-16.png`, `favicon-32.png`, `favicon-48.png`,
  `favicon.ico`, `icon-180.png`, `icon-192.png`, `icon-512.png`) are drawn from the same
  geometry by [`scripts/dev/make_icons.py`](../../scripts/dev/make_icons.py), which needs Pillow:

      python scripts/dev/make_icons.py

  The script holds the geometry as numbers; change it there and in `mark.svg` together. The
  server's own pages carry copies of the favicons in `src/kranto/web/static/`.

## The colour

One accent: the page's indigo, `#3d44d4` on light and `#aeb6ff` on dark. These are the
`--primary` and `--link` tokens of the page's stylesheet
(`src/kranto/page/ui/static/kranto.css`). No other colour is a brand colour. The pastel violet,
green and amber the page uses are state colours, and stay that.

## The name

In a sentence, **Kranto**. As a wordmark, the name in lowercase, `kranto`, set in the page's own
sans-serif (the `--sans` stack) at weight 650 with tight tracking. No drawing, no tagline
locked to it, no pun on the name.
