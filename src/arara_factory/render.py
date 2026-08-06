from __future__ import annotations

import hashlib
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
from .subtitles import write_capcut_ass
from .template_mask import build_hero_overlay

VIDEO_EXTS = {'.mp4', '.mov', '.mkv', '.webm', '.avi'}


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
    open_safe_name: bool = True


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


def _probe_duration(ffprobe: str, path: Path) -> float:
    cmd = [ffprobe, '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', str(path)]
    process = subprocess.run(cmd, text=True, capture_output=True)
    if process.returncode:
        raise RuntimeError((process.stderr or process.stdout)[-2000:])
    return float(process.stdout.strip())


def _brainrot_files(source: Path) -> list[Path]:
    if source.is_file() and source.suffix.lower() in VIDEO_EXTS:
        return [source]
    if source.is_dir():
        return sorted(p for p in source.rglob('*') if p.suffix.lower() in VIDEO_EXTS)
    return []


def _app_root() -> Path:
    root = Path.home() / 'Videos' / 'ARARA Factory'
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cached_overlay(template: Path) -> Path:
    stat = template.stat()
    key = hashlib.sha256(f'{template.resolve()}|{stat.st_size}|{stat.st_mtime_ns}'.encode()).hexdigest()[:16]
    target = _app_root() / 'cache' / f'hero-overlay-{key}.png'
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        build_hero_overlay(template, target)
    return target


def _has_nvenc(ffmpeg: str) -> bool:
    try:
        process = subprocess.run([ffmpeg, '-hide_banner', '-encoders'], text=True, capture_output=True, timeout=15)
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
    label = 'preview' if preview else 'hero'
    base = output_dir / f'{source.stem}_{label}_v{variant}.mp4'
    if not base.exists():
        return base
    stamp = time.strftime('%H%M%S')
    return output_dir / f'{source.stem}_{label}_v{variant}_{stamp}.mp4'


def render_reels(
    source: Path,
    brainrot_source: Path,
    template: Path,
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
        raise RuntimeError('Не выбран готовый Reel.')
    if not template.is_file():
        raise RuntimeError('Не выбран PNG-шаблон ARARA.')

    clips = _brainrot_files(brainrot_source)
    if not clips:
        raise RuntimeError('Не выбран brainrot-файл или в папке нет видео.')

    output_dir.mkdir(parents=True, exist_ok=True)
    full_duration = _probe_duration(ffprobe, source)
    reel_duration = min(full_duration, options.preview_seconds) if options.preview_seconds else full_duration
    rng = random.Random(options.seed + int(time.time()))
    made: list[Path] = []

    progress(2, 'Загружаю сохранённый Hero-шаблон')
    overlay = _cached_overlay(template)

    with tempfile.TemporaryDirectory(prefix='arara_') as tmp:
        work = Path(tmp)
        wav = work / 'audio.wav'
        ass = work / 'captions.ass'

        progress(5, 'Определяю ритм ARARA')
        extract_wav(ffmpeg, source, wav)
        pulses = detect_pulses(wav)
        if options.preview_seconds:
            pulses = [pulse for pulse in pulses if pulse.start < reel_duration]
        if not pulses:
            raise RuntimeError('Не удалось определить фразы ARARA в аудио.')
        write_capcut_ass(pulses, ass, options.font, options.subtitle_y)
        ass_path = _escape_filter_path(ass)

        for variant in range(1, options.variants + 1):
            progress(10 + int(84 * (variant - 1) / max(1, options.variants)), f'Собираю вариант {variant}')
            brainrot = rng.choice(clips)
            segment = choose_segment(ffprobe, brainrot, reel_duration, seed=options.seed + variant + int(time.time()))
            out = _safe_output(output_dir, source, variant, bool(options.preview_seconds))

            graph = ';'.join([
                '[1:v]scale=1080:502:force_original_aspect_ratio=increase,crop=1080:502,setsar=1,fps=30[brain]',
                'color=c=black:s=1080x1920:r=30[canvas]',
                '[canvas][brain]overlay=x=0:y=1410:shortest=1[withbrain]',
                '[0:v]scale=1056:635:force_original_aspect_ratio=increase,crop=1056:635,setsar=1,fps=30[main]',
                '[withbrain][main]overlay=x=12:y=667:shortest=1[layout]',
                '[2:v]scale=1080:1920,format=rgba[frame]',
                '[layout][frame]overlay=0:0:format=auto[framed]',
                f"[framed]subtitles='{ass_path}'[vout]",
            ])

            base_cmd = [
                ffmpeg, '-y', '-hide_banner', '-loglevel', 'error',
                '-t', f'{reel_duration:.3f}', '-i', str(source),
                '-ss', f'{segment.start:.3f}', '-t', f'{segment.duration:.3f}', '-i', str(brainrot),
                '-loop', '1', '-t', f'{reel_duration:.3f}', '-i', str(overlay),
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
