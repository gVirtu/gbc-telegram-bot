"""Tests for game event spec modules."""

from src.models.game_state import EventSpec


class TestGameEventsModule:
    def test_event_spec_has_title_and_score(self):
        spec = EventSpec(title="Wild Battle Started", score=50)
        assert spec.title == "Wild Battle Started"
        assert spec.score == 50

    def test_pkpcrystal_game_events_structure(self):
        from src.game_events.pkpcrystal import GAME_EVENTS

        assert isinstance(GAME_EVENTS, dict)
        assert "wild_battle_start" in GAME_EVENTS
        spec = GAME_EVENTS["wild_battle_start"]
        assert isinstance(spec, EventSpec)
        assert spec.title == "Wild Battle Started"
        assert spec.score == 50

    def test_pkpcrystal_game_events_keys_are_EventSpec(self):
        from src.game_events.pkpcrystal import GAME_EVENTS

        for key, spec in GAME_EVENTS.items():
            assert isinstance(key, str)
            assert isinstance(spec, EventSpec)
            assert isinstance(spec.title, str)
            assert isinstance(spec.score, int)
