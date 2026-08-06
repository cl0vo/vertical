from __future__ import annotations

import time
from pathlib import Path

VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm"}


def is_publishable_reel(path: Path) -> bool:
    name = path.name.lower()
    return (
        path.is_file()
        and path.suffix.lower() in VIDEO_SUFFIXES
        and ".part." not in name
        and "_preview_" not in name
    )


def discover_reels(
    folder: Path,
    *,
    recursive: bool = False,
    order: str = "name",
) -> list[Path]:
    if not folder.is_dir():
        return []
    iterator = folder.rglob("*") if recursive else folder.glob("*")
    files = [path.resolve() for path in iterator if is_publishable_reel(path)]

    if order == "created":
        key = lambda path: (path.stat().st_ctime_ns, path.name.lower())
    elif order == "modified":
        key = lambda path: (path.stat().st_mtime_ns, path.name.lower())
    else:
        key = lambda path: path.name.lower()
    return sorted(files, key=key)


def normalize_selected_reels(files: list[Path], *, order: str = "name") -> list[Path]:
    unique: dict[str, Path] = {}
    for file in files:
        path = file.expanduser().resolve()
        if is_publishable_reel(path):
            unique[str(path).lower()] = path
    values = list(unique.values())
    if order == "created":
        values.sort(key=lambda path: (path.stat().st_ctime_ns, path.name.lower()))
    elif order == "modified":
        values.sort(key=lambda path: (path.stat().st_mtime_ns, path.name.lower()))
    else:
        values.sort(key=lambda path: path.name.lower())
    return values


def effective_queue_start(
    existing_due_times: list[float],
    *,
    delay_minutes: int,
    interval_minutes: int,
    now: float | None = None,
) -> float:
    current = float(time.time() if now is None else now)
    requested = current + max(0, int(delay_minutes)) * 60
    unfinished = [float(value) for value in existing_due_times if value > 0]
    if not unfinished:
        return requested
    interval = max(15, int(interval_minutes)) * 60
    return max(requested, max(unfinished) + interval)
