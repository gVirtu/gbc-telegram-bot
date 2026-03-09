"""Tests for mirror utility functions."""

from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.game_state import ChatConfig, ChatGameState
from src.utils.mirror_utils import broadcast_game_update, broadcast_text, get_leader_chat_id, is_media_only_mirror


# ---------------------------------------------------------------------------
# get_leader_chat_id
# ---------------------------------------------------------------------------

class TestGetLeaderChatId:
    def test_no_config_returns_self(self):
        with patch("src.utils.mirror_utils.state_manager") as mock_sm:
            mock_sm.load_chat_config.return_value = None
            assert get_leader_chat_id(100) == 100

    def test_config_without_mirrors_chat_id_returns_self(self):
        with patch("src.utils.mirror_utils.state_manager") as mock_sm:
            mock_sm.load_chat_config.return_value = ChatConfig(chat_id=100)
            assert get_leader_chat_id(100) == 100

    def test_config_with_mirrors_chat_id_returns_leader(self):
        with patch("src.utils.mirror_utils.state_manager") as mock_sm:
            mock_sm.load_chat_config.return_value = ChatConfig(chat_id=200, mirrors_chat_id=100)
            assert get_leader_chat_id(200) == 100

    def test_independent_chat_returns_self(self):
        with patch("src.utils.mirror_utils.state_manager") as mock_sm:
            mock_sm.load_chat_config.return_value = ChatConfig(chat_id=50, mirrors_chat_id=None)
            assert get_leader_chat_id(50) == 50


# ---------------------------------------------------------------------------
# is_media_only_mirror
# ---------------------------------------------------------------------------

class TestIsMediaOnlyMirror:
    def _make_config(self, chat_id, mirrors_chat_id=None, flag_value=None):
        flags = {}
        if flag_value is not None:
            flags["media_only_mirror"] = flag_value
        return ChatConfig(chat_id=chat_id, mirrors_chat_id=mirrors_chat_id, feature_flags=flags)

    def test_returns_false_for_leader_chat(self):
        config = self._make_config(10, mirrors_chat_id=None, flag_value=True)
        with patch("src.utils.mirror_utils.state_manager") as mock_sm:
            mock_sm.load_chat_config.return_value = config
            assert is_media_only_mirror(10) is False

    def test_returns_false_for_mirror_without_flag(self):
        config = self._make_config(20, mirrors_chat_id=10, flag_value=None)
        with patch("src.utils.mirror_utils.state_manager") as mock_sm:
            mock_sm.load_chat_config.return_value = config
            assert is_media_only_mirror(20) is False

    def test_returns_false_for_mirror_with_flag_disabled(self):
        config = self._make_config(20, mirrors_chat_id=10, flag_value=False)
        with patch("src.utils.mirror_utils.state_manager") as mock_sm:
            mock_sm.load_chat_config.return_value = config
            assert is_media_only_mirror(20) is False

    def test_returns_true_for_mirror_with_flag_enabled(self):
        config = self._make_config(20, mirrors_chat_id=10, flag_value=True)
        with patch("src.utils.mirror_utils.state_manager") as mock_sm:
            mock_sm.load_chat_config.return_value = config
            assert is_media_only_mirror(20) is True

    def test_returns_false_when_no_config(self):
        with patch("src.utils.mirror_utils.state_manager") as mock_sm:
            mock_sm.load_chat_config.return_value = None
            assert is_media_only_mirror(99) is False


# ---------------------------------------------------------------------------
# broadcast_game_update
# ---------------------------------------------------------------------------

def _make_mock_adapter(platform="telegram"):
    adapter = MagicMock()
    adapter.platform = platform
    adapter.preferred_animation_format = "animation"
    adapter.edit_game_message = AsyncMock(return_value="file_id_xyz")
    adapter.send_game_message = AsyncMock(return_value=999)
    adapter.build_game_keyboard = MagicMock(return_value=MagicMock())
    return adapter


