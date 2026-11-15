"""An issue's markdown as the HTML a platform that takes HTML sends.

Only what a newsletter cub writes is rendered: paragraphs, line breaks, ``**bold**``, ``*italic*``
and ``[label](https://...)`` links. Everything else is text: every character of the body is
escaped first, so nothing a model or a source wrote becomes markup, a script or a style; a link
is kept only when its address is ``https://`` (or ``http://``) and carries no quote or angle
bracket. The plain-text part is the markdown itself.
"""

from __future__ import annotations

import html
import re

# matched on the escaped text: an address with a quote in it (now ``&quot;`` or ``&#x27;``)
# is left as text
_LINK = re.compile(r"\[([^\[\]\n]{1,300})\]\((https?://(?:(?!&quot;|&#x27;)[^\s()<>\"']){1,2000})\)")
_BOLD = re.compile(r"\*\*([^*\n]{1,2000})\*\*")
_ITALIC = re.compile(r"(?<![*\w])\*([^*\n]{1,2000})\*(?![*\w])")


def _inline(text: str) -> str:
    out = html.escape(text, quote=True)
    # the escaped text cannot hold a tag, so the replacements below are the only markup
    out = _LINK.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', out)
    out = _BOLD.sub(r"<strong>\1</strong>", out)
    return _ITALIC.sub(r"<em>\1</em>", out)


def to_html(body: str, *, footer: str | None = None) -> str:
    """The body's paragraphs as HTML, then ``footer`` (already HTML: the platform's own,
    such as an unsubscribe link) in a last paragraph."""
    paras = [p for p in re.split(r"\n\s*\n", body.strip()) if p.strip()]
    parts = ["<p>" + "<br>\n".join(_inline(line) for line in p.strip().split("\n")) + "</p>"
             for p in paras]
    if footer:
        parts.append(f'<p style="font-size:12px;color:#666">{footer}</p>')
    return "\n".join(parts)


def to_text(body: str, *, footer: str | None = None) -> str:
    return body.strip() + (f"\n\n{footer}" if footer else "")
