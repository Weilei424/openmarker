from __future__ import annotations


def allowed_rotations(
    grain_mode: str,
    fabric_grain_deg: float,
    piece_grainline_deg: float | None,
) -> list[float]:
    """
    Return the rotation angles (degrees, CW) the heuristic may try for one piece.

    grain_mode:
      'single' — piece grainline must align with fabric grain (one candidate)
      'bi'     — piece grainline may align or be 180° opposite (two candidates)

    If piece_grainline_deg is None (no grainline data in DXF), any mode returns
    all 360 candidates — no constraint without data.

    Phase 6: the 'none' (free rotation) mode was removed — production markers
    always honour grain. Pass 'single' for a fixed alignment.
    """
    if grain_mode not in ("single", "bi"):
        raise ValueError(f"Unknown grain_mode: {grain_mode!r}")

    if piece_grainline_deg is None:
        return list(range(360))

    target = (fabric_grain_deg - piece_grainline_deg) % 360

    if grain_mode == "single":
        return [target]
    # grain_mode == "bi"
    return [target, (target + 180) % 360]
