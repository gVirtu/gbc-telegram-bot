"""Tests for game controller.

This module tests the PyBoy game controller including initialization,
frame capture, input injection, and save states.
"""

import pytest
import numpy as np
from io import BytesIO
from unittest.mock import MagicMock, PropertyMock, patch

from src.game import GameController, GameControllerManager, BUTTON_EVENTS
from src.models.game_state import GameButton


class TestButtonEvents:
    """Test button to event mapping."""

    def test_all_buttons_mapped(self):
        """Test that all GameButtons have event mappings (except meta-actions)."""
        # Meta-actions that don't correspond to physical GameBoy buttons
        meta_actions = {GameButton.WAIT, GameButton.SEQUENCE, GameButton.ENVIAR}

        for button in GameButton:
            if button in meta_actions:
                # Meta-actions should not be in BUTTON_EVENTS
                assert button not in BUTTON_EVENTS
            else:
                assert button in BUTTON_EVENTS, f"Button {button} not mapped"

    def test_wait_button_not_in_events(self):
        """Test that WAIT button is NOT in BUTTON_EVENTS."""
        assert GameButton.WAIT not in BUTTON_EVENTS

    def test_button_events_structure(self):
        """Test that button events are tuples of press/release."""
        for button, events in BUTTON_EVENTS.items():
            assert len(events) == 2, f"Button {button} should have press and release events"
            assert events[0] is not None  # Press event
            assert events[1] is not None  # Release event


class TestGameControllerInitialization:
    """Test GameController initialization."""
    
    @pytest.fixture
    def mock_rom_path(self, tmp_path):
        """Create a mock ROM file path."""
        rom_path = tmp_path / "test.gbc"
        rom_path.write_bytes(b"mock rom data")
        return rom_path
    
    def test_init_with_chat_id(self, mock_rom_path):
        """Test initialization with chat ID."""
        controller = GameController(123456, rom_path=mock_rom_path)
        
        assert controller.chat_id == 123456
        assert controller.rom_path == mock_rom_path
        assert not controller.is_initialized()
    
    def test_init_default_rom_path(self, tmp_path):
        """Test initialization uses default ROM path."""
        rom_path = tmp_path / "game.gbc"
        rom_path.write_bytes(b"rom data")
        
        # Create a mock settings object with required attributes
        mock_settings = MagicMock()
        mock_settings.rom_path = rom_path
        mock_settings.data_dir = tmp_path / "data"
        mock_settings.save_slots = 5
        
        with patch("src.game.settings", mock_settings):
            controller = GameController(123456)
            
            assert controller.rom_path == rom_path


