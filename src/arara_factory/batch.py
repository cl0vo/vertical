from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

MIN_SECONDS = 9.0
MAX_SECONDS = 15.0
TARGET_SECONDS = 12.0
STATE_VERSION = 1


@dataclass(frozen=True)
class BatchSegment:
    index: int
    start: float
    duration: float
    completed: bool = False
    output: str = ''

    @property
    def end(self) -> float:
        return self.start + self.duration


@dataclass(frozen=True)
class BatchPlan:
    source: str
    size: int
    mtime_ns: int
    duration: float
    segments: tuple[BatchSegment, ...]

    @property
    def completed_count(self) -> int:
        return sum(1 for segment in self.segments if segment.completed)

    @property
    def remaining_count(self) -> int:
        return len(self.segments) - self.completed_count

    @property
    def next_segment(self) -> BatchSegment | None:
        return next((segment for segment in self.segments if not segment.completed), None)


def _state_root() -> Path:
    local = os.environ.get('LOCALAPPDATA')
    base = Path(local) if local else Path.home() / 'AppData' / 'Local'
    root = base / 'ARARA Factory' / 'batch-progress'
    root.mkdir(parents=True, exist_ok=True)
    return root


def source_key(source: Path) -> str:
    resolved = str(source.resolve()).lower().encode('utf-8', errors='replace')
    return hashlib.sha256(resolved).hexdigest()[:24]


def state_path(source: Path) -> Path:
    return _state_root() / f'{source_key(source)}.json'


def _signature(source: Path) -> tuple[str, int, int]:
    stat = source.stat()
    return str(source.resolve()), int(stat.st_size), int(stat.st_mtime_ns)


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=path.stem + '-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        Path(temp_name).replace(path)
    finally:
        Path(temp_name).unlink(missing_ok=True)


def _plan_payload(plan: BatchPlan) -> dict:
    return {
        'version': STATE_VERSION,
        'source': plan.source,
        'size': plan.size,
        'mtime_ns': plan.mtime_ns,
        'duration': plan.duration,
        'segments': [asdict(segment) for segment in plan.segments],
    }


def save_plan(plan: BatchPlan) -> None:
    _atomic_write(state_path(Path(plan.source)), _plan_payload(plan))


def load_plan(source: Path) -> BatchPlan | None:
    path = state_path(source)
    if not path.is_file() or not source.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
        resolved, size, mtime_ns = _signature(source)
        if (
            int(payload.get('version', 0)) != STATE_VERSION
            or str(payload.get('source', '')) != resolved
            or int(payload.get('size', -1)) != size
            or int(payload.get('mtime_ns', -1)) != mtime_ns
        ):
            return None
        segments = tuple(
            BatchSegment(
                index=int(item['index']),
                start=float(item['start']),
                duration=float(item['duration']),
                completed=bool(item.get('completed', False)),
                output=str(item.get('output', '')),
            )
            for item in payload.get('segments') or []
        )
        return BatchPlan(
            source=resolved,
            size=size,
            mtime_ns=mtime_ns,
            duration=float(payload['duration']),
            segments=segments,
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def detect_silence_cut_points(ffmpeg: str, source: Path) -> list[float]:
    command = [
        ffmpeg,
        '-hide_banner', '-nostats', '-loglevel', 'info',
        '-i', str(source),
        '-vn', '-af', 'silencedetect=noise=-36dB:d=0.18',
        '-f', 'null', '-',
    ]
    process = subprocess.run(command, text=True, capture_output=True)
    text = process.stderr or process.stdout
    starts = [float(value) for value in re.findall(r'silence_start:\s*([0-9.]+)', text)]
    ends = [float(value) for value in re.findall(r'silence_end:\s*([0-9.]+)', text)]
    cuts: list[float] = []
    for start, end in zip(starts, ends):
        if end > start:
            cuts.append((start + end) / 2.0)
    return sorted(set(round(value, 3) for value in cuts if value >= 0))


def build_segments(
    duration: float,
    cut_points: list[float],
    minimum: float = MIN_SECONDS,
    maximum: float = MAX_SECONDS,
    target: float = TARGET_SECONDS,
) -> tuple[BatchSegment, ...]:
    duration = max(0.0, float(duration))
    cuts = sorted(value for value in cut_points if 0 < value < duration)
    segments: list[BatchSegment] = []
    start = 0.0

    while duration - start >= minimum - 0.01:
        remaining = duration - start
        if remaining <= maximum + 0.01:
            end = duration
        else:
            lower = start + minimum
            upper = min(start + maximum, duration)
            candidates = [
                value for value in cuts
                if lower <= value <= upper and (duration - value >= minimum - 0.01)
            ]
            if candidates:
                wanted = start + target
                end = min(candidates, key=lambda value: (abs(value - wanted), value))
            else:
                end = upper

        clip_duration = round(end - start, 3)
        if clip_duration < minimum - 0.05:
            break
        segments.append(
            BatchSegment(
                index=len(segments) + 1,
                start=round(start, 3),
                duration=min(maximum, clip_duration),
            )
        )
        start = round(end, 3)

    return tuple(segments)


def create_plan(ffmpeg: str, source: Path, duration: float) -> BatchPlan:
    if not source.is_file():
        raise FileNotFoundError(source)
    resolved, size, mtime_ns = _signature(source)
    cuts = detect_silence_cut_points(ffmpeg, source)
    segments = build_segments(duration, cuts)
    if not segments:
        raise RuntimeError('Не удалось найти ни одного отрезка длиной 9–15 секунд.')
    plan = BatchPlan(
        source=resolved,
        size=size,
        mtime_ns=mtime_ns,
        duration=float(duration),
        segments=segments,
    )
    save_plan(plan)
    return plan


def ensure_plan(ffmpeg: str, source: Path, duration: float) -> BatchPlan:
    return load_plan(source) or create_plan(ffmpeg, source, duration)


def pending_segments(plan: BatchPlan, limit: int) -> tuple[BatchSegment, ...]:
    pending = tuple(segment for segment in plan.segments if not segment.completed)
    if limit <= 0:
        return pending
    return pending[:limit]


def mark_completed(source: Path, segment_index: int, output: Path) -> BatchPlan:
    plan = load_plan(source)
    if plan is None:
        raise RuntimeError('Прогресс часовой записи не найден.')
    segments = tuple(
        BatchSegment(
            index=segment.index,
            start=segment.start,
            duration=segment.duration,
            completed=True if segment.index == segment_index else segment.completed,
            output=str(output) if segment.index == segment_index else segment.output,
        )
        for segment in plan.segments
    )
    updated = BatchPlan(
        source=plan.source,
        size=plan.size,
        mtime_ns=plan.mtime_ns,
        duration=plan.duration,
        segments=segments,
    )
    save_plan(updated)
    return updated


def reset_progress(source: Path) -> bool:
    path = state_path(source)
    if path.exists():
        path.unlink()
        return True
    return False


def format_timestamp(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f'{hours:02d}-{minutes:02d}-{secs:02d}'
