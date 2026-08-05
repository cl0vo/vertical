from __future__ import annotations

from pathlib import Path
from .audio import Pulse

TOKENS = ('ARARA', 'RARA', 'RARARA', 'ARARARA')


def ass_time(seconds: float) -> str:
    cs = max(0, int(round(seconds * 100)))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f'{h}:{m:02d}:{s:02d}.{cs:02d}'


def token_for(pulse: Pulse, index: int) -> str:
    duration = pulse.end - pulse.start
    if duration > .62:
        return 'ARARARA'
    if duration > .43:
        return 'RARARA'
    if duration < .24:
        return 'RARA'
    return TOKENS[index % len(TOKENS)]


def write_capcut_ass(pulses: list[Pulse], target: Path, font: str = 'Arial Black', y: int = 1120) -> None:
    """Create the subtitle look measured from the supplied reference Reel.

    White heavy uppercase text, thick black outline, current token in neon green,
    two-line grouping and a short pop-in without camera zooms.
    """
    header = f'''[Script Info]
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
    lines: list[str] = []
    for i, pulse in enumerate(pulses):
        current = token_for(pulse, i)
        previous = token_for(pulses[i - 1], i - 1) if i else ''
        following = token_for(pulses[i + 1], i + 1) if i + 1 < len(pulses) else ''

        upper = ' '.join(item for item in (previous, current) if item)
        lower = following
        active = rf'{{\c&H0035FF4D&\fs86}}{current}{{\c&H00FFFFFF&\fs78}}'
        upper = upper.replace(current, active, 1)
        text = upper + (rf'\N{lower}' if lower else '')

        # Pop only the subtitle layer. No source-video zoom or movement.
        tags = rf'{{\an2\pos(540,{y})\bord7\shad2\fad(25,45)\fscx94\fscy94\t(0,95,\fscx104\fscy104)\t(95,170,\fscx100\fscy100)}}'
        end = max(pulse.end, pulse.start + .18)
        lines.append(f'Dialogue: 0,{ass_time(pulse.start)},{ass_time(end)},Base,,0,0,0,,{tags}{text}')

    target.write_text(header + '\n'.join(lines) + '\n', encoding='utf-8-sig')
