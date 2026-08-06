from __future__ import annotations

from arara_factory.geometry import (
    DEFAULT_BRAINROT_TRANSFORM,
    NormalizedRect,
    clamp_normalized_rect,
    normalized_to_rect,
)


def test_default_scene_matches_lower_third_on_full_hd() -> None:
    rect = normalized_to_rect(DEFAULT_BRAINROT_TRANSFORM, 1080, 1920)
    assert 10 <= rect.x <= 20
    assert 1310 <= rect.y <= 1320
    assert 1040 <= rect.width <= 1055
    assert 585 <= rect.height <= 595


def test_custom_scene_scales_between_preview_and_render() -> None:
    transform = NormalizedRect(0.10, 0.55, 0.80, 0.35)
    small = normalized_to_rect(transform, 270, 480)
    full = normalized_to_rect(transform, 1080, 1920)
    assert (small.x, small.y, small.width, small.height) == (27, 264, 216, 168)
    assert (full.x, full.y, full.width, full.height) == (108, 1056, 864, 672)


def test_dragged_scene_cannot_leave_canvas() -> None:
    safe = clamp_normalized_rect(NormalizedRect(-0.5, 0.95, 1.8, 0.5))
    assert safe.x == 0.0
    assert safe.y == 0.5
    assert safe.width == 1.0
    assert safe.height == 0.5