class TestGameControllerMocked:
    """Test GameController with mocked PyBoy."""
    
    @pytest.fixture
    def mock_pyboy(self):
        """Create a mock PyBoy instance."""
        mock = MagicMock()

        # Return a valid 160x144 RGB frame
        mock_frame = np.zeros((144, 160, 3), dtype=np.uint8)

        # Mock screen.ndarray property (the new API)
        mock_screen = MagicMock()
        type(mock_screen).ndarray = PropertyMock(return_value=mock_frame)
        mock.screen = mock_screen

        return mock
    
    @pytest.fixture
    def controller(self, mock_pyboy, tmp_path):
        """Create a controller with mocked PyBoy."""
        rom_path = tmp_path / "test.gbc"
        rom_path.write_bytes(b"rom data")
        
        controller = GameController(123456, rom_path=rom_path)
        controller.pyboy = mock_pyboy
        controller._initialized = True
        
        return controller
    
    def test_is_initialized(self, controller):
        """Test is_initialized check."""
        assert controller.is_initialized() is True
    
    def test_get_frame(self, controller, mock_pyboy):
        """Test frame capture."""
        frame = controller.get_frame()

        assert isinstance(frame, np.ndarray)
        assert frame.shape == (144, 160, 3)
        # Verify screen.ndarray was accessed
        assert mock_pyboy.screen.ndarray is not None
    
    def test_get_frame_not_initialized(self, controller):
        """Test frame capture when not initialized."""
        controller._initialized = False
        
        with pytest.raises(RuntimeError, match="Emulator not initialized"):
            controller.get_frame()
    
    def test_tick(self, controller, mock_pyboy):
        """Test ticking the emulator."""
        controller.tick(frames=5)
        
        assert mock_pyboy.tick.call_count == 5
    
    def test_send_input(self, controller, mock_pyboy):
        """Test sending button input."""
        frame = controller.send_input(GameButton.A, frames=10)
        
        # Should press, tick 10 times, release, tick once more
        assert mock_pyboy.send_input.call_count == 2  # Press + release
        assert mock_pyboy.tick.call_count == 11  # 10 hold + 1 release
        assert isinstance(frame, np.ndarray)
    
    def test_send_input_invalid_button(self, controller):
        """Test sending invalid button."""
        with pytest.raises(ValueError, match="Invalid button"):
            controller.send_input("invalid_button", frames=10)
    
    def test_save_state(self, controller, mock_pyboy):
        """Test saving state."""
        # Mock save_state to write to buffer
        def mock_save(buffer):
            buffer.write(b"saved state data")
        
        mock_pyboy.save_state = mock_save
        
        state_data = controller.save_state()
        
        assert state_data == b"saved state data"
    
    def test_load_state(self, controller, mock_pyboy):
        """Test loading state."""
        state_data = b"test state data"
        controller.load_state(state_data)
        
        mock_pyboy.load_state.assert_called_once()
        # Check that BytesIO was passed
        call_args = mock_pyboy.load_state.call_args[0][0]
        assert isinstance(call_args, BytesIO)
        assert call_args.read() == state_data
    
    def test_stop(self, controller, mock_pyboy):
        """Test stopping the emulator."""
        controller.stop()
        
        mock_pyboy.stop.assert_called_once()
        assert not controller.is_initialized()
    
    def test_context_manager(self, mock_pyboy, tmp_path):
        """Test context manager."""
        rom_path = tmp_path / "test.gbc"
        rom_path.write_bytes(b"rom data")
        
        controller = GameController(123456, rom_path=rom_path)
        controller.pyboy = mock_pyboy
        controller._initialized = True
        
        with controller as c:
            assert c.is_initialized()
        
        mock_pyboy.stop.assert_called_once()


class TestGameControllerManager:
    """Test GameControllerManager."""
    
    @pytest.fixture
    def manager(self):
        """Create a fresh manager."""
        return GameControllerManager()
    
    @pytest.fixture
    def mock_rom_path(self, tmp_path):
        """Create a mock ROM file."""
        rom_path = tmp_path / "test.gbc"
        rom_path.write_bytes(b"rom data")
        return rom_path
    
    @pytest.mark.asyncio
    async def test_get_or_create_controller(self, manager, mock_rom_path):
        """Test getting or creating controller."""
        # Create mock settings with required attributes
        mock_settings = MagicMock()
        mock_settings.rom_path = mock_rom_path
        mock_settings.data_dir = mock_rom_path.parent / "data"
        mock_settings.save_slots = 5
        save_dir = mock_rom_path.parent / "saves" / "123456"
        save_dir.mkdir(parents=True, exist_ok=True)
        mock_settings.get_chat_save_dir.return_value = save_dir
        
        with patch("src.game.settings", mock_settings):
            with patch("src.game.PyBoy") as mock_pyboy_class:
                mock_instance = MagicMock()
                mock_pyboy_class.return_value = mock_instance
                
                controller = await manager.get_or_create_controller(123456)
                
                assert controller.chat_id == 123456
                assert 123456 in manager._controllers
    
    def test_get_controller_existing(self, manager):
        """Test getting existing controller."""
        mock_controller = MagicMock()
        manager._controllers[123456] = mock_controller
        
        controller = manager.get_controller(123456)
        
        assert controller == mock_controller
    
    def test_get_controller_nonexistent(self, manager):
        """Test getting nonexistent controller."""
        controller = manager.get_controller(999999)
        
        assert controller is None
    
    def test_remove_controller(self, manager):
        """Test removing controller."""
        mock_controller = MagicMock()
        manager._controllers[123456] = mock_controller
        
        result = manager.remove_controller(123456)
        
        assert result is True
        assert 123456 not in manager._controllers
        mock_controller.stop.assert_called_once()
    
    def test_remove_nonexistent_controller(self, manager):
        """Test removing nonexistent controller."""
        result = manager.remove_controller(999999)
        
        assert result is False
    
    def test_stop_all(self, manager):
        """Test stopping all controllers."""
        mock1 = MagicMock()
        mock2 = MagicMock()
        manager._controllers[1] = mock1
        manager._controllers[2] = mock2
        
        manager.stop_all()
        
        mock1.stop.assert_called_once()
        mock2.stop.assert_called_once()
        assert len(manager._controllers) == 0


