from __future__ import annotations

import pytest

from arara_factory.geometry import canonical_layout
from arara_factory.render import output_duration
from arara_factory.subtitles import group_words
from arara_factory.transcribe import RecognizedWord


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


def test_recognized_words_are_grouped_into_short_capcut_lines() -> None:
    words = [
        RecognizedWord('это', 0.0, 0.3, 0.9),
        RecognizedWord('будет', 0.32, 0.7, 0.9),
        RecognizedWord('реальный', 0.72, 1.2, 0.9),
        RecognizedWord('тест', 1.22, 1.55, 0.9),
        RecognizedWord('программы', 1.58, 2.1, 0.9),
    ]
    groups = group_words(words)
    assert len(groups) == 1
    assert [word.text for word in groups[0].words] == ['это', 'будет', 'реальный', 'тест', 'программы']


def test_long_pause_starts_a_new_caption_group() -> None:
    words = [
        RecognizedWord('первая', 0.0, 0.3, 0.9),
        RecognizedWord('фраза', 0.35, 0.7, 0.9),
        RecognizedWord('вторая', 1.5, 1.8, 0.9),
    ]
    groups = group_words(words)
    assert len(groups) == 2
