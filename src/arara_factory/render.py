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
from .geometry import REFERENCE_HEIGHT, REFERENCE_WIDTH, canonical_layout
from .subtitles import write_capcut_ass

VIDEO_EXTS = {'.mp4', '.mov', '.mkv', '.webm', '.avi'}


@dataclass(frozen=True)
class MediaInfo:
    width: int
    height: int
    duration: float
    fps: float


@dataclass
class RenderOptions:
    variants: int = 1
    subtitle_y: int = 1120
    font: str = 'Arial Black'
    seed: int = 777
    encoder_preset: str = 'veryfast'
    crf: int = 20
    encoder_mode: str = 'auto'  # auto | nvidia | cpu
    preview_seconds: float | None = None
    brainrot_zoom: float = 1.25


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
        '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height,r_frame_rate:format=duration',
        '-of', 'json',
        str(path),
    ]
    process = subprocess.run(cmd, text=True, capture_output=True)
    if process.returncode:
        raise RuntimeError((process.stderr or process.stdout)[-2000:])
    try:
        payload = json.loads(process.stdout)
        stream = payload['streams'][0]
        num, den = str(stream.get('r_frame_rate', '30/1')).split('/', 1)
        return MediaInfo(
            width=int(stream['width']),
            height=int(stream['height']),
            duration=float(payload['format']['duration']),
            fps=float(num) / max(float(den), 1.0),
        )
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError('Не удалось определить формат видео.') from exc


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


def _safe_output(output_dir: Path, source: Path, variant: int, preview: bool) -> Path:
    label = 'preview' if preview else 'ready'
    base = output_dir / f'{source.stem}_{label}_v{variant}.mp4'
    if not base.exists():
        return base
    stamp = time.strftime('%H%M%S')
    return output_dir / f'{source.stem}_{label}_v{variant}_{stamp}.mp4'


def _validate_reel_geometry(info: MediaInfo) -> None:
    expected = REFERENCE_WIDTH / REFERENCE_HEIGHT
    actual = info.width / info.height
    if abs(actual - expected) > 0.015:
        raise RuntimeError(f'Reel должен быть вертикальным 9:16. Получено {info.width}×{info.height}.')


def _even(value: float) -> int:
    return max(2, int(round(value / 2.0) * 2))


def _zoom_crop(info: MediaInfo, target_aspect: float, zoom: float) -> tuple[int, int, int, int]:
    """Return a centered subject-safe crop preserving the lower-zone aspect ratio.

    For the supplied 640×360 Car Falling source and the recommended 1.25× zoom,
    this resolves to x=64, y=36, width=512, height=288. Sampling throughout the
    hour showed that the car remains near the central road corridor in this crop.
    """
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


