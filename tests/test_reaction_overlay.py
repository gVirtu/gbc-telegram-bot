"""Tests for apply_reaction_overlay."""

import os
os.environ.setdefault("PYTEST_CURRENT_TEST", "1")

from pathlib import Path
import numpy as np
import pytest
from PIL import Image

from src.utils.frame_utils import apply_reaction_overlay


def _make_frames(n, h=288, w=320):
    """Make n solid-black game frames."""
    return [np.zeros((h, w, 3), dtype=np.uint8) for _ in range(n)]


def _make_asset_dir(tmp_path, color=(255, 0, 0)):
    """Create a temp asset dir with a solid red reaction_joy.png (RGBA)."""
    img = Image.new("RGBA", (64, 64), (*color, 255))
    img.save(tmp_path / "reaction_joy.png")
    return tmp_path


class TestApplyReactionOverlayEmpty:
    def test_empty_reactions_returns_frames_unchanged(self, tmp_path):
        frames = _make_frames(30)
        asset_dir = _make_asset_dir(tmp_path)
        result = apply_reaction_overlay(frames, [], capture_fps=15, asset_dir=asset_dir)
        for orig, res in zip(frames, result):
            assert np.array_equal(orig, res)

    def test_returns_same_number_of_frames(self, tmp_path):
        frames = _make_frames(30)
        asset_dir = _make_asset_dir(tmp_path)
        result = apply_reaction_overlay(frames, [{"user_name": "Alice", "reaction_type": "joy"}], capture_fps=15, asset_dir=asset_dir)
        assert len(result) == len(frames)


class TestApplyReactionOverlayTiming:
    def test_frame_before_animation_unchanged(self, tmp_path):
        """Frame 0 has scale=0 (phase_frame=0 → scale=0/4=0), so emoji invisible."""
        frames = _make_frames(30)
        asset_dir = _make_asset_dir(tmp_path)
        reactions = [{"user_name": "Alice", "reaction_type": "joy"}]
        result = apply_reaction_overlay(frames, reactions, capture_fps=15, asset_dir=asset_dir)
        # At frame 0, scale = 0.0 → emoji has zero size → frame unchanged
        assert np.array_equal(result[0], frames[0])

    def test_frame_during_hold_has_emoji(self, tmp_path):
        """Frame 10 (hold phase) should have the emoji composited on top-left."""
        frames = _make_frames(30)
        asset_dir = _make_asset_dir(tmp_path)
        reactions = [{"user_name": "Alice", "reaction_type": "joy"}]
        result = apply_reaction_overlay(frames, reactions, capture_fps=15, asset_dir=asset_dir)
        # Top-left slot (x=0..63, y=...) should differ from black during hold
        assert not np.array_equal(result[10], frames[10]), "Frame 10 should have emoji drawn"

    def test_animation_gone_after_25_frames(self, tmp_path):
        """After frame 24 the emoji is fully scaled down (invisible)."""
        frames = _make_frames(30)
        asset_dir = _make_asset_dir(tmp_path)
        reactions = [{"user_name": "Alice", "reaction_type": "joy"}]
        result = apply_reaction_overlay(frames, reactions, capture_fps=15, asset_dir=asset_dir)
        assert np.array_equal(result[25], frames[25]), "Frame 25 should be back to original"


class TestApplyReactionOverlayMultiWindow:
    def test_second_window_reactions_appear_at_frame_30(self, tmp_path):
        """With 60 frames and 4 reactions, reactions 0–2 appear in window 0,
        reaction 3 starts at frame 30 (window 1)."""
        frames = _make_frames(60)
        asset_dir = _make_asset_dir(tmp_path)
        reactions = [
            {"user_name": f"User{i}", "reaction_type": "joy"} for i in range(4)
        ]
        result = apply_reaction_overlay(frames, reactions, capture_fps=15, asset_dir=asset_dir)
        # Frame 35 (window 1, hold phase) should have emoji on top-left
        assert not np.array_equal(result[35], frames[35]), "Frame 35 should have window-1 emoji"

    def test_single_window_animation_only_shown_once(self, tmp_path):
        """With 30 frames and 1 reaction, second window does not exist."""
        frames = _make_frames(30)  # exactly 1 window
        asset_dir = _make_asset_dir(tmp_path)
        reactions = [{"user_name": "Alice", "reaction_type": "joy"}]
        result = apply_reaction_overlay(frames, reactions, capture_fps=15, asset_dir=asset_dir)
        assert len(result) == 30


class TestApplyReactionOverlayMissingAsset:
    def test_missing_asset_skips_gracefully(self, tmp_path):
        """No PNG in asset_dir → reaction skipped, frames returned unmodified."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        frames = _make_frames(30)
        reactions = [{"user_name": "Alice", "reaction_type": "joy"}]
        # Should not raise
        result = apply_reaction_overlay(frames, reactions, capture_fps=15, asset_dir=empty_dir)
        assert len(result) == 30
