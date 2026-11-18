"""An update of a cub from a source nobody reviewed (a git address) waits for the owner's press
by default, even when it asks for nothing new (``cubs.auto_update_unreviewed``, off). The
owner's own cubs (a folder), and reviewed or Kranto's own, apply by themselves as before."""

from __future__ import annotations

from types import SimpleNamespace

from kranto.core.cubs import install
from kranto.core.cubs import settings as cs


def staged(trust):
    """A staged update that adds no permission and no send, inside this Kranto's range."""
    rec = {"id": "hello", "version": "1.2.0", "manifest": {}, "delta": {"added": {}}}
    if trust is not ...:
        rec["trust"] = trust
    return rec


def cfg(**cubs):
    return SimpleNamespace(cubs=cs.parse(cubs), root=None)


def test_the_setting_is_off_by_default_and_named():
    assert cs.values(None)["cubs.auto_update_unreviewed"] is False
    assert cs.values(None)["cubs.auto_update"] is True              # the owner's rule stays
    assert "nobody reviewed" in cs.GLOBAL["cubs.auto_update_unreviewed"].words


def test_an_update_from_an_unreviewed_source_waits_for_the_press():
    for trust in ("listed", "unreviewed", "generated"):
        assert install.waits_why(staged(trust)) == install.UNREVIEWED_WAITS, trust
        assert install.waits_why(staged(trust), cfg()) == install.UNREVIEWED_WAITS, trust
    assert install.UNREVIEWED_WAITS.startswith("waits for your approval")


def test_a_record_without_a_known_trust_is_taken_as_unreviewed():
    for trust in (..., None, "", "trusted", 3):
        assert install.waits_why(staged(trust)) == install.UNREVIEWED_WAITS, trust


def test_the_owners_and_reviewed_cubs_apply_by_themselves_as_before():
    for trust in ("core", "first-party", "owner", "reviewed"):
        assert install.waits_why(staged(trust)) is None, trust


def test_the_owner_can_let_unreviewed_updates_apply_by_themselves():
    on = cfg(auto_update_unreviewed=True)
    assert install.waits_why(staged("unreviewed"), on) is None
    # what an update asks for still waits, whatever the source
    grown = {**staged("unreviewed"), "delta": {"added": {"requests": ["post"]}}}
    assert install.waits_why(grown, on) == "asks to send something new"
    assert install.waits_why({**staged("owner"), "delta": {"added": {"net": ["x"]}}}) \
        == "asks for one more permission"
