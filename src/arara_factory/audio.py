from __future__ import annotations

import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class Pulse:
    start: float
    end: float
    strength: float


def extract_wav(
    ffmpeg: str,
    source: Path,
    target: Path,
    duration: float | None = None,
    start: float = 0.0,
) -> None:
    cmd = [ffmpeg, '-y', '-hide_banner', '-loglevel', 'error']
    if start > 0:
        cmd.extend(['-ss', f'{max(0.0, start):.3f}'])
    if duration is not None:
        cmd.extend(['-t', f'{max(0.1, duration):.3f}'])
    cmd.extend([
        '-i', str(source),
        '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le',
        str(target),
    ])
    process = subprocess.run(cmd, text=True, capture_output=True)
    if process.returncode:
        raise RuntimeError((process.stderr or process.stdout)[-2000:])


def detect_pulses(wav_path: Path, min_silence: float = 0.10) -> list[Pulse]:
    with wave.open(str(wav_path), 'rb') as wf:
        rate = wf.getframerate()
        data = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32)
    if data.size == 0:
        return []
    data /= max(1.0, np.max(np.abs(data)))
    frame = max(160, int(rate * 0.025))
    hop = max(80, int(rate * 0.010))
    rms = np.array([
        np.sqrt(np.mean(data[i:i + frame] ** 2) + 1e-8)
        for i in range(0, max(1, len(data) - frame), hop)
    ])
    if rms.size == 0:
        return []
    floor = float(np.percentile(rms, 35))
    peak = float(np.percentile(rms, 92))
    threshold = floor + max(0.025, (peak - floor) * 0.34)
    active = rms > threshold
    min_gap = max(1, int(min_silence / (hop / rate)))
    for i in range(1, len(active) - 1):
        if (
            not active[i]
            and active[max(0, i - min_gap):i].any()
            and active[i + 1:min(len(active), i + min_gap + 1)].any()
        ):
            active[i] = True
    pulses: list[Pulse] = []
    start = None
    for idx, on in enumerate(active):
        if on and start is None:
            start = idx
        if start is not None and (not on or idx == len(active) - 1):
            end = idx if not on else idx + 1
            duration = (end - start) * hop / rate
            if duration >= 0.09:
                segment = rms[start:end]
                pulses.append(Pulse(start * hop / rate, end * hop / rate, float(segment.max())))
            start = None
    return pulses
