from __future__ import annotations

import json
import random
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .audio import detect_pulses, extract_wav
from .brainrot_index import choose_segment
from .geometry import (
    REFERENCE_HEIGHT,
    REFERENCE_WIDTH,
    NormalizedRect,
    normalized_to_rect,
)
from .scene_state import load_brainrot_transform
from .subtitles import arara_words_from_pulses, write_word_ass

VIDEO_EXTS = {'.mp4', '.mov', '.mkv', '.webm', '.avi'}
MIN_REEL_SECONDS = 9.0
MAX_REEL_SECONDS = 15.0


@dataclass(frozen=True)
class MediaInfo:
    width: int
    height: int
    duration: float
    fps: float
    has_audio: bool


@dataclass
class RenderOptions:
    variants: int = 1
    subtitle_y: int = 1050
    font: str = 'Arial Black'
    seed: int = 777
    encoder_preset: str = 'veryfast'
    crf: int = 20
    encoder_mode: str = 'auto'
    preview_seconds: float | None = None
    brainrot_zoom: float = 1.25
    subtitles_enabled: bool = True
    subtitle_mode: str = 'arara'
    source_start: float = 0.0
    clip_duration: float | None = None
    output_stem: str | None = None
    brainrot_x: float | None = None
    brainrot_y: float | None = None
    brainrot_width: float | None = None
    brainrot_height: float | None = None


def _run(cmd: list[str], log) -> subprocess.CompletedProcess[str]:
    log(' '.join(cmd))
    process = subprocess.run(cmd, text=True, capture_output=True)
    if process.returncode:
        raise RuntimeError((process.stderr or process.stdout)[-5000:])
    return process


def _escape_filter_path(path: Path) -> str:
    return str(path.resolve()).replace('\\', '/').replace(':', '\\:').replace("'", "\\'")


def _binary(name: str) -> str | None:
    bundled = Path(getattr(sys, '_MEIPASS', Path.cwd())) / (name + ('.exe' if sys.platform == 'win32' else ''))
    if bundled.exists():
        return str(bundled)
    return shutil.which(name)