class TestGameControllerIntegration:
    """Integration tests for GameController."""
    
    @pytest.fixture
    def mock_rom_path(self, tmp_path):
        """Create a mock ROM file."""
        rom_path = tmp_path / "test.gbc"
        rom_path.write_bytes(b"ROM" * 1000)  # Make it big enough
        return rom_path
    
    @pytest.mark.asyncio
    async def test_full_lifecycle(self, mock_rom_path):
        """Test full controller lifecycle."""
        controller = GameController(123456, rom_path=mock_rom_path, sym_path=None)
        
        with patch("src.game.PyBoy") as mock_pyboy_class:
            # Setup mock
            mock_instance = MagicMock()
            mock_frame = np.zeros((144, 160, 3), dtype=np.uint8)
            mock_screen = MagicMock()
            type(mock_screen).ndarray = PropertyMock(return_value=mock_frame)
            mock_instance.screen = mock_screen
            mock_pyboy_class.return_value = mock_instance
            
            # Initialize
            await controller.initialize()
            assert controller.is_initialized()
            
            # Get frame
            frame = controller.get_frame()
            assert frame.shape == (144, 160, 3)
            
            # Send input
            frame = controller.send_input(GameButton.A, frames=5)
            assert isinstance(frame, np.ndarray)
            
            # Save and load state
            mock_buffer = BytesIO()
            def mock_save(buf):
                buf.write(b"test state")
            mock_instance.save_state = mock_save
            
            state = controller.save_state()
            assert state == b"test state"
            
            # Stop
            controller.stop()
            assert not controller.is_initialized()


class TestErrorHandling:
    """Test error handling."""
    
    def test_initialize_missing_rom(self, tmp_path):
        """Test initialization with missing ROM."""
        controller = GameController(123456, rom_path=tmp_path / "nonexistent.gbc")
        
        with pytest.raises(FileNotFoundError):
            # Can't use async/await in sync test, but the error happens before async
            import asyncio
            asyncio.run(controller.initialize())
    
    def test_uninitialized_operations(self, tmp_path):
        """Test operations on uninitialized controller."""
        rom_path = tmp_path / "test.gbc"
        rom_path.write_bytes(b"rom")
        
        controller = GameController(123456, rom_path=rom_path)
        
        with pytest.raises(RuntimeError, match="Emulator not initialized"):
            controller.get_frame()
        
        with pytest.raises(RuntimeError, match="Emulator not initialized"):
            controller.tick()
        
        with pytest.raises(RuntimeError, match="Emulator not initialized"):
            controller.send_input(GameButton.A, frames=10)


class TestFrameHashTracking:
    """Test frame hash tracking functionality."""
    
    @pytest.fixture
    def controller_with_mock(self, tmp_path):
        """Create controller with mocked PyBoy."""
        rom_path = tmp_path / "test.gbc"
        rom_path.write_bytes(b"rom")

        controller = GameController(123456, rom_path=rom_path)

        mock_pyboy = MagicMock()
        mock_frame = np.zeros((144, 160, 3), dtype=np.uint8)
        mock_screen = MagicMock()
        type(mock_screen).ndarray = PropertyMock(return_value=mock_frame)
        mock_pyboy.screen = mock_screen

        controller.pyboy = mock_pyboy
        controller._initialized = True

        return controller
    

