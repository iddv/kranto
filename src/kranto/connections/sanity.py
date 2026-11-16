"""Sanity: the one Sanity project and dataset a cub's drafts are filed into.

Connected with a pasted robot token (Sanity › Manage › API › Tokens; an **Editor** token on
the Free plan, which has no draft-only role: Kranto's ``sanity`` broker offers no publish, no
delete, and writes only documents whose id starts with ``drafts.kranto-``). The project id and
the dataset name the connection (``yourprojectid/production``); requests carry the token only to
``<project>.api.sanity.io``.

Save and test only reads: one GROQ count over the drafts, which a public dataset answers
without a token only for published documents, so a token Sanity does not accept is said in
plain words. Whether the token may write is learned at the first live press (403: refused).

The Studio's address and the site's post address (both optional, not secret) are kept in the
library's settings (``sanity.site``) for the confirm's read-back and the Studio link.
"""

from __future__ import annotations

import re

from ..sources.base import SourceError
from ..stored.settings import SanitySite, get_blob, set_blob
from .base import Bearer, Grant, Provider, need, status_of
from .oauth import OAuthError
from .secret import Secret

API_VERSION = "v2021-06-07"            # its queries see drafts with a token (perspective raw)
PROJECT = re.compile(r"[a-z0-9]{4,32}")
DATASET = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
URL = re.compile(r"https://[A-Za-z0-9.-]{1,120}(/[A-Za-z0-9._~/-]{0,120})?")
SITE_KEY = "sanity.site"
SCOPES = ("drafts",)
DEADLINE_S = 30.0


def api_host(project: str) -> str:
    return f"{project}.api.sanity.io"


def api_base(instance: str) -> str:
    """``https://<project>.api.sanity.io/<version>/data`` for ``project/dataset``."""
    project = instance.split("/", 1)[0]
    return f"https://{api_host(project)}/{API_VERSION}/data"


def dataset_of(instance: str) -> str:
    return instance.split("/", 1)[1]


def site(store) -> dict:
    """``{studio?, post_url?}``: where the Studio and the site's posts are (never a secret)."""
    got = get_blob(store, SITE_KEY, SanitySite) if store is not None else None
    return got.to_dict() if got is not None else {}


def _url(fields: dict, key: str, what: str) -> str | None:
    value = str(fields.get(key) or "").strip().rstrip("/")
    if not value:
        return None
    if not URL.fullmatch(value):
        raise OAuthError(f"{what} is an https:// address, like {_EXAMPLES[key]}")
    return value


_EXAMPLES = {"studio": "https://your-studio.sanity.studio",
             "post_url": "https://your-site.example/blog"}


