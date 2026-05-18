import pytest
from core.layout.grain import allowed_rotations


def test_mode_none_returns_all_360():
    result = allowed_rotations("none", fabric_grain_deg=0.0, piece_grainline_deg=90.0)
    assert result == list(range(360))


def test_mode_none_ignores_grainline():
    """grain_mode='none' ignores piece grainline regardless of value."""
    result = allowed_rotations("none", fabric_grain_deg=45.0, piece_grainline_deg=None)
    assert result == list(range(360))


def test_piece_without_grainline_always_free():
    """Any grain mode with piece_grainline_deg=None returns all 360 rotations."""
    for mode in ("single", "bi"):
        result = allowed_rotations(mode, fabric_grain_deg=0.0, piece_grainline_deg=None)
        assert result == list(range(360)), f"mode={mode} with None grainline should be free"


def test_single_aligns_grainline_with_fabric():
    """
    fabric_grain=0°, piece_grain=90° →
    target = (0 - 90) % 360 = 270°.
    Rotating piece 270° CW turns its 90° grainline to 0° (fabric grain).
    """
    result = allowed_rotations("single", fabric_grain_deg=0.0, piece_grainline_deg=90.0)
    assert result == [270.0]


def test_single_no_rotation_needed():
    """piece_grain == fabric_grain → target = 0°."""
    result = allowed_rotations("single", fabric_grain_deg=0.0, piece_grainline_deg=0.0)
    assert result == [0.0]


def test_bi_returns_target_and_180():
    """fabric=0°, piece_grain=90° → target=270° → bi returns [270°, 90°]."""
    result = allowed_rotations("bi", fabric_grain_deg=0.0, piece_grainline_deg=90.0)
    assert set(result) == {270.0, 90.0}


def test_bi_wraparound():
    """fabric=0°, piece_grain=270° → target=90° → bi returns [90°, 270°]."""
    result = allowed_rotations("bi", fabric_grain_deg=0.0, piece_grainline_deg=270.0)
    assert set(result) == {90.0, 270.0}


def test_single_45_degree_fabric():
    """fabric=45°, piece_grain=90° → target=(45-90)%360=315°."""
    result = allowed_rotations("single", fabric_grain_deg=45.0, piece_grainline_deg=90.0)
    assert result == [315.0]


def test_unknown_mode_raises():
    with pytest.raises(ValueError, match="Unknown grain_mode"):
        allowed_rotations("diagonal", fabric_grain_deg=0.0, piece_grainline_deg=0.0)