class TestGetFrameAsPng:
    """Test PNG conversion integration."""
    
    @pytest.fixture
    def controller_with_mock(self, tmp_path):
        """Create controller with mocked PyBoy."""
        rom_path = tmp_path / "test.gbc"
        rom_path.write_bytes(b"rom")

        controller = GameController(123456, rom_path=rom_path)

        mock_pyboy = MagicMock()
        # Create a colorful frame
        mock_frame = np.zeros((144, 160, 3), dtype=np.uint8)
        mock_frame[:, :, 0] = 255  # Red
        mock_screen = MagicMock()
        type(mock_screen).ndarray = PropertyMock(return_value=mock_frame)
        mock_pyboy.screen = mock_screen

        controller.pyboy = mock_pyboy
        controller._initialized = True

        return controller
    
    def test_get_frame_as_png(self, controller_with_mock):
        """Test getting frame as PNG."""
        png_buffer = controller_with_mock.get_frame_as_png()
        
        assert isinstance(png_buffer, BytesIO)
        assert len(png_buffer.getvalue()) > 0
        
        # Verify it's valid PNG
        from PIL import Image
        png_buffer.seek(0)
        image = Image.open(png_buffer)
        assert image.format == "PNG"


class TestGameControllerManagerAutoLoad:
    """Test GameControllerManager auto_load parameter."""
    
    @pytest.fixture
    def manager(self):
        """Create a fresh manager."""
        return GameControllerManager()
    
    @pytest.fixture
    def mock_rom_path(self, tmp_path):
        """Create a mock ROM file."""
        rom_path = tmp_path / "test.gbc"
        rom_path.write_bytes(b"rom data")
        return rom_path
    
    @pytest.mark.asyncio
    async def test_get_or_create_controller_auto_load_true(self, manager, mock_rom_path):
        """Test get_or_create_controller with auto_load=True loads save states."""
        mock_settings = MagicMock()
        mock_settings.rom_path = mock_rom_path
        mock_settings.data_dir = mock_rom_path.parent / "data"
        mock_settings.save_slots = 5
        save_dir = mock_rom_path.parent / "saves" / "123456"
        save_dir.mkdir(parents=True, exist_ok=True)
        mock_settings.get_chat_save_dir.return_value = save_dir
        
        with patch("src.game.settings", mock_settings):
            with patch("src.game.PyBoy") as mock_pyboy_class:
                mock_instance = MagicMock()
                mock_instance.cartridge_title = "TEST"
                mock_pyboy_class.return_value = mock_instance
                
                with patch("src.game.state_manager") as mock_state_mgr:
                    # Set up auto-save slot
                    from src.models.game_state import SaveSlotInfo
                    mock_state_mgr.list_save_slots.return_value = [
                        SaveSlotInfo(slot_number=0, is_auto_save=True, created_at="2024-01-01", updated_at="2024-01-01")
                    ]
                    mock_state_mgr.load_from_slot.return_value = b"save_data"
                    
                    controller = await manager.get_or_create_controller(123456, auto_load=True)
                    
                    # Should try to load save state
                    mock_state_mgr.load_from_slot.assert_called_once_with(123456, 0)
                    mock_instance.load_state.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_or_create_controller_auto_load_false(self, manager, mock_rom_path):
        """Test get_or_create_controller with auto_load=False skips save loading."""
        mock_settings = MagicMock()
        mock_settings.rom_path = mock_rom_path
        mock_settings.data_dir = mock_rom_path.parent / "data"
        mock_settings.save_slots = 5
        save_dir = mock_rom_path.parent / "saves" / "123456"
        save_dir.mkdir(parents=True, exist_ok=True)
        mock_settings.get_chat_save_dir.return_value = save_dir
        
        with patch("src.game.settings", mock_settings):
            with patch("src.game.PyBoy") as mock_pyboy_class:
                mock_instance = MagicMock()
                mock_instance.cartridge_title = "TEST"
                mock_pyboy_class.return_value = mock_instance
                
                with patch("src.game.state_manager") as mock_state_mgr:
                    controller = await manager.get_or_create_controller(123456, auto_load=False)
                    
                    # Should NOT try to load save state
                    mock_state_mgr.load_from_slot.assert_not_called()
                    mock_instance.load_state.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_get_or_create_controller_auto_load_default(self, manager, mock_rom_path):
        """Test get_or_create_controller defaults to auto_load=True."""
        mock_settings = MagicMock()
        mock_settings.rom_path = mock_rom_path
        mock_settings.data_dir = mock_rom_path.parent / "data"
        mock_settings.save_slots = 5
        save_dir = mock_rom_path.parent / "saves" / "123456"
        save_dir.mkdir(parents=True, exist_ok=True)
        mock_settings.get_chat_save_dir.return_value = save_dir
        
        with patch("src.game.settings", mock_settings):
            with patch("src.game.PyBoy") as mock_pyboy_class:
                mock_instance = MagicMock()
                mock_instance.cartridge_title = "TEST"
                mock_pyboy_class.return_value = mock_instance
                
                with patch("src.game.state_manager") as mock_state_mgr:
                    from src.models.game_state import SaveSlotInfo
                    mock_state_mgr.list_save_slots.return_value = [
                        SaveSlotInfo(slot_number=1, is_auto_save=False, created_at="2024-01-01")
                    ]
                    mock_state_mgr.load_from_slot.return_value = b"save_data"
                    
                    controller = await manager.get_or_create_controller(123456)
                    
                    # Should try to load save state (default behavior)
                    mock_state_mgr.list_save_slots.assert_called_once()


