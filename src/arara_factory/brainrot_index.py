from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from pathlib import Path

from .process_utils import run_hidden

INDEX_VERSION = 2


@dataclass(frozen=True)
class IndexedSegment:
    start: float
    duration: float
    index: int = -1


@dataclass(frozen=True)
class IndexInfo:
    total: int
    used: int
    remaining: int
    duration: float
    is_current: bool


def _fingerprint(path: Path) -> str:
    stat = path.stat()
    raw = f'{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}'.encode('utf-8')
    return hashlib.sha256(raw).hexdigest()[:20]


def _probe_duration(ffprobe: str, path: Path) -> float:
    cmd = [
        ffprobe,
        '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        str(path),
    ]
    process = run_hidden(cmd, text=True, capture_output=True)
    if process.returncode:
        raise RuntimeError((process.stderr or process.stdout)[-2000:])
    try:
        return float(process.stdout.strip())
    except ValueError as exc:
        raise RuntimeError('Не удалось определить длительность brainrot-видео.') from exc


def index_path(video: Path) -> Path:
    return video.with_suffix(video.suffix + '.arara-index.json')


def build_index(
    ffprobe: str,
    video: Path,
    *,
    target_segments: int = 600,
    min_clip: float = 9.0,
    max_clip: float = 15.0,
) -> Path:
    if not video.is_file():
        raise FileNotFoundError(video)
    duration = _probe_duration(ffprobe, video)
    if duration < max_clip:
        raise RuntimeError('Brainrot должен быть длиннее 15 секунд.')

    usable = max(0.0, duration - max_clip)
    count = max(1, min(target_segments, int(max(1.0, usable / 1.25))))
    step = usable / count if count else 0.0
    segments = []
    for index in range(count):
        start = min(max(0.0, index * step), max(0.0, duration - max_clip))
        available = max(min_clip, min(max_clip, duration - start))
        segments.append({'start': round(start, 3), 'duration': round(available, 3)})

    payload = {
        'version': INDEX_VERSION,
        'source': str(video.resolve()),
        'fingerprint': _fingerprint(video),
        'duration': round(duration, 3),
        'min_clip': min_clip,
        'max_clip': max_clip,
        'segments': segments,
        'used': [],
    }
    target = index_path(video)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return target


def load_or_build(ffprobe: str, video: Path, target_segments: int = 600) -> dict:
    target = index_path(video)
    if target.exists():
        try:
            payload = json.loads(target.read_text(encoding='utf-8'))
            if payload.get('version') == INDEX_VERSION and payload.get('fingerprint') == _fingerprint(video):
                return payload
        except (OSError, ValueError, TypeError):
            pass
    build_index(ffprobe, video, target_segments=target_segments)
    return json.loads(target.read_text(encoding='utf-8'))


def get_index_info(video: Path) -> IndexInfo | None:
    if not video.is_file():
        return None
    target = index_path(video)
    if not target.exists():
        return None
    try:
        payload = json.loads(target.read_text(encoding='utf-8'))
        segments = payload.get('segments') or []
        used = set(payload.get('used') or [])
        current = payload.get('version') == INDEX_VERSION and payload.get('fingerprint') == _fingerprint(video)
        return IndexInfo(
            total=len(segments),
            used=min(len(used), len(segments)),
            remaining=max(0, len(segments) - len(used)),
            duration=float(payload.get('duration') or 0.0),
            is_current=current,
        )
    except (OSError, ValueError, TypeError):
        return None


def reset_usage(video: Path) -> bool:
    target = index_path(video)
    if not target.exists():
        return False
    try:
        payload = json.loads(target.read_text(encoding='utf-8'))
        payload['used'] = []
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        return True
    except (OSError, ValueError, TypeError):
        return False


def choose_segment(
    ffprobe: str,
    video: Path,
    reel_duration: float,
    seed: int | None = None,
    *,
    mark_used: bool = True,
) -> IndexedSegment:
    if reel_duration < 1.0 or reel_duration > 15.05:
        raise RuntimeError(f'Недопустимая длина brainrot-фрагмента: {reel_duration:.1f} сек.')

    payload = load_or_build(ffprobe, video)
    segments = payload.get('segments') or []
    if not segments:
        raise RuntimeError('Индекс brainrot-видео пуст.')

    used = set(payload.get('used') or [])
    available = [index for index in range(len(segments)) if index not in used]
    if not available:
        used.clear()
        available = list(range(len(segments)))

    rng = random.Random(seed)
    selected = rng.choice(available)
    item = segments[selected]
    source_duration = float(payload.get('duration') or 0.0)
    wanted = max(1.0, reel_duration)
    start = min(float(item['start']), max(0.0, source_duration - wanted))

    if mark_used:
        used.add(selected)
        payload['used'] = sorted(used)
        index_path(video).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return IndexedSegment(start=start, duration=wanted, index=selected)


def mark_segment_used(video: Path, segment_index: int) -> bool:
    if segment_index < 0:
        return False
    target = index_path(video)
    if not target.exists():
        return False
    try:
        payload = json.loads(target.read_text(encoding='utf-8'))
        segments = payload.get('segments') or []
        if segment_index >= len(segments):
            return False
        used = set(payload.get('used') or [])
        used.add(int(segment_index))
        payload['used'] = sorted(used)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        return True
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
