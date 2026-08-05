from __future__ import annotations

import random
import shutil
import sys
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .audio import detect_pulses, extract_wav
from .subtitles import write_capcut_ass

VIDEO_EXTS={'.mp4','.mov','.mkv','.webm','.avi'}

@dataclass
class RenderOptions:
    variants: int = 3
    cutaway_chance: float = .65
    min_cutaway: float = .45
    max_cutaway: float = 1.10
    subtitle_y: int = 1380
    font: str = 'Arial Black'
    seed: int = 777


def _run(cmd: list[str], log) -> None:
    log(' '.join(cmd))
    p=subprocess.run(cmd, text=True, capture_output=True)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout)[-3000:])


def _escape_filter_path(path: Path) -> str:
    return str(path.resolve()).replace('\\','/').replace(':','\\:').replace("'", "\\'")


def _binary(name: str) -> str | None:
    bundled = Path(getattr(sys, '_MEIPASS', Path.cwd())) / (name + ('.exe' if sys.platform == 'win32' else ''))
    if bundled.exists():
        return str(bundled)
    return shutil.which(name)


def render_reels(source: Path, brainrot_dir: Path, output_dir: Path, options: RenderOptions, progress=lambda n,s:None, log=lambda s:None) -> list[Path]:
    ffmpeg=_binary('ffmpeg')
    ffprobe=_binary('ffprobe')
    if not ffmpeg or not ffprobe:
        raise RuntimeError('FFmpeg не найден. Установи FFmpeg и добавь его в PATH.')
    output_dir.mkdir(parents=True,exist_ok=True)
    clips=[p for p in brainrot_dir.rglob('*') if p.suffix.lower() in VIDEO_EXTS]
    rng=random.Random(options.seed)
    made=[]
    with tempfile.TemporaryDirectory(prefix='arara_') as td:
        td=Path(td); wav=td/'audio.wav'; ass=td/'captions.ass'
        progress(5,'Извлекаю звук')
        extract_wav(ffmpeg,source,wav)
        pulses=detect_pulses(wav)
        if not pulses:
            raise RuntimeError('Не удалось найти голосовые импульсы ARARA в аудио.')
        write_capcut_ass(pulses,ass,options.font,options.subtitle_y)
        for variant in range(options.variants):
            progress(10+int(85*variant/max(1,options.variants)),f'Собираю вариант {variant+1}')
            out=output_dir/f'{source.stem}_arara_v{variant+1}.mp4'
            selected=[]
            for p in pulses[1:-1]:
                if clips and rng.random()<options.cutaway_chance and p.start>1.0:
                    selected.append((p.start,min(options.max_cutaway,max(options.min_cutaway,p.end-p.start+.25)),rng.choice(clips)))
            inputs=['-i',str(source)]
            for _,_,clip in selected: inputs += ['-stream_loop','-1','-i',str(clip)]
            chains=['[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[base]']
            current='base'
            for idx,(start,dur,_) in enumerate(selected,1):
                chains.append(f'[{idx}:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,trim=duration={dur:.3f},setpts=PTS-STARTPTS+{start:.3f}/TB[cut{idx}]')
                chains.append(f'[{current}][cut{idx}]overlay=enable=\'between(t,{start:.3f},{start+dur:.3f})\':shortest=1[m{idx}]')
                current=f'm{idx}'
            ass_path=_escape_filter_path(ass)
            chains.append(f'[{current}]subtitles=\'{ass_path}\'[vout]')
            cmd=[ffmpeg,'-y',*inputs,'-filter_complex',';'.join(chains),'-map','[vout]','-map','0:a?','-c:v','libx264','-preset','medium','-crf','18','-c:a','aac','-b:a','192k','-movflags','+faststart','-shortest',str(out)]
            _run(cmd,log); made.append(out)
    progress(100,'Готово')
    return made
