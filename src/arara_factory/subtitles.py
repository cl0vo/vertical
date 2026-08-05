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
    d = pulse.end - pulse.start
    if d > .62: return 'ARARARA'
    if d > .43: return 'RARARA'
    if d < .24: return 'RARA'
    return TOKENS[index % len(TOKENS)]

def write_capcut_ass(pulses: list[Pulse], target: Path, font: str='Arial Black', y: int=1380) -> None:
    header = f'''[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\nStyle: Base,{font},82,&H00FFFFFF,&H0000FF00,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,8,2,2,80,80,360,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'''
    lines=[]
    for i,p in enumerate(pulses):
        token=token_for(p,i)
        prev=token_for(pulses[i-1],i-1) if i else ''
        nxt=token_for(pulses[i+1],i+1) if i+1<len(pulses) else ''
        row1=' '.join(x for x in (prev, token) if x)
        row2=nxt
        row1=row1.replace(token, r'{\c&H0000FF00&\fs92}'+token+r'{\c&H00FFFFFF&\fs82}')
        text=row1 + (r'\N'+row2 if row2 else '')
        tags=fr'{{\an2\pos(540,{y})\fad(35,55)\t(0,120,\fscx112\fscy112)\t(120,220,\fscx100\fscy100)}}'
        lines.append(f'Dialogue: 0,{ass_time(p.start)},{ass_time(max(p.end,p.start+.18))},Base,,0,0,0,,{tags}{text}')
    target.write_text(header+'\n'.join(lines)+'\n', encoding='utf-8-sig')
