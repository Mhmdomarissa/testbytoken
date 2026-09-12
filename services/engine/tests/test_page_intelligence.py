"""W7: pytest coverage for Phase 0's D2 fix (page-map locator capture).
No browser — _best_locator and _stable_element_id are pure functions.
"""

from __future__ import annotations

from tests.fakes import FakeElement
from uts_engine.discovery.discovery import _best_locator
from uts_engine.planning.page_intelligence import _stable_element_id


def test_best_locator_populates_locator_for_every_field_in_synthetic_page():
    fields = [
        FakeElement(attrs={"id": "amount"}, tag_name="input"),
        FakeElement(attrs={"name": "send-to"}, tag_name="select"),
        FakeElement(text="Continue", tag_name="button"),
        # No id, no name, no text — must still fall back to something usable.
        FakeElement(attrs={"type": "checkbox"}, tag_name="input"),
    ]
    for el in fields:
        _name_hint, locator_by, locator_value = _best_locator(el)
        assert locator_by, f"missing locator_by for a {el.tag_name} element"
        assert locator_value, f"missing locator_value for a {el.tag_name} element"


def test_best_locator_prefers_id_over_name_and_text():
    el = FakeElement(text="Amount", attrs={"id": "amount", "name": "amt"}, tag_name="input")
    _name_hint, locator_by, locator_value = _best_locator(el)
    assert locator_by == "id"
    assert locator_value == "amount"


def test_stable_element_id_deterministic_and_distinct():
    id1 = _stable_element_id("Transfers", "Transfers > Form", "field", "Amount", "id", "amount")
    id2 = _stable_element_id("Transfers", "Transfers > Form", "field", "Amount", "id", "amount")
    id3 = _stable_element_id("Transfers", "Transfers > Form", "field", "Send from", "id", "send-from")

    assert id1 == id2, "identical inputs must hash to the same id"
    assert id1 != id3, "distinct inputs must hash to distinct ids"
    assert id1  # non-empty
