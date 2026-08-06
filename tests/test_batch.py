from __future__ import annotations

from arara_factory.batch import BatchPlan, BatchSegment, build_segments, pending_segments


def test_hour_recording_is_split_into_9_to_15_second_reels() -> None:
    segments = build_segments(
        61.0,
        [10.5, 23.0, 35.4, 47.8],
    )
    assert len(segments) >= 4
    assert all(9.0 <= segment.duration <= 15.0 for segment in segments)
    assert segments[0].start == 0.0
    for previous, current in zip(segments, segments[1:]):
        assert abs(previous.end - current.start) < 0.01


def _sample_plan() -> BatchPlan:
    return BatchPlan(
        source='recording.mp4',
        size=1,
        mtime_ns=1,
        duration=40.0,
        segments=(
            BatchSegment(1, 0.0, 10.0, completed=True),
            BatchSegment(2, 10.0, 10.0),
            BatchSegment(3, 20.0, 10.0),
            BatchSegment(4, 30.0, 10.0),
        ),
    )


def test_first_batch_limit_skips_completed_segments() -> None:
    todo = pending_segments(_sample_plan(), 2)
    assert [segment.index for segment in todo] == [2, 3]


def test_zero_limit_means_all_remaining_without_duplicates() -> None:
    todo = pending_segments(_sample_plan(), 0)
    assert [segment.index for segment in todo] == [2, 3, 4]


def test_tiny_tail_is_not_exported_as_invalid_reel() -> None:
    segments = build_segments(31.0, [10.0, 20.0])
    assert [segment.duration for segment in segments] == [10.0, 10.0, 11.0]

    segments_with_short_tail = build_segments(28.0, [10.0, 20.0])
    assert all(segment.duration >= 9.0 for segment in segments_with_short_tail)
