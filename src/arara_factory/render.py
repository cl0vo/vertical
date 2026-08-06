from __future__ import annotations

import random
import shutil
import subprocess
import sys
import tempfile
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


def _run(cmd: list[str], log) -> None:
    log(' '.join(cmd))
    process = subprocess.run(cmd, text=True, capture_output=True)
    if process.returncode:
        raise RuntimeError((process.stderr or process.stdout)[-4000:])


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
        return [p for p in source.rglob('*') if p.suffix.lower() in VIDEO_EXTS]
    return []


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
    reel_duration = _probe_duration(ffprobe, source)
    rng = random.Random(options.seed)
    made: list[Path] = []

    with tempfile.TemporaryDirectory(prefix='arara_') as tmp:
        work = Path(tmp)
        wav = work / 'audio.wav'
        ass = work / 'captions.ass'
        overlay = work / 'hero_overlay.png'

        progress(3, 'Готовлю Hero-шаблон')
        build_hero_overlay(template, overlay)

        progress(7, 'Определяю ритм ARARA')
        extract_wav(ffmpeg, source, wav)
        pulses = detect_pulses(wav)
        if not pulses:
            raise RuntimeError('Не удалось определить фразы ARARA в аудио.')
        write_capcut_ass(pulses, ass, options.font, options.subtitle_y)
        ass_path = _escape_filter_path(ass)

        for variant in range(options.variants):
            progress(10 + int(86 * variant / max(1, options.variants)), f'Собираю вариант {variant + 1}')
            brainrot = rng.choice(clips)
            segment = choose_segment(ffprobe, brainrot, reel_duration, seed=options.seed + variant)
            out = output_dir / f'{source.stem}_hero_v{variant + 1}.mp4'

            graph = ';'.join([
                '[1:v]scale=1080:502:force_original_aspect_ratio=increase,crop=1080:502,setsar=1[brain]',
                'color=c=black:s=1080x1920:r=30[canvas]',
                '[canvas][brain]overlay=x=0:y=1410:shortest=1[withbrain]',
                '[0:v]scale=1056:635:force_original_aspect_ratio=increase,crop=1056:635,setsar=1[main]',
                '[withbrain][main]overlay=x=12:y=667:shortest=1[layout]',
                '[2:v]scale=1080:1920,format=rgba[frame]',
                '[layout][frame]overlay=0:0:format=auto[framed]',
                f"[framed]subtitles='{ass_path}'[vout]",
            ])

            cmd = [
                ffmpeg, '-y',
                '-i', str(source),
                '-ss', f'{segment.start:.3f}', '-t', f'{segment.duration:.3f}', '-i', str(brainrot),
                '-loop', '1', '-i', str(overlay),
                '-filter_complex', graph,
                '-map', '[vout]', '-map', '0:a?',
                '-c:v', 'libx264', '-preset', options.encoder_preset, '-crf', str(options.crf),
                '-c:a', 'aac', '-b:a', '160k',
                '-movflags', '+faststart', '-shortest', str(out),
            ]
            _run(cmd, log)
            made.append(out)

    progress(100, 'Готово')
    return made
