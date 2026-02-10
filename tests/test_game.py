"""Tests for game controller.

This module tests the PyBoy game controller including initialization,
frame capture, input injection, and save states.
"""

import pytest
import numpy as np
from pathlib import Path
from io import BytesIO
from unittest.mock import MagicMock, PropertyMock, patch, mock_open

from src.game import GameController, GameControllerManager, BUTTON_EVENTS
from src.models.game_state import GameButton


class TestButtonEvents:
    """Test button to event mapping."""

    def test_all_buttons_mapped(self):
        """Test that all GameButtons have event mappings (except meta-actions)."""
        # Meta-actions that don't correspond to physical GameBoy buttons
        meta_actions = {GameButton.WAIT, GameButton.SEQUENCE, GameButton.ENVIAR, GameButton.RUN}

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
        frame = controller.tick(frames=5)
        
        assert mock_pyboy.tick.call_count == 5
        assert isinstance(frame, np.ndarray)
    
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
    
    def test_should_update_frame_first_frame(self, controller):
        """Test first frame always updates."""
        frame = np.zeros((144, 160, 3), dtype=np.uint8)
        
        should_update, frame_hash = controller.should_update_frame(frame)
        
        assert should_update is True
        assert len(frame_hash) == 64  # SHA256 hex
    
    def test_should_update_frame_same_frame(self, controller):
        """Test same frame doesn't update."""
        frame = np.zeros((144, 160, 3), dtype=np.uint8)
        
        # First call
        should_update, frame_hash = controller.should_update_frame(frame)
        controller.update_frame_hash(frame_hash)
        
        # Second call with same frame
        should_update, new_hash = controller.should_update_frame(frame)
        
        assert should_update is False
        assert new_hash == frame_hash
    
    def test_should_update_frame_different_frame(self, controller):
        """Test different frame updates."""
        frame1 = np.zeros((144, 160, 3), dtype=np.uint8)
        frame2 = np.ones((144, 160, 3), dtype=np.uint8)
        
        # First call
        should_update, hash1 = controller.should_update_frame(frame1)
        controller.update_frame_hash(hash1)
        
        # Second call with different frame
        should_update, hash2 = controller.should_update_frame(frame2)
        
        assert should_update is True
        assert hash1 != hash2
    
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
        controller = GameController(123456, rom_path=mock_rom_path)
        
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
    
    def test_update_frame_hash(self, controller_with_mock):
        """Test updating frame hash."""
        assert controller_with_mock.last_frame_hash is None
        
        controller_with_mock.update_frame_hash("abc123")
        
        assert controller_with_mock.last_frame_hash == "abc123"
    
    def test_should_update_frame_without_argument(self, controller_with_mock):
        """Test should_update_frame capturing its own frame."""
        should_update, frame_hash = controller_with_mock.should_update_frame()
        
        assert should_update is True
        assert len(frame_hash) == 64


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
