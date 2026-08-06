from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .audio import Pulse
from .transcribe import RecognizedWord

TOKENS = ('ARARA', 'RARA', 'RARARA', 'ARARARA')


@dataclass(frozen=True)
class CaptionGroup:
    words: tuple[RecognizedWord, ...]

    @property
    def start(self) -> float:
        return self.words[0].start

    @property
    def end(self) -> float:
        return self.words[-1].end


def ass_time(seconds: float) -> str:
    cs = max(0, int(round(seconds * 100)))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f'{h}:{m:02d}:{s:02d}.{cs:02d}'


def _ass_escape(text: str) -> str:
    return text.replace('\\', r'\\').replace('{', r'\{').replace('}', r'\}')


def group_words(
    words: list[RecognizedWord],
    *,
    max_words: int = 5,
    max_chars: int = 30,
    max_duration: float = 2.8,
    max_gap: float = 0.55,
) -> list[CaptionGroup]:
    groups: list[CaptionGroup] = []
    current: list[RecognizedWord] = []

    def flush() -> None:
        nonlocal current
        if current:
            groups.append(CaptionGroup(tuple(current)))
            current = []

    for word in words:
        if not current:
            current.append(word)
            continue
        candidate = [*current, word]
        text_length = sum(len(item.text) for item in candidate) + len(candidate) - 1
        duration = candidate[-1].end - candidate[0].start
        gap = word.start - current[-1].end
        if len(candidate) > max_words or text_length > max_chars or duration > max_duration or gap > max_gap:
            flush()
        current.append(word)
    flush()
    return groups


def _balanced_break(words: tuple[RecognizedWord, ...]) -> int | None:
    if len(words) < 4:
        return None
    best_index = None
    best_delta = None
    for index in range(1, len(words)):
        left = len(' '.join(word.text for word in words[:index]))
        right = len(' '.join(word.text for word in words[index:]))
        delta = abs(left - right)
        if best_delta is None or delta < best_delta:
            best_index = index
            best_delta = delta
    return best_index


def _caption_text(group: CaptionGroup, active_index: int) -> str:
    break_at = _balanced_break(group.words)
    parts: list[str] = []
    for index, item in enumerate(group.words):
        word = _ass_escape(item.text.upper())
        if index == active_index:
            word = rf'{{\c&H0035FF4D&\fs86}}{word}{{\c&H00FFFFFF&\fs78}}'
        parts.append(word)
    if break_at is None:
        return ' '.join(parts)
    return ' '.join(parts[:break_at]) + r'\N' + ' '.join(parts[break_at:])


def _header(font: str) -> str:
    return f'''[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Base,{font},78,&H00FFFFFF,&H004DFF35,&H00000000,&H50000000,-1,0,0,0,100,100,0,0,1,7,2,2,72,72,250,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''


def write_word_ass(
    words: list[RecognizedWord],
    target: Path,
    font: str = 'Arial Black',
    y: int = 1050,
) -> None:
    groups = group_words(words)
    lines: list[str] = []
    for group in groups:
        for index, word in enumerate(group.words):
            start = word.start
            if index + 1 < len(group.words):
                end = max(word.end, group.words[index + 1].start)
            else:
                end = max(word.end + 0.18, start + 0.18)
            text = _caption_text(group, index)
            tags = (
                rf'{{\an2\pos(540,{y})\bord7\shad2\fad(20,35)'
                rf'\fscx98\fscy98\t(0,75,\fscx103\fscy103)\t(75,145,\fscx100\fscy100)}}'
            )
            lines.append(
                f'Dialogue: 0,{ass_time(start)},{ass_time(end)},Base,,0,0,0,,{tags}{text}'
            )
    target.write_text(_header(font) + '\n'.join(lines) + '\n', encoding='utf-8-sig')


def arara_words_from_pulses(
    pulses: list[Pulse],
    pattern: tuple[str, ...] = TOKENS,
) -> list[RecognizedWord]:
    """Turn voice activity into timed ARARA words without speech recognition.

    The user's performance is intentionally made from brand syllables that normal
    Russian ASR often treats as unknown.  We therefore preserve the actual audio
    timing and cycle through the canonical visible tokens.
    """
    if not pattern:
        pattern = TOKENS
    words: list[RecognizedWord] = []
    for index, pulse in enumerate(pulses):
        start = max(0.0, float(pulse.start))
        end = max(start + 0.12, float(pulse.end))
        words.append(
            RecognizedWord(
                text=pattern[index % len(pattern)],
                start=start,
                end=end,
                confidence=1.0,
            )
        )
    return words


def token_for(pulse: Pulse, index: int) -> str:
    return TOKENS[index % len(TOKENS)]


def write_capcut_ass(pulses: list[Pulse], target: Path, font: str = 'Arial Black', y: int = 1050) -> None:
    write_word_ass(arara_words_from_pulses(pulses), target, font, y)