@pytest.mark.asyncio
class TestBroadcastGameUpdate:
    async def test_broadcasts_to_leader_only_when_no_mirrors(self):
        leader_id = 10
        mock_adapter = _make_mock_adapter()
        leader_state = ChatGameState(chat_id=leader_id, message_id=50)
        leader_config = ChatConfig(chat_id=leader_id, platform="telegram")
        fake_buffer = BytesIO(b"fake_video_data")

        with (
            patch("src.utils.mirror_utils.state_manager") as mock_sm,
            patch("src.utils.mirror_utils.get_adapter", return_value=mock_adapter),
            patch("src.utils.mirror_utils.game_controller_manager"),
            patch("src.utils.mirror_utils.save_frames_as_mp4", return_value=fake_buffer),
        ):
            mock_sm.get_mirror_chat_ids.return_value = []
            mock_sm.get_or_create_chat_config.return_value = leader_config
            mock_sm.load_game_state.return_value = leader_state

            await broadcast_game_update(leader_id, "caption", [], 15, [])

        mock_adapter.edit_game_message.assert_called_once_with(
            leader_id, 50, "caption", mock_adapter.build_game_keyboard.return_value,
            fake_buffer, media_type="animation"
        )

    async def test_broadcasts_to_leader_and_mirrors(self):
        leader_id = 10
        mirror_id = 20
        mock_adapter = _make_mock_adapter()
        leader_state = ChatGameState(chat_id=leader_id, message_id=50)
        mirror_state = ChatGameState(chat_id=mirror_id, message_id=60)
        leader_config = ChatConfig(chat_id=leader_id, platform="telegram")
        mirror_config = ChatConfig(chat_id=mirror_id, platform="telegram")
        fake_buffer = BytesIO(b"fake_video_data")

        with (
            patch("src.utils.mirror_utils.state_manager") as mock_sm,
            patch("src.utils.mirror_utils.get_adapter", return_value=mock_adapter),
            patch("src.utils.mirror_utils.game_controller_manager"),
            patch("src.utils.mirror_utils.save_frames_as_mp4", return_value=fake_buffer),
        ):
            mock_sm.get_mirror_chat_ids.return_value = [mirror_id]
            mock_sm.get_or_create_chat_config.side_effect = lambda cid: (
                leader_config if cid == leader_id else mirror_config
            )
            mock_sm.load_game_state.side_effect = lambda cid: (
                leader_state if cid == leader_id else mirror_state
            )
            mock_sm.load_chat_config.return_value = None

            await broadcast_game_update(leader_id, "caption", [], 15, [])

        assert mock_adapter.edit_game_message.call_count == 2
        calls = {c.args[0] for c in mock_adapter.edit_game_message.call_args_list}
        assert leader_id in calls
        assert mirror_id in calls

    async def test_seeds_initial_message_when_no_state(self):
        leader_id = 10
        mirror_id = 20
        mock_adapter = _make_mock_adapter()
        leader_state = ChatGameState(chat_id=leader_id, message_id=50)
        leader_config = ChatConfig(chat_id=leader_id, platform="telegram")
        mirror_config = ChatConfig(chat_id=mirror_id, platform="telegram")
        fake_buffer = BytesIO(b"fake_video_data")

        mock_controller = MagicMock()
        mock_controller.is_initialized.return_value = True
        mock_controller.get_frame_as_png.return_value = BytesIO(b"png_data")

        with (
            patch("src.utils.mirror_utils.state_manager") as mock_sm,
            patch("src.utils.mirror_utils.get_adapter", return_value=mock_adapter),
            patch("src.utils.mirror_utils.game_controller_manager") as mock_gcm,
            patch("src.utils.mirror_utils.save_frames_as_mp4", return_value=fake_buffer),
        ):
            mock_sm.get_mirror_chat_ids.return_value = [mirror_id]
            mock_sm.get_or_create_chat_config.side_effect = lambda cid: (
                leader_config if cid == leader_id else mirror_config
            )
            # Leader has state, mirror has no state
            mock_sm.load_game_state.side_effect = lambda cid: (
                leader_state if cid == leader_id else None
            )
            mock_sm.load_chat_config.return_value = None
            mock_gcm.get_controller.return_value = mock_controller

            await broadcast_game_update(leader_id, "caption", [], 15, [])

        # Leader: edit, mirror: seed
        mock_adapter.edit_game_message.assert_called_once_with(
            leader_id, 50, "caption", mock_adapter.build_game_keyboard.return_value,
            fake_buffer, media_type="animation"
        )
        mock_adapter.send_game_message.assert_called_once()
        assert mock_adapter.send_game_message.call_args.args[0] == mirror_id

    async def test_no_adapter_skips_target(self):
        leader_id = 10
        leader_state = ChatGameState(chat_id=leader_id, message_id=50)
        leader_config = ChatConfig(chat_id=leader_id, platform="unknown_platform")
        media_buffer = BytesIO(b"fake_video_data")

        with (
            patch("src.utils.mirror_utils.state_manager") as mock_sm,
            patch("src.utils.mirror_utils.get_adapter", return_value=None),
            patch("src.utils.mirror_utils.game_controller_manager"),
        ):
            mock_sm.get_mirror_chat_ids.return_value = []
            mock_sm.get_or_create_chat_config.return_value = leader_config
            mock_sm.load_game_state.return_value = leader_state

            # Should not raise
            await broadcast_game_update(leader_id, "caption", media_buffer, "photo", [])

    async def test_skips_media_only_mirror_in_broadcast_game_update(self):
        leader_id = 10
        mirror_id = 20
        mock_adapter = _make_mock_adapter()
        leader_state = ChatGameState(chat_id=leader_id, message_id=50)
        leader_config = ChatConfig(chat_id=leader_id, platform="telegram")
        mirror_config = ChatConfig(
            chat_id=mirror_id,
            platform="telegram",
            mirrors_chat_id=leader_id,
            feature_flags={"media_only_mirror": True},
        )
        fake_buffer = BytesIO(b"fake_video_data")

        with (
            patch("src.utils.mirror_utils.state_manager") as mock_sm,
            patch("src.utils.mirror_utils.get_adapter", return_value=mock_adapter),
            patch("src.utils.mirror_utils.game_controller_manager"),
            patch("src.utils.mirror_utils.save_frames_as_mp4", return_value=fake_buffer),
            patch("src.utils.mirror_utils.is_media_only_mirror", side_effect=lambda cid: cid == mirror_id),
        ):
            mock_sm.get_mirror_chat_ids.return_value = [mirror_id]
            mock_sm.get_or_create_chat_config.side_effect = lambda cid: (
                leader_config if cid == leader_id else mirror_config
            )
            mock_sm.load_game_state.return_value = leader_state

            await broadcast_game_update(leader_id, "caption", [], 15, [])

        # Only leader should receive the update
        assert mock_adapter.edit_game_message.call_count == 1
        assert mock_adapter.edit_game_message.call_args.args[0] == leader_id

    async def test_file_id_saved_on_edit(self):
        leader_id = 10
        mock_adapter = _make_mock_adapter()
        mock_adapter.edit_game_message = AsyncMock(return_value="new_file_id")
        leader_state = ChatGameState(chat_id=leader_id, message_id=50)
        leader_config = ChatConfig(chat_id=leader_id, platform="telegram")
        fake_buffer = BytesIO(b"fake_video_data")

        with (
            patch("src.utils.mirror_utils.state_manager") as mock_sm,
            patch("src.utils.mirror_utils.get_adapter", return_value=mock_adapter),
            patch("src.utils.mirror_utils.game_controller_manager"),
            patch("src.utils.mirror_utils.save_frames_as_mp4", return_value=fake_buffer),
        ):
            mock_sm.get_mirror_chat_ids.return_value = []
            mock_sm.get_or_create_chat_config.return_value = leader_config
            mock_sm.load_game_state.return_value = leader_state

            await broadcast_game_update(leader_id, "caption", [], 15, [])

        mock_sm.save_game_state.assert_called_once()
        saved_state = mock_sm.save_game_state.call_args.args[0]
        assert saved_state.last_animation_file_id == "new_file_id"


