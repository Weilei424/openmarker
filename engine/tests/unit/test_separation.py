import os
import pytest
from core.models.piece import Piece, BoundingBox
from core.layout.separation import _resolve_sparrow_path


def _rect(piece_id: str, w: float, h: float, grainline: float | None = None) -> Piece:
    return Piece(
        id=piece_id, name=piece_id,
        polygon=[(0, 0), (w, 0), (w, h), (0, h)],
        area=w * h,
        bbox=BoundingBox(0, 0, w, h, w, h),
        is_valid=True,
        grainline_direction_deg=grainline,
    )


# --- _resolve_sparrow_path ---

def test_resolve_prefers_env_override(tmp_path, monkeypatch):
    fake = tmp_path / "sparrow.exe"
    fake.write_bytes(b"\x00")
    monkeypatch.setenv("OPENMARKER_SPARROW_PATH", str(fake))
    assert _resolve_sparrow_path() == str(fake)


def test_resolve_missing_raises(monkeypatch):
    monkeypatch.delenv("OPENMARKER_SPARROW_PATH", raising=False)
    monkeypatch.setattr(os.path, "isfile", lambda p: False)
    with pytest.raises(FileNotFoundError):
        _resolve_sparrow_path()
