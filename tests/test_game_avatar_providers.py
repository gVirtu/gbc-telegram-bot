"""Tests for game avatar provider modules."""
from PIL import Image


class TestPkpcrystalAvatarProvider:
    """Tests for the pkpcrystal avatar provider."""

    def test_get_avatar_returns_image(self):
        """get_avatar returns a PIL Image."""
        from src.game_avatar_providers.pkpcrystal import get_avatar
        result = get_avatar({})
        assert isinstance(result, Image.Image)

    def test_get_avatar_is_rgba(self):
        """get_avatar returns an RGBA image."""
        from src.game_avatar_providers.pkpcrystal import get_avatar
        result = get_avatar({})
        assert result.mode == "RGBA"

    def test_get_avatar_has_nonzero_size(self):
        """get_avatar returns a 56x56 image."""
        from src.game_avatar_providers.pkpcrystal import get_avatar
        result = get_avatar({})
        assert result.size == (56, 56)

    def test_get_avatar_ignores_player_data(self):
        """get_avatar returns the same cached instance regardless of player dict content."""
        from src.game_avatar_providers.pkpcrystal import get_avatar
        result1 = get_avatar({})
        result2 = get_avatar({"user_name": "Alice", "user_id": 42, "unexpected_key": True})
        assert result1 is result2
