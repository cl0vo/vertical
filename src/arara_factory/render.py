from __future__ import annotations

import random
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .audio import detect_pulses, extract_wav
from .subtitles import write_capcut_ass
from .template_mask import build_hero_overlay

VIDEO_EXTS = {'.mp4', '.mov', '.mkv', '.webm', '.avi'}


@dataclass
class RenderOptions:
    variants: int = 3
    subtitle_y: int = 1120
    font: str = 'Arial Black'
    seed: int = 777


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


def render_reels(
    source: Path,
    brainrot_dir: Path,
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
    if not template.is_file():
        raise RuntimeError('Не выбран PNG-шаблон ARARA.')

    clips = [p for p in brainrot_dir.rglob('*') if p.suffix.lower() in VIDEO_EXTS]
    if not clips:
        raise RuntimeError('В папке brainrot нет видео.')

    output_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(options.seed)
    made: list[Path] = []

    with tempfile.TemporaryDirectory(prefix='arara_') as tmp:
        work = Path(tmp)
        wav = work / 'audio.wav'
        ass = work / 'captions.ass'
        overlay = work / 'hero_overlay.png'

        progress(4, 'Готовлю шаблон ARARA')
        build_hero_overlay(template, overlay)

        progress(8, 'Анализирую ритм голоса')
        extract_wav(ffmpeg, source, wav)
        pulses = detect_pulses(wav)
        if not pulses:
            raise RuntimeError('Не удалось определить фразы ARARA в аудио.')
        write_capcut_ass(pulses, ass, options.font, options.subtitle_y)

        for variant in range(options.variants):
            progress(12 + int(84 * variant / max(1, options.variants)), f'Собираю вариант {variant + 1}')
            brainrot = rng.choice(clips)
            start_offset = rng.uniform(0, 25)
            out = output_dir / f'{source.stem}_hero_v{variant + 1}.mp4'
            ass_path = _escape_filter_path(ass)

            # Layout on a 1080x1920 canvas:
            # central main content: x=12..1068, y=667..1302
            # full brainrot region: y=1410..1912
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
                '-ss', f'{start_offset:.3f}', '-stream_loop', '-1', '-i', str(brainrot),
                '-loop', '1', '-i', str(overlay),
                '-filter_complex', graph,
                '-map', '[vout]', '-map', '0:a?',
                '-c:v', 'libx264', '-preset', 'medium', '-crf', '18',
                '-c:a', 'aac', '-b:a', '192k',
                '-movflags', '+faststart', '-shortest', str(out),
            ]
            _run(cmd, log)
            made.append(out)

    progress(100, 'Готово')
    return made
