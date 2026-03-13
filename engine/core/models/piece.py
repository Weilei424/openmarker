# Internal data models for pattern pieces.
# These are the canonical structures passed between parser, normalizer, API, and frontend.

from dataclasses import dataclass, field


@dataclass
class BoundingBox:
    min_x: float
    min_y: float
    max_x: float
    max_y: float
    width: float
    height: float


@dataclass
class Piece:
    id: str                                    # stable identifier, e.g. "piece_0"
    name: str                                  # layer name from DXF
    polygon: list[tuple[float, float]]         # exterior ring, origin-translated, closing point excluded
    area: float                                # mm²
    bbox: BoundingBox
    is_valid: bool                             # True if Shapely considers the geometry valid
    validation_notes: list[str] = field(default_factory=list)  # non-fatal warnings