class SanityProvider(Provider):
    key = "sanity"
    name = "Sanity"
    scopes = SCOPES
    single = False                     # recorded under project/dataset
    writes = True
    exclusive = True                   # one Sanity dataset per Kranto

    def instance(self, value: str | None) -> str:
        return str(value or "").strip().lower()

    def api_host(self, instance: str, entry: dict) -> str:
        return api_host(instance.split("/", 1)[0])

    def headers(self, entry: dict, method: str, url: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {entry['key']}"}

    def paste_instance(self, fields: dict) -> str:
        project = need(fields, "project", "The project id").lower()
        dataset = str(fields.get("dataset") or "production").strip().lower()
        if not PROJECT.fullmatch(project):
            raise OAuthError("The project id is the short name in Sanity's Manage page and "
                             "in sanity.config (letters and digits, like abc123de)")
        if not DATASET.fullmatch(dataset):
            raise OAuthError("The dataset is a name like production")
        return f"{project}/{dataset}"

    def paste(self, fields: dict) -> Grant:
        instance = self.paste_instance(fields)
        token = Secret(need(fields, "token", "The token"))
        studio, post_url = _url(fields, "studio", "The Studio"), \
            _url(fields, "post_url", "The posts' address")
        http = self.http.with_auth(Bearer(api_host(instance.split("/", 1)[0]), token))
        try:
            drafts = self._count(http, instance)
        except SourceError as exc:
            if exc.needs_login:
                raise OAuthError("Sanity refused this token (HTTP 401): copy it again from "
                                 "Manage, API, Tokens") from None
            raise OAuthError(f"Sanity did not answer ({status_of(exc)}); nothing was "
                             "kept") from None
        if self.conns is not None:
            set_blob(self.conns.store, SITE_KEY,
                     SanitySite(studio=studio or None, post_url=post_url or None))
        note = (f"The token reads {instance}: {drafts} draft{'' if drafts == 1 else 's'} there "
                "now. Kranto files drafts only; you publish in Studio.")
        return Grant(instance, SCOPES, {"key": token.reveal()}, note=note)

    def identify(self, http, instance: str, entry: dict) -> str:
        try:
            self._count(http, instance)
        except SourceError as exc:
            raise OAuthError(f"Sanity answered {status_of(exc)}") from None
        return instance

    def _count(self, http, instance: str) -> int:
        r = http.get(f"{api_base(instance)}/query/{dataset_of(instance)}",
                     params={"query": 'count(*[_id in path("drafts.**")])'},
                     deadline=DEADLINE_S, errors=False)
        if r.status_code in (401, 403):
            raise SourceError(f"needs login: HTTP {r.status_code}", needs_login=True,
                              status=r.status_code)
        if r.status_code == 404:
            raise OAuthError(f"Sanity has no dataset {dataset_of(instance)} in project "
                             f"{instance.split('/', 1)[0]}")
        if not 200 <= r.status_code < 300:
            raise SourceError(f"HTTP {r.status_code}", status=r.status_code)
        try:
            n = r.json().get("result")
        except (ValueError, AttributeError):
            n = None
        return n if isinstance(n, int) and not isinstance(n, bool) else 0


INFO = {
    "key": "sanity", "name": "Sanity", "state": "available", "flow": "paste", "writes": True,
    "blurb": "The Sanity workspace your posts are filed into as drafts: Kranto drafts a post, "
             "and files it in Sanity with this token only when you approve it "
             "(Send to Sanity). It never puts a post live: you do that in Studio.",
    "scopes": ["Editor (Sanity's Free plan has no draft-only role; Kranto writes drafts only)"],
    "reads": "Whether a draft or a post with the same id or slug is already there, and how many "
             "drafts the dataset holds.",
    "never": "Never publishes, deletes or edits a published post; never writes a document "
             "whose id does not start with drafts.kranto-; never overwrites a draft you edited "
             "in Studio. Never files while the blog is in practice (the default: nothing is "
             "sent) or stopped.",
    "revoke_at": "sanity.io/manage, your project, API, Tokens: delete the token.",
    "expiry": "no expiry",
    "steps": ["Open sanity.io/manage and your project. Under API, Tokens, click Add API token.",
              "Name it kranto-drafts and choose Editor (the Free plan has no "
              "Contributor role; Kranto itself never publishes). Copy the token: Sanity shows "
              "it once.",
              "Paste the project id (as in sanity.config), the dataset (production) and the "
              "token below. Optionally your Studio's address and your posts' address, so the "
              "confirm can link to them. Click Save and test: Kranto only reads.",
              "Send to Sanity is practice (nothing is sent) until you turn on Send for real."],
    "fields": [{"key": "project", "label": "Project id", "placeholder": "yourprojectid"},
               {"key": "dataset", "label": "Dataset", "placeholder": "production"},
               {"key": "token", "label": "Token", "secret": True},
               {"key": "studio", "label": "Studio address (optional)",
                "placeholder": "https://your-studio.sanity.studio"},
               {"key": "post_url", "label": "Posts' address (optional)",
                "placeholder": "https://your-site.example/blog"}],
    "sources": [],
}