class TestFrameCapture:
    """Tests for the begin_capture/end_capture frame-sampling API."""

    @pytest.fixture
    def controller(self, tmp_path):
        """GameController with mocked PyBoy returning a unique frame per tick."""
        rom_path = tmp_path / "test.gbc"
        rom_path.write_bytes(b"rom")

        ctrl = GameController(123456, rom_path=rom_path)

        mock_pyboy = MagicMock()
        # Each call to screen.ndarray returns a fresh array with a unique fill value
        call_count = [0]

        def unique_frame(*args, **kwargs):
            call_count[0] += 1
            arr = np.full((144, 160, 3), call_count[0], dtype=np.uint8)
            return arr

        mock_screen = MagicMock()
        type(mock_screen).ndarray = PropertyMock(side_effect=unique_frame)
        mock_pyboy.screen = mock_screen

        ctrl.pyboy = mock_pyboy
        ctrl._initialized = True
        return ctrl

    def test_begin_capture_captures_t0(self, controller):
        """begin_capture() captures t=0 frame immediately, before any ticks."""
        controller.begin_capture(4)
        assert len(controller._frame_buffer) == 1

    def test_tick_captures_at_interval(self, controller):
        """After begin_capture(4) + 8 ticks, buffer has 3 entries (t=0, t=4, t=8)."""
        controller.begin_capture(4)
        controller.tick(8)
        assert len(controller._frame_buffer) == 3

    def test_tick_no_capture_between_intervals(self, controller):
        """After begin_capture(4) + 3 ticks, buffer still has only the t=0 entry."""
        controller.begin_capture(4)
        controller.tick(3)
        assert len(controller._frame_buffer) == 1

    def test_end_capture_alignment_full_interval(self, controller):
        """After 4 ticks with interval=4, end_capture() runs 4 extra ticks to reach the boundary."""
        controller.begin_capture(4)
        controller.tick(4)
        # tick_count == 4, remainder == 0 → extra_ticks == 4
        tick_before = controller.pyboy.tick.call_count
        controller.end_capture()
        extra = controller.pyboy.tick.call_count - tick_before
        assert extra == 4

    def test_end_capture_alignment_partial(self, controller):
        """After 6 ticks with interval=4, end_capture() runs 2 extra ticks (4 - 6%4 = 2)."""
        controller.begin_capture(4)
        controller.tick(6)
        # tick_count == 6, remainder == 2 → extra_ticks == 2
        tick_before = controller.pyboy.tick.call_count
        controller.end_capture()
        extra = controller.pyboy.tick.call_count - tick_before
        assert extra == 2

    def test_end_capture_returns_and_clears(self, controller):
        """end_capture() returns the captured frames and clears the internal buffer."""
        controller.begin_capture(4)
        controller.tick(8)
        assert len(controller._frame_buffer) == 3

        returned = controller.end_capture()

        assert len(returned) == 3
        assert controller._frame_buffer == []
        assert controller._capture_tick_count == 0

    def test_send_input_ticks_counted(self, controller):
        """Ticks inside send_input() are counted toward the capture interval."""
        # begin_capture(4); send_input A for 10 hold frames → tick(10) + tick(1) = 11 ticks
        # Expected frames: t=0 (begin_capture), t=4 (tick 4), t=8 (tick 8) → 3 entries
        controller.begin_capture(4)
        controller.send_input(GameButton.A, frames=10)
        assert len(controller._frame_buffer) == 3

    def test_send_input_with_modifier_ticks_counted(self, controller):
        """Ticks inside send_input_with_modifier() are counted toward the capture interval."""
        controller.begin_capture(4)
        controller.send_input_with_modifier(GameButton.UP, GameButton.B, frames=10)
        # same 11 ticks as send_input
        assert len(controller._frame_buffer) == 3


