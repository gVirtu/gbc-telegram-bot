"""Tests for game event spec modules."""

from src.models.game_state import EventSpec


class TestGameEventsModule:
    def test_event_spec_has_title_and_score(self):
        spec = EventSpec(title="Wild Battle Started", score=50)
        assert spec.title == "Wild Battle Started"
        assert spec.score == 50

    def test_event_spec_defaults_addr_bank_condition(self):
        spec = EventSpec(title="Test", score=10)
        assert spec.addr is None
        assert spec.bank is None
        assert spec.condition is None

    def test_event_spec_with_addr(self):
        spec = EventSpec(title="Test", score=10, addr="DoBattle.wild")
        assert spec.addr == "DoBattle.wild"
        assert spec.bank is None
        assert spec.condition is None

    def test_event_spec_with_condition(self):
        cond = lambda c: True
        spec = EventSpec(title="Test", score=10, addr="Foo", condition=cond)
        assert spec.condition is cond

    def test_pkpcrystal_game_events_structure(self):
        from src.game_events.pkpcrystal import GAME_EVENTS

        assert isinstance(GAME_EVENTS, dict)
        assert "wild_battle_start" in GAME_EVENTS
        spec = GAME_EVENTS["wild_battle_start"]
        assert isinstance(spec, EventSpec)
        assert spec.title == "Wild Battle Started"
        assert spec.score == 5
        assert spec.addr == "DoBattle.wild"
        assert spec.condition is not None  # must filter out trainer battles

    def test_pkpcrystal_game_events_have_twelve_entries(self):
        from src.game_events.pkpcrystal import GAME_EVENTS

        assert len(GAME_EVENTS) == 12

    def test_pkpcrystal_all_entries_have_addr_and_score(self):
        from src.game_events.pkpcrystal import GAME_EVENTS

        for key, spec in GAME_EVENTS.items():
            assert isinstance(spec.addr, str), f"{key} missing addr"
            assert isinstance(spec.score, int), f"{key} missing score"
            assert spec.score > 0, f"{key} score must be positive"

    def test_pkpcrystal_dedup_events_share_symbol(self):
        from src.game_events.pkpcrystal import GAME_EVENTS

        wild_faint = GAME_EVENTS["wild_defeated"]
        trainer_faint = GAME_EVENTS["trainer_pokemon_defeated"]
        assert wild_faint.addr == trainer_faint.addr == "EnemyMonFaintedAnimation"
        assert wild_faint.condition is not None
        assert trainer_faint.condition is not None

    def test_pkpcrystal_game_events_keys_are_EventSpec(self):
        from src.game_events.pkpcrystal import GAME_EVENTS

        for key, spec in GAME_EVENTS.items():
            assert isinstance(key, str)
            assert isinstance(spec, EventSpec)
            assert isinstance(spec.title, str)
            assert isinstance(spec.score, int)

    def test_pkpcrystal_wild_shiny_has_condition(self):
        from src.game_events.pkpcrystal import GAME_EVENTS

        spec = GAME_EVENTS["wild_shiny_sparkle"]
        assert spec.addr == "BattleStartMessage"
        assert spec.condition is not None
        assert spec.score == 4096

    def test_pkpcrystal_hall_of_fame_score(self):
        from src.game_events.pkpcrystal import GAME_EVENTS

        spec = GAME_EVENTS["hall_of_fame"]
        assert spec.score == 2500
        assert spec.addr == "HallOfFame"
