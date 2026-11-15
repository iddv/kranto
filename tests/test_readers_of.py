"""scripts/dev/readers_of.py: a stored field's readers, through its contract
family and by the table's name."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("readers_of",
                                               ROOT / "scripts" / "dev" / "readers_of.py")
readers_of = importlib.util.module_from_spec(_spec)
sys.modules["readers_of"] = readers_of
_spec.loader.exec_module(readers_of)


def test_a_contracts_family_holds_its_subclasses_and_the_types_it_nests():
    fams = readers_of.families(readers_of.py_files())
    assert fams[("syntheses", "input_ids")].names == {"SynthesisInputIds", "InputIds"}
    card = fams[("ideas", "card")]
    assert {"Card", "Evidence", "Rating", "Demand", "PriorArt"} <= card.names
    assert fams[("news_briefs", "items")].module.name == "stored.py"      # a feature's own


def test_the_readers_of_a_key_are_the_files_that_use_its_contract(capsys):
    assert readers_of.main(["sources.validation", "median_similarity"]) == 0
    out = capsys.readouterr().out
    typed = out.split("Through the contract")[1].split("By the table's name")[0]
    assert "src/kranto/source_health.py  lines" in typed
    assert "  src/kranto/stored/sources.py" not in out        # the contract is not a reader


def test_a_column_without_a_contract_is_read_by_name(capsys):
    assert readers_of.main(["settings.value"]) == 0
    assert "no contract type yet" in capsys.readouterr().out