class TestAudioCapture:
    """Tests for audio capture via begin_capture/tick/end_capture."""

    @pytest.fixture
    def controller(self, tmp_path):
        """GameController with mocked PyBoy that provides audio data each tick."""
        rom_path = tmp_path / "test.gbc"
        rom_path.write_bytes(b"rom")

        ctrl = GameController(123456, rom_path=rom_path)

        mock_pyboy = MagicMock()

        # Frame mock (required for get_frame)
        mock_frame = np.zeros((144, 160, 3), dtype=np.uint8)
        mock_screen = MagicMock()
        type(mock_screen).ndarray = PropertyMock(return_value=mock_frame)
        mock_pyboy.screen = mock_screen

        # Audio mock: each tick returns a fresh (800, 2) int8 array
        tick_count = [0]

        def audio_ndarray(*args, **kwargs):
            tick_count[0] += 1
            return np.full((800, 2), tick_count[0], dtype=np.int8)

        mock_sound = MagicMock()
        type(mock_sound).ndarray = PropertyMock(side_effect=audio_ndarray)
        mock_pyboy.sound = mock_sound

        ctrl.pyboy = mock_pyboy
        ctrl._initialized = True
        return ctrl

    def test_no_audio_before_capture(self, controller):
        """get_last_captured_audio() returns empty list before any capture."""
        assert controller.get_last_captured_audio() == []

    def test_audio_buffer_empty_before_ticks(self, controller):
        """begin_capture resets audio buffer to empty (no audio at t=0)."""
        controller.begin_capture(4)
        assert controller._audio_buffer == []

    def test_audio_chunks_collected_each_tick(self, controller):
        """Each tick during capture appends one audio chunk."""
        controller.begin_capture(4)
        controller.tick(5)
        assert len(controller._audio_buffer) == 5

    def test_audio_chunks_are_copies(self, controller):
        """Audio chunks are independent copies, not references to the same object."""
        controller.begin_capture(1)
        controller.tick(2)
        chunks = controller._audio_buffer
        assert chunks[0] is not chunks[1]

    def test_end_capture_stores_audio(self, controller):
        """end_capture() stores collected audio in _last_captured_audio."""
        controller.begin_capture(4)
        controller.tick(4)
        controller.end_capture()

        audio = controller.get_last_captured_audio()
        assert len(audio) == 4

    def test_end_capture_clears_audio_buffer(self, controller):
        """end_capture() resets _audio_buffer to empty."""
        controller.begin_capture(4)
        controller.tick(4)
        controller.end_capture()
        assert controller._audio_buffer == []

    def test_audio_not_collected_outside_capture(self, controller):
        """Ticks outside a capture window do not fill _audio_buffer."""
        controller.tick(10)
        assert controller._audio_buffer == []

    def test_audio_chunk_shape(self, controller):
        """Each collected chunk has shape (800, 2) as returned by mock."""
        controller.begin_capture(1)
        controller.tick(3)
        for chunk in controller._audio_buffer:
            assert chunk.shape == (800, 2)
            assert chunk.dtype == np.int8

    def test_begin_capture_resets_previous_audio_buffer(self, controller):
        """A second begin_capture() resets the audio buffer."""
        controller.begin_capture(1)
        controller.tick(5)
        assert len(controller._audio_buffer) == 5

        # Start a new capture — buffer should reset
        controller._capturing = False  # simulate end of first capture
        controller.begin_capture(1)
        assert controller._audio_buffer == []
