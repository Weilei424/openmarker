from __future__ import annotations


def allowed_rotations(
    grain_mode: str,
    fabric_grain_deg: float,
    piece_grainline_deg: float | None,
) -> list[float]:
    """
    Return the rotation angles (degrees, CW) the heuristic may try for one piece.

    grain_mode:
      'none'   — free rotation, all 360 candidates in 1° steps
      'single' — piece grainline must align with fabric grain (one candidate)
      'bi'     — piece grainline may align or be 180° opposite (two candidates)

    If piece_grainline_deg is None (no grainline data in DXF), any mode returns
    all 360 candidates — no constraint without data.
    """
    if grain_mode == "none" or piece_grainline_deg is None:
        return list(range(360))

    target = (fabric_grain_deg - piece_grainline_deg) % 360

    if grain_mode == "single":
        return [target]
    elif grain_mode == "bi":
        return [target, (target + 180) % 360]
    else:
        raise ValueError(f"Unknown grain_mode: {grain_mode!r}")