def probe_media(ffprobe: str, path: Path) -> MediaInfo:
    cmd = [
        ffprobe,
        '-v', 'error',
        '-show_entries', 'stream=codec_type,width,height,r_frame_rate:format=duration',
        '-of', 'json',
        str(path),
    ]
    process = subprocess.run(cmd, text=True, capture_output=True)
    if process.returncode:
        raise RuntimeError((process.stderr or process.stdout)[-2000:])
    try:
        payload = json.loads(process.stdout)
        streams = payload.get('streams') or []
        video = next(stream for stream in streams if stream.get('codec_type') == 'video')
        rate = str(video.get('r_frame_rate') or '30/1')
        num, den = rate.split('/', 1)
        return MediaInfo(
            width=int(video['width']),
            height=int(video['height']),
            duration=float(payload['format']['duration']),
            fps=float(num) / max(float(den), 1.0),
            has_audio=any(stream.get('codec_type') == 'audio' for stream in streams),
        )
    except (KeyError, StopIteration, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError('Не удалось определить формат видео.') from exc


def output_duration(source_duration: float, preview_seconds: float | None = None) -> float:
    if source_duration < MIN_REEL_SECONDS - 0.05:
        raise RuntimeError(
            f'Reel слишком короткий: {source_duration:.1f} сек. Нужен ролик от 9 до 15 секунд.'
        )
    final_duration = min(source_duration, MAX_REEL_SECONDS)
    if preview_seconds is not None:
        return min(final_duration, max(1.0, float(preview_seconds)))
    return final_duration


def _brainrot_files(source: Path) -> list[Path]:
    if source.is_file() and source.suffix.lower() in VIDEO_EXTS:
        return [source]
    if source.is_dir():
        return sorted(path for path in source.rglob('*') if path.suffix.lower() in VIDEO_EXTS)
    return []


def _has_nvenc(ffmpeg: str) -> bool:
    try:
        process = subprocess.run(
            [ffmpeg, '-hide_banner', '-encoders'],
            text=True,
            capture_output=True,
            timeout=15,
        )
        return process.returncode == 0 and 'h264_nvenc' in process.stdout
    except (OSError, subprocess.SubprocessError):
        return False


def _video_encoder_args(ffmpeg: str, options: RenderOptions, force_cpu: bool = False) -> tuple[list[str], str]:
    use_nvenc = not force_cpu and options.encoder_mode in {'auto', 'nvidia'} and _has_nvenc(ffmpeg)
    if use_nvenc:
        return [
            '-c:v', 'h264_nvenc',
            '-preset', 'fast',
            '-rc', 'vbr',
            '-cq', str(max(16, min(30, options.crf))),
            '-b:v', '0',
            '-pix_fmt', 'yuv420p',
        ], 'NVIDIA NVENC'
    return [
        '-c:v', 'libx264',
        '-preset', options.encoder_preset,
        '-crf', str(options.crf),
        '-pix_fmt', 'yuv420p',
        '-threads', '0',
    ], 'CPU x264'


def _safe_output(
    output_dir: Path,
    source: Path,
    variant: int,
    preview: bool,
    output_stem: str | None = None,
) -> Path:
    label = 'preview' if preview else 'ready'
    stem = (output_stem or source.stem).strip() or source.stem
    base = output_dir / f'{stem}_{label}_v{variant}.mp4'
    if not base.exists():
        return base
    stamp = time.strftime('%H%M%S')
    return output_dir / f'{stem}_{label}_v{variant}_{stamp}.mp4'


def _validate_reel_format(info: MediaInfo) -> None:
    expected = REFERENCE_WIDTH / REFERENCE_HEIGHT
    actual = info.width / info.height
    if abs(actual - expected) > 0.015:
        raise RuntimeError(f'Reel должен быть вертикальным 9:16. Получено {info.width}×{info.height}.')
    if not info.has_audio:
        raise RuntimeError('В Reel нет аудиодорожки. Для субтитров и итогового звука нужен Reel со звуком.')


def _segment_timing(info: MediaInfo, options: RenderOptions) -> tuple[float, float]:
    start = max(0.0, float(options.source_start or 0.0))
    available = max(0.0, info.duration - start)
    if options.clip_duration is None:
        full_duration = output_duration(available)
    else:
        requested = min(MAX_REEL_SECONDS, float(options.clip_duration))
        if requested < MIN_REEL_SECONDS - 0.05:
            raise RuntimeError('Пакетный фрагмент должен быть длиной от 9 до 15 секунд.')
        full_duration = min(requested, available)
        if full_duration < MIN_REEL_SECONDS - 0.05:
            raise RuntimeError('В конце исходной записи осталось меньше 9 секунд.')
    duration = full_duration
    if options.preview_seconds is not None:
        duration = min(full_duration, max(1.0, float(options.preview_seconds)))
    return start, duration


def _brain_rect(info: MediaInfo, options: RenderOptions):
    if None in (
        options.brainrot_x,
        options.brainrot_y,
        options.brainrot_width,
        options.brainrot_height,
    ):
        normalized = load_brainrot_transform()
    else:
        normalized = NormalizedRect(
            float(options.brainrot_x),
            float(options.brainrot_y),
            float(options.brainrot_width),
            float(options.brainrot_height),
        )
    return normalized_to_rect(normalized, info.width, info.height)


def _even(value: float) -> int:
    return max(2, int(round(value / 2.0) * 2))


def _zoom_crop(info: MediaInfo, target_aspect: float, zoom: float) -> tuple[int, int, int, int]:
    zoom = max(1.0, min(1.5, float(zoom)))
    source_aspect = info.width / info.height
    if source_aspect >= target_aspect:
        base_h = info.height
        base_w = _even(base_h * target_aspect)
    else:
        base_w = info.width
        base_h = _even(base_w / target_aspect)

    crop_w = min(info.width, _even(base_w / zoom))
    crop_h = min(info.height, _even(crop_w / target_aspect))
    if crop_h > info.height:
        crop_h = min(info.height, _even(base_h / zoom))
        crop_w = min(info.width, _even(crop_h * target_aspect))

    x = max(0, (info.width - crop_w) // 2)
    y = max(0, (info.height - crop_h) // 2)
    return x, y, crop_w, crop_h


def _prepare_subtitles(
    ffmpeg: str,
    source: Path,
    work: Path,
    source_start: float,
    reel_duration: float,
    options: RenderOptions,
    progress,
    log,
) -> Path | None:
    wav = work / 'audio.wav'
    ass = work / 'captions.ass'
    progress(3, 'Извлекаю голос')
    extract_wav(ffmpeg, source, wav, duration=reel_duration, start=source_start)
    progress(6, 'Определяю тайминги ARARA по голосу')
    pulses = [pulse for pulse in detect_pulses(wav, min_silence=0.08) if pulse.start < reel_duration]
    words = arara_words_from_pulses(pulses)
    if not words:
        log('Голосовые фрагменты не найдены. Reel будет собран без субтитров, а не остановлен ошибкой.')
        return None
    log(f'ARARA Timing: найдено голосовых фрагментов — {len(words)}')
    write_word_ass(words, ass, options.font, options.subtitle_y)
    return ass


def render_reels(
    source: Path,
    brainrot_source: Path,
    output_dir: Path,
    options: RenderOptions,
    progress=lambda n, s: None,
    log=lambda s: None,
) -> list[Path]:
    ffmpeg = _binary('ffmpeg')
    ffprobe = _binary('ffprobe')
    if not ffmpeg or not ffprobe:
        raise RuntimeError('FFmpeg не найден внутри программы.')
    if not source.is_file():
        raise RuntimeError('Не выбран готовый Reel или длинная запись.')

    clips = _brainrot_files(brainrot_source)
    if not clips:
        raise RuntimeError('Не выбран длинный brainrot-файл.')

    source_info = probe_media(ffprobe, source)
    _validate_reel_format(source_info)
    source_start, reel_duration = _segment_timing(source_info, options)
    brain_rect = _brain_rect(source_info, options)

    if options.clip_duration is None and source_info.duration > MAX_REEL_SECONDS + 0.05 and not options.preview_seconds:
        log(f'Reel {source_info.duration:.1f} сек автоматически обрезан до 15.0 сек.')
    log(
        f'Reel {source_info.width}×{source_info.height} · исходник {source_start:.2f}–'
        f'{source_start + reel_duration:.2f} сек · итог {reel_duration:.2f} сек · '
        f'brainrot x={brain_rect.x} y={brain_rect.y} w={brain_rect.width} h={brain_rect.height}'
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(options.seed + time.time_ns())
    made: list[Path] = []

    with tempfile.TemporaryDirectory(prefix='arara_') as tmp:
        work = Path(tmp)
        subtitle_filter = ''
        subtitles_active = False

        if options.subtitles_enabled:
            ass = _prepare_subtitles(
                ffmpeg,
                source,
                work,
                source_start,
                reel_duration,
                options,
                progress,
                log,
            )
            if ass is not None:
                subtitles_active = True
                subtitle_filter = f";[layout]subtitles='{_escape_filter_path(ass)}'[vout]"

        for variant in range(1, options.variants + 1):
            progress(12 + int(82 * (variant - 1) / max(1, options.variants)), f'Собираю вариант {variant}')
            brainrot = rng.choice(clips)
            brain_info = probe_media(ffprobe, brainrot)
            if brain_info.duration < reel_duration:
                raise RuntimeError(
                    f'Brainrot короче итогового Reel: {brain_info.duration:.1f} сек. Нужен файл длиннее 15 сек.'
                )
            segment = choose_segment(
                ffprobe,
                brainrot,
                reel_duration,
                seed=options.seed + variant + time.time_ns(),
            )
            out = _safe_output(
                output_dir,
                source,
                variant,
                bool(options.preview_seconds),
                options.output_stem,
            )
            crop_x, crop_y, crop_w, crop_h = _zoom_crop(
                brain_info,
                brain_rect.width / brain_rect.height,
                options.brainrot_zoom,
            )
            log(
                f'Brainrot {brain_info.width}×{brain_info.height} · '
                f'{segment.start:.2f}–{segment.start + reel_duration:.2f} сек · '
                f'zoom {options.brainrot_zoom:.2f}× · crop {crop_w}×{crop_h}+{crop_x}+{crop_y}'
            )

            graph = ';'.join([
                '[0:v]fps=30,setsar=1,setpts=PTS-STARTPTS[base]',
                f'[1:v]crop={crop_w}:{crop_h}:{crop_x}:{crop_y},'
                f'scale={brain_rect.width}:{brain_rect.height}:flags=lanczos,'
                f'setsar=1,fps=30,setpts=PTS-STARTPTS[brain]',
                f'[base][brain]overlay=x={brain_rect.x}:y={brain_rect.y}:shortest=1[layout]',
            ])
            if subtitles_active:
                graph += subtitle_filter
                video_map = '[vout]'
            else:
                video_map = '[layout]'

            base_cmd = [ffmpeg, '-y', '-hide_banner', '-loglevel', 'error']
            if source_start > 0:
                base_cmd.extend(['-ss', f'{source_start:.3f}'])
            base_cmd.extend([
                '-t', f'{reel_duration:.3f}', '-i', str(source),
                '-ss', f'{segment.start:.3f}', '-t', f'{reel_duration:.3f}', '-i', str(brainrot),
                '-filter_complex', graph,
                '-map', video_map, '-map', '0:a?',
            ])
            audio_args = [
                '-af', 'asetpts=PTS-STARTPTS',
                '-c:a', 'aac', '-b:a', '160k',
                '-t', f'{reel_duration:.3f}',
                '-movflags', '+faststart', '-shortest', str(out),
            ]
            encoder_args, encoder_name = _video_encoder_args(ffmpeg, options)
            log(f'Кодирование: {encoder_name}')

            try:
                _run([*base_cmd, *encoder_args, *audio_args], log)
            except RuntimeError as exc:
                if encoder_name != 'NVIDIA NVENC':
                    raise
                log(f'NVENC недоступен, повторяю на CPU: {exc}')
                cpu_args, _ = _video_encoder_args(ffmpeg, options, force_cpu=True)
                _run([*base_cmd, *cpu_args, *audio_args], log)

            made.append(out)

    progress(100, 'Готово')
    return made
