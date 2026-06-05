"""Unit tests for the GA meta-heuristic driver. Uses stub evaluators
(no real BLF) so tests are deterministic and fast."""
import os
import pickle
import random
import sys

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from core.layout import ga
from core.models.piece import Piece, BoundingBox


def _p(piece_id: str, w: float = 100, h: float = 50) -> Piece:
    """Minimal Piece for stub-evaluator tests. id encodes the index."""
    return Piece(
        id=piece_id, name=piece_id,
        polygon=[(0, 0), (w, 0), (w, h), (0, h)],
        area=w * h,
        bbox=BoundingBox(0, 0, w, h, w, h),
        is_valid=True, validation_notes=[], grainline_direction_deg=0.0,
    )


def test_ga_module_exports_and_config_defaults():
    assert callable(ga.run_ga)
    assert hasattr(ga, "GAConfig")
    assert hasattr(ga, "GAResult")
    cfg = ga.GAConfig()
    assert cfg.population_size == ga.POPULATION_SIZE
    assert cfg.crossover_rate == ga.CROSSOVER_RATE
    assert cfg.mutation_rate == ga.MUTATION_RATE
    assert cfg.tournament_size == ga.TOURNAMENT_SIZE
    assert cfg.elitism_count == ga.ELITISM_COUNT
    assert cfg.no_grainline_rotation_cap == ga.NO_GRAINLINE_ROTATION_CAP
    assert cfg.mutation_move_weights == ga.MUTATION_MOVE_WEIGHTS
    # rotation_flip favored, matching SA's tuning win (spec section 5.4).
    assert cfg.mutation_move_weights["rotation_flip"] == 3.0
    # Sanity bounds.
    assert cfg.population_size >= 2
    assert 0.0 <= cfg.crossover_rate <= 1.0
    assert 0.0 <= cfg.mutation_rate <= 1.0
    assert cfg.tournament_size >= 2
    assert 0 <= cfg.elitism_count < cfg.population_size


def test_ga_config_picklable():
    """GAConfig must cross the ProcessPoolExecutor boundary (initargs)."""
    cfg = ga.GAConfig(population_size=12)
    restored = pickle.loads(pickle.dumps(cfg))
    assert restored.population_size == 12
    assert restored.mutation_move_weights == ga.MUTATION_MOVE_WEIGHTS
