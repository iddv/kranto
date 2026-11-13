"""A small fake web for tests that read pages (look, sponsors): an article, the pages it links,
a Hacker News thread and a GitHub repository. Kept from the deep dive's tests when the deep
dive left Kranto (cut 2); no request leaves the test."""

from __future__ import annotations

import base64

import httpx

from kranto.sources import HTTP

PUBLIC = ["93.184.216.34"]
ARTICLE = "https://article.test/post"
PARAGRAPH = ("Measured on a 40 kWh community battery over 18 months, the round-trip "
             "efficiency fell from 91% to 84%, and the operator published the full log. ")


def page(title, links=(), body=PARAGRAPH * 8):
    anchors = " ".join(f'<a href="{u}">source {i}</a>' for i, u in enumerate(links))
    return (f"<html><head><title>{title}</title></head><body><nav><a href='/'>Home</a></nav>"
            f"<article><h1>{title}</h1><p>{body}</p><p>See {anchors}.</p>"
            f"<p>{body}</p></article></body></html>")


def comment(i, text, children=()):
    return {"id": 5000 + i, "text": text, "children": list(children)}


def hn_thread(n_comments=8):
    """A thread with links in the comments and a repository named twice."""
    kids = [comment(0, '<p>The study is <a href="https:&#x2F;&#x2F;paper.test&#x2F;study">'
                       'here</a>; mail me at someone@example.com</p>',
                    [comment(1, 'And the code: <a href="https://github.com/acme/widget">'
                                'widget</a>', [comment(2, "deep reply")])]),
            comment(3, 'Same repo <a href="https://github.com/acme/widget">again</a>')]
    kids += [comment(10 + i, f"<p>Plain comment {i} about battery fade.</p>")
             for i in range(n_comments - 4)]
    return {"id": 1001, "title": "Battery fade measured", "url": ARTICLE, "text": None,
            "children": kids}


class Web:
    """Answers a page reader's requests; counts them by host."""

    def __init__(self, thread=None, **overrides):
        self.thread = thread if thread is not None else hn_thread()
        self.overrides = overrides
        self.hits: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.hits.append(url)
        for prefix, response in self.overrides.items():
            if url.startswith(prefix):
                return response() if callable(response) else response
        if url.startswith("https://hn.algolia.com/api/v1/items/"):
            return httpx.Response(200, json=self.thread)
        if url == ARTICLE:
            return httpx.Response(200, html=page(
                "Battery fade", ["https://article.test/related", "https://data.test/log"]))
        if url.startswith("https://paper.test/") or url.startswith("https://data.test/"):
            return httpx.Response(200, html=page(f"Page {url}"))
        if url == "https://api.github.com/repos/acme/widget":
            return httpx.Response(200, json={
                "full_name": "acme/widget", "description": "Battery log analyser",
                "stargazers_count": 120, "forks_count": 4, "language": "Python",
                "pushed_at": "2026-09-20T00:00:00Z", "archived": False,
                "html_url": "https://github.com/acme/widget"})
        if url == "https://api.github.com/repos/acme/widget/readme":
            text = "# widget\n![badge](https://x/b.svg)\nReads battery logs. " * 5
            return httpx.Response(200, json={"encoding": "base64",
                                             "content": base64.b64encode(text.encode()).decode()})
        return httpx.Response(404)


def http_for(web):
    return HTTP(transport=httpx.MockTransport(web), resolver=lambda h: PUBLIC)
