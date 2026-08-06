from __future__ import annotations

import json
from pathlib import Path

from arara_factory.brainrot_index import (
    INDEX_VERSION,
    _fingerprint,
    choose_segment,
    index_path,
    mark_segment_used,
)
from arara_factory.render import _partial_output, _progress_seconds


def test_partial_output_keeps_mp4_extension() -> None:
    final = Path('clip_ready_v1.mp4')
    partial = _partial_output(final)
    assert partial.name == 'clip_ready_v1.part.mp4'
    assert partial.suffix == '.mp4'


def test_ffmpeg_progress_parser_supports_both_formats() -> None:
    assert _progress_seconds('out_time_ms=12500000') == 12.5
    assert _progress_seconds('out_time=00:01:02.500000') == 62.5
    assert _progress_seconds('progress=continue') is None


def test_brainrot_is_committed_only_after_success(tmp_path: Path) -> None:
    video = tmp_path / 'brainrot.mp4'
    video.write_bytes(b'fake-video-for-index-state')
    payload = {
        'version': INDEX_VERSION,
        'source': str(video.resolve()),
        'fingerprint': _fingerprint(video),
        'duration': 60.0,
        'min_clip': 9.0,
        'max_clip': 15.0,
        'segments': [
            {'start': 0.0, 'duration': 15.0},
            {'start': 15.0, 'duration': 15.0},
        ],
        'used': [],
    }
    index_path(video).write_text(json.dumps(payload), encoding='utf-8')

    selected = choose_segment(
        'ffprobe-not-needed',
        video,
        12.0,
        seed=7,
        mark_used=False,
    )
    before = json.loads(index_path(video).read_text(encoding='utf-8'))
    assert before['used'] == []

    mark_segment_used(video, selected.index)
    after = json.loads(index_path(video).read_text(encoding='utf-8'))
    assert after['used'] == [selected.index]