def render_reels(
    source: Path,
    brainrot_source: Path,
    template: Path,
    output_dir: Path,
    options: RenderOptions,
    progress=lambda n, s: None,
    log=lambda s: None,
) -> list[Path]:
    """Build the canonical ARARA composition.

    The source Reel fills the central window. The chosen brainrot segment covers
    the entire area below that window, including the former right ARARA panel.
    Only the outer gold border remains. The brainrot is zoomed around the central
    car/road corridor and is never stretched.
    """
    ffmpeg = _binary('ffmpeg')
    ffprobe = _binary('ffprobe')
    if not ffmpeg or not ffprobe:
        raise RuntimeError('FFmpeg не найден внутри программы.')
    if not source.is_file():
        raise RuntimeError('Не выбран готовый Reel.')
    if not template.is_file():
        raise RuntimeError('Не выбран PNG-шаблон ARARA.')

    clips = _brainrot_files(brainrot_source)
    if not clips:
        raise RuntimeError('Не выбран длинный brainrot-файл.')

    source_info = probe_media(ffprobe, source)
    _validate_reel_geometry(source_info)
    full_duration = source_info.duration
    reel_duration = min(full_duration, options.preview_seconds) if options.preview_seconds else full_duration
    main_rect, brain_rect = canonical_layout(source_info.width, source_info.height)

    log(
        f'Reel {source_info.width}×{source_info.height}; '
        f'главное окно x={main_rect.x} y={main_rect.y} w={main_rect.width} h={main_rect.height}; '
        f'нижний brainrot x={brain_rect.x} y={brain_rect.y} w={brain_rect.width} h={brain_rect.height}'
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(options.seed + int(time.time()))
    made: list[Path] = []

    with tempfile.TemporaryDirectory(prefix='arara_') as tmp:
        work = Path(tmp)
        wav = work / 'audio.wav'
        ass = work / 'captions.ass'

        progress(4, 'Готовлю субтитры')
        extract_wav(ffmpeg, source, wav)
        pulses = detect_pulses(wav)
        if options.preview_seconds:
            pulses = [pulse for pulse in pulses if pulse.start < reel_duration]
        if not pulses:
            raise RuntimeError('Не удалось определить речь в аудио Reel.')
        write_capcut_ass(pulses, ass, options.font, options.subtitle_y)
        ass_path = _escape_filter_path(ass)

        for variant in range(1, options.variants + 1):
            progress(10 + int(84 * (variant - 1) / max(1, options.variants)), f'Собираю вариант {variant}')
            brainrot = rng.choice(clips)
            brain_info = probe_media(ffprobe, brainrot)
            segment = choose_segment(
                ffprobe,
                brainrot,
                reel_duration,
                seed=options.seed + variant + int(time.time()),
            )
            out = _safe_output(output_dir, source, variant, bool(options.preview_seconds))
            crop_x, crop_y, crop_w, crop_h = _zoom_crop(
                brain_info,
                brain_rect.width / brain_rect.height,
                options.brainrot_zoom,
            )
            log(
                f'Brainrot {brain_info.width}×{brain_info.height}; '
                f'zoom {options.brainrot_zoom:.2f}×; crop x={crop_x} y={crop_y} w={crop_w} h={crop_h}'
            )

            graph = ';'.join([
                f'color=c=black:s={source_info.width}x{source_info.height}:r=30[canvas]',
                f'[0:v]scale={main_rect.width}:{main_rect.height}:force_original_aspect_ratio=increase,'
                f'crop={main_rect.width}:{main_rect.height},setsar=1,fps=30[main]',
                f'[canvas][main]overlay=x={main_rect.x}:y={main_rect.y}:shortest=1[withmain]',
                f'[2:v]scale={source_info.width}:{source_info.height},format=rgba[frame]',
                '[withmain][frame]overlay=0:0:format=auto[framed]',
                f'[1:v]crop={crop_w}:{crop_h}:{crop_x}:{crop_y},'
                f'scale={brain_rect.width}:{brain_rect.height}:flags=lanczos,setsar=1,fps=30[brain]',
                f'[framed][brain]overlay=x={brain_rect.x}:y={brain_rect.y}:shortest=1[layout]',
                f"[layout]subtitles='{ass_path}'[vout]",
            ])

            base_cmd = [
                ffmpeg, '-y', '-hide_banner', '-loglevel', 'error',
                '-t', f'{reel_duration:.3f}', '-i', str(source),
                '-ss', f'{segment.start:.3f}', '-t', f'{segment.duration:.3f}', '-i', str(brainrot),
                '-loop', '1', '-t', f'{reel_duration:.3f}', '-i', str(template),
                '-filter_complex', graph,
                '-map', '[vout]', '-map', '0:a?',
            ]
            audio_args = ['-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', '-shortest', str(out)]
            encoder_args, encoder_name = _video_encoder_args(ffmpeg, options)
            log(f'Кодирование: {encoder_name}')

            try:
                _run([*base_cmd, *encoder_args, *audio_args], log)
            except RuntimeError as exc:
                if encoder_name != 'NVIDIA NVENC':
                    raise
                log(f'NVENC недоступен через текущий драйвер, повторяю на CPU: {exc}')
                cpu_args, _ = _video_encoder_args(ffmpeg, options, force_cpu=True)
                _run([*base_cmd, *cpu_args, *audio_args], log)

            made.append(out)

    progress(100, 'Готово')
    return made
