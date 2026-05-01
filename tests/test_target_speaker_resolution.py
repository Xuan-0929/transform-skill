from __future__ import annotations

from types import SimpleNamespace

from persona_distill.workflow import _resolve_target_speaker


def _items(*speakers: str) -> list[SimpleNamespace]:
    return [SimpleNamespace(speaker=s) for s in speakers]


def test_resolve_target_speaker_prefers_requested_when_present() -> None:
    items = _items("A", "B", "A", "C")
    resolved = _resolve_target_speaker(
        items,
        requested_speaker="B",
        state_speaker=None,
        persona_id="persona-x",
    )
    assert resolved == "B"


def test_resolve_target_speaker_uses_state_when_requested_missing() -> None:
    items = _items("A", "A", "C")
    resolved = _resolve_target_speaker(
        items,
        requested_speaker="B",
        state_speaker="C",
        persona_id="persona-x",
    )
    assert resolved == "C"


def test_resolve_target_speaker_falls_back_to_dominant_speaker() -> None:
    items = _items("A", "A", "B", "A", "C")
    resolved = _resolve_target_speaker(
        items,
        requested_speaker=None,
        state_speaker=None,
        persona_id="persona-x",
    )
    assert resolved == "A"
