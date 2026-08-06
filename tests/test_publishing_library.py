from __future__ import annotations

import os
from pathlib import Path

from arara_factory.publishing_library import (
    discover_reels,
    effective_queue_start,
    normalize_selected_reels,
)


def _file(path: Path, *, mtime: int | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"video")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def test_folder_picker_finds_only_finished_reels(tmp_path: Path) -> None:
    _file(tmp_path / "b.mp4")
    _file(tmp_path / "a.mov")
    _file(tmp_path / "clip_preview_v1.mp4")
    _file(tmp_path / "clip.part.mp4")
    _file(tmp_path / "notes.txt")
    _file(tmp_path / "nested" / "c.mp4")

    direct = discover_reels(tmp_path, recursive=False, order="name")
    assert [path.name for path in direct] == ["a.mov", "b.mp4"]

    recursive = discover_reels(tmp_path, recursive=True, order="name")
    assert [path.name for path in recursive] == ["a.mov", "b.mp4", "c.mp4"]


def test_selected_files_are_deduplicated_and_sorted(tmp_path: Path) -> None:
    later = _file(tmp_path / "later.mp4", mtime=200)
    earlier = _file(tmp_path / "earlier.mp4", mtime=100)
    selected = normalize_selected_reels(
        [later, earlier, later],
        order="modified",
    )
    assert selected == [earlier.resolve(), later.resolve()]


def test_start_delay_is_used_when_queue_is_empty() -> None:
    assert effective_queue_start(
        [],
        delay_minutes=90,
        interval_minutes=15,
        now=1_000,
    ) == 6_400


def test_new_files_never_overlap_existing_schedule() -> None:
    # Requested start is 30 minutes from now, but an existing Reel is already due
    # later. The new Reel must be placed one full interval after it.
    assert effective_queue_start(
        [5_000, 8_000],
        delay_minutes=30,
        interval_minutes=60,
        now=1_000,
    ) == 11_600


def test_requested_delay_wins_when_it_is_later_than_queue() -> None:
    assert effective_queue_start(
        [2_000],
        delay_minutes=180,
        interval_minutes=15,
        now=1_000,
    ) == 11_800