# ---------------------------------------------------------------------------
# broadcast_text
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestBroadcastText:
    async def test_sends_to_leader_and_mirrors(self):
        leader_id = 10
        mirror_id = 20
        mock_adapter = _make_mock_adapter()

        with (
            patch("src.utils.mirror_utils.state_manager") as mock_sm,
            patch("src.utils.mirror_utils.get_adapter", return_value=mock_adapter),
        ):
            mock_sm.get_mirror_chat_ids.return_value = [mirror_id]
            mock_sm.get_or_create_chat_config.side_effect = lambda cid: ChatConfig(
                chat_id=cid, platform="telegram"
            )
            mock_sm.load_chat_config.return_value = None

            await broadcast_text(leader_id, "hello")

        assert mock_adapter.send_text.call_count == 2
        calls = {c.args[0] for c in mock_adapter.send_text.call_args_list}
        assert leader_id in calls
        assert mirror_id in calls

    async def test_sends_only_to_leader_when_no_mirrors(self):
        leader_id = 10
        mock_adapter = _make_mock_adapter()

        with (
            patch("src.utils.mirror_utils.state_manager") as mock_sm,
            patch("src.utils.mirror_utils.get_adapter", return_value=mock_adapter),
        ):
            mock_sm.get_mirror_chat_ids.return_value = []
            mock_sm.get_or_create_chat_config.return_value = ChatConfig(
                chat_id=leader_id, platform="telegram"
            )

            await broadcast_text(leader_id, "hello")

        mock_adapter.send_text.assert_called_once_with(leader_id, "hello")

    async def test_skips_chat_when_no_adapter(self):
        leader_id = 10
        with (
            patch("src.utils.mirror_utils.state_manager") as mock_sm,
            patch("src.utils.mirror_utils.get_adapter", return_value=None),
        ):
            mock_sm.get_mirror_chat_ids.return_value = []
            mock_sm.get_or_create_chat_config.return_value = ChatConfig(
                chat_id=leader_id, platform="unknown"
            )

            # Should not raise
            await broadcast_text(leader_id, "hello")

    async def test_skips_media_only_mirror_in_broadcast_text(self):
        leader_id = 10
        mirror_id = 20
        mock_adapter = _make_mock_adapter()

        with (
            patch("src.utils.mirror_utils.state_manager") as mock_sm,
            patch("src.utils.mirror_utils.get_adapter", return_value=mock_adapter),
            patch("src.utils.mirror_utils.is_media_only_mirror", side_effect=lambda cid: cid == mirror_id),
        ):
            mock_sm.get_mirror_chat_ids.return_value = [mirror_id]
            mock_sm.get_or_create_chat_config.side_effect = lambda cid: ChatConfig(
                chat_id=cid, platform="telegram"
            )

            await broadcast_text(leader_id, "hello")

        # Only leader receives the text
        mock_adapter.send_text.assert_called_once_with(leader_id, "hello")
