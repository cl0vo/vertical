from __future__ import annotations

import pytest

from arara_factory.geometry import canonical_layout
from arara_factory.render import output_duration


def test_reel_duration_is_kept_inside_range() -> None:
    assert output_duration(9.0) == 9.0
    assert output_duration(12.4) == 12.4
    assert output_duration(15.0) == 15.0


def test_long_reel_is_trimmed_to_fifteen_seconds() -> None:
    assert output_duration(23.133333) == 15.0


def test_short_reel_is_rejected() -> None:
    with pytest.raises(RuntimeError):
        output_duration(8.5)


def test_preview_is_five_seconds_but_only_for_valid_reel() -> None:
    assert output_duration(12.0, 5.0) == 5.0
    with pytest.raises(RuntimeError):
        output_duration(7.0, 5.0)


def test_full_lower_third_geometry_for_1080x1920() -> None:
    _, brainrot = canonical_layout(1080, 1920)
    assert brainrot.x == 15
    assert brainrot.y == 1315
    assert brainrot.width == 1048
    assert brainrot.height == 589
