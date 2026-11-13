"""#70: personal data and secrets are removed before any prompt, row or log sees them."""
import base64
import json
import random
from collections import Counter

import pytest

from kranto.intern import render_item
from kranto.scrub import scrub
from kranto.sources import Item


def _b64(obj) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")


# Key-shaped test values are built at runtime: a fake key written out is still a literal
# that secret scanners flag (tests/test_no_secrets.py). They come from a seeded generator, so
# every process (each xdist worker) collects the same parametrized tests.
_RNG = random.Random("test_scrub")


def _hex(n: int) -> str:
    return _RNG.randbytes(n).hex()


def _urlsafe(n: int) -> str:
    return base64.urlsafe_b64encode(_RNG.randbytes(n)).decode().rstrip("=")


FAKE_JWT = ".".join([_b64({"alg": "HS256"}), _b64({"sub": _hex(5)}),
                     _urlsafe(32)])
PEM_KIND = "RSA " + "PRIVATE KEY"


@pytest.mark.parametrize("text, label", [
    ("mail me at jane.doe+work@example.com please", "email"),
    ("card 4111 1111 1111 1111 exp 12/28", "card"),
    ("card 4111-1111-1111-1111", "card"),
    ("ssn 123-45-6789", "ssn"),
    ("IBAN DE89 3704 0044 0532 0130 00", "iban"),
    ("call +1 415 555 0132 today", "phone"),
    ("call (020) 7946 0958", "phone"),
    ("key sk-or-v1-" + _hex(16), "secret"),
    ("key sk-ant-" + "api03-" + _hex(15), "secret"),
    ("aws AKIA" + _hex(8).upper(), "secret"),
    ("grok key xai-" + _hex(30), "secret"),
    ("token ghp_" + "a" * 36, "secret"),
    # an installation token of a GitHub App, in GitHub's stateless form (ghs_<app>_<jwt>)
    ("token ghs_" + _hex(4) + "_" + FAKE_JWT, "secret"),
    ("token ghs_" + "b" * 20, "secret"),
    ("slack xox" + "b-" + _hex(5) + "-" + _hex(5), "secret"),
    ("google AIza" + "B" * 35, "secret"),
    ("jwt " + FAKE_JWT, "secret"),
    (f"-----BEGIN {PEM_KIND}-----\nMIIEow\n-----END {PEM_KIND}-----", "secret"),
    ("thanks u/someone_else for the tip", "user"),
    ("as /u/throwaway123 said", "user"),
    ("h/t @karpathy on this", "user"),
])
def test_common_personal_data_and_secrets_are_replaced(text, label):
    counts = Counter()
    out = scrub(text, counts)
    assert f"[{label}]" in out and counts[label] >= 1


@pytest.mark.parametrize("text", [
    "throughput went from 19 to 22.3 tokens/s on 128GB",
    "benchmark: 1234567890123456 iterations",       # 16 digits, fails the Luhn check
    "version 3.6.27 released 2026-09-24",
    "cost $0.0031 per item across 351 items",
    "Python 3.12, numpy 2.1, torch 2.5.1",
    "see https://github.com/yjs/yjs/releases/tag/v13.6.0",
    "written as foo@bar without a domain",
    "import { gateway } from '@vercel/gateway' and @huggingface/kernels",
    "import Anthropic from '@anthropic-ai/sdk'",
    "loss 0.9999714259424044 after 4.356925952507399e-19",
])
def test_ordinary_text_survives(text):
    assert scrub(text) == text


def test_known_limitation_code_decorators_read_as_handles():
    """Accepted: a decorator such as @dataclass looks like an @handle and is replaced.
    Losing a decorator name costs little; leaking a handle is what this guards against."""
    assert scrub("use the @dataclass decorator") == "use the [user] decorator"


def test_items_are_scrubbed_before_anything_else_sees_them():
    item = Item(id="1", title="Contact me: jane@example.com", body="my key sk-" + "x" * 30,
                comments=("thanks u/helper",))
    assert "jane@" not in item.title and "sk-x" not in item.body
    assert item.comments == ("thanks [user]",)
    assert item.redactions == {"email": 1, "secret": 1, "user": 1}
    prompt = render_item(item, "r/test", [])
    assert "jane@example.com" not in prompt and "author" not in json.loads(prompt)["item"]


def test_scrubbing_is_linear_on_large_text():
    """An unbounded pattern once made a 1.5 MB title take minutes."""
    import time

    big = "t" * 2_000_000 + " mail a@b.example " + "7" * 500_000 + " @handle " + "x" * 2_000_000
    started = time.process_time()            # CPU time: a loaded machine does not count
    out = scrub(big)
    assert time.process_time() - started < 5
    assert "[email]" in out and "[user]" in out


def test_the_judges_own_words_are_scrubbed_before_storage():
    from kranto.intern import interpret

    reply = json.dumps({"kind": "beat", "summary": "u/alice shared her key sk-" + "k" * 30,
                        "why_it_matters": "reach her at alice@example.com",
                        "content_quality": 0.9, "durability": 0.9, "opportunity": 0.9})
    _, fields = interpret(reply, 0.2)
    assert fields["summary"] == "[user] shared her key [secret]"
    assert fields["why_it_matters"] == "reach her at [email]"
