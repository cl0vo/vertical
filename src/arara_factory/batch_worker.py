from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .batch import BatchPlan, ensure_plan, format_timestamp, mark_completed, pending_segments
from .render import RenderOptions, _binary, probe_media, render_reels


class BatchRenderWorker(QThread):
    progressed = Signal(int, str)
    logged = Signal(str)
    completed = Signal(list, object)
    failed = Signal(str)

    ANALYSIS_SHARE = 15

    def __init__(
        self,
        source: Path,
        brainrot: Path,
        output: Path,
        limit: int,
        options: RenderOptions,
    ) -> None:
        super().__init__()
        self.source = source
        self.brainrot = brainrot
        self.output = output
        self.limit = limit
        self.options = options

    def run(self) -> None:
        try:
            ffmpeg = _binary('ffmpeg')
            ffprobe = _binary('ffprobe')
            if not ffmpeg or not ffprobe:
                raise RuntimeError('FFmpeg не найден внутри программы.')

            info = probe_media(ffprobe, self.source)

            def analysis_progress(value: int, text: str) -> None:
                mapped = min(self.ANALYSIS_SHARE, int(value * self.ANALYSIS_SHARE / 100))
                self.progressed.emit(mapped, text)

            plan = ensure_plan(
                ffmpeg,
                self.source,
                info.duration,
                analysis_progress,
            )
            todo = pending_segments(plan, self.limit)
            if not todo:
                self.progressed.emit(100, 'Все фрагменты уже готовы')
                self.completed.emit([], plan)
                return

            outputs: list[str] = []
            total = len(todo)
            render_share = 100 - self.ANALYSIS_SHARE

            for position, segment in enumerate(todo):
                base = self.ANALYSIS_SHARE + int(position * render_share / total)
                next_base = self.ANALYSIS_SHARE + int((position + 1) * render_share / total)
                span = max(1, next_base - base)
                human_time = format_timestamp(segment.start).replace('-', ':')
                self.progressed.emit(
                    base,
                    f'Ролик {position + 1} из {total} · исходник {human_time}',
                )

                def mapped_progress(value: int, text: str) -> None:
                    mapped = min(99, base + int(span * max(0, min(100, value)) / 100))
                    self.progressed.emit(
                        mapped,
                        f'Ролик {position + 1} из {total} · {text}',
                    )

                stem = (
                    f'{self.source.stem}_clip_{segment.index:04d}_'
                    f'{format_timestamp(segment.start)}'
                )
                render_options = RenderOptions(
                    variants=1,
                    subtitle_y=self.options.subtitle_y,
                    font=self.options.font,
                    seed=self.options.seed + segment.index,
                    encoder_preset=self.options.encoder_preset,
                    crf=self.options.crf,
                    encoder_mode=self.options.encoder_mode,
                    brainrot_zoom=self.options.brainrot_zoom,
                    subtitles_enabled=self.options.subtitles_enabled,
                    subtitle_mode='arara',
                    source_start=segment.start,
                    clip_duration=segment.duration,
                    output_stem=stem,
                    brainrot_x=self.options.brainrot_x,
                    brainrot_y=self.options.brainrot_y,
                    brainrot_width=self.options.brainrot_width,
                    brainrot_height=self.options.brainrot_height,
                )
                made = render_reels(
                    self.source,
                    self.brainrot,
                    self.output,
                    render_options,
                    mapped_progress,
                    self.logged.emit,
                )
                if not made:
                    raise RuntimeError(f'Не создан ролик №{segment.index}.')

                result = made[0]
                plan = mark_completed(self.source, segment.index, result)
                outputs.append(str(result))
                self.progressed.emit(
                    next_base,
                    f'Готово {position + 1} из {total} · прогресс сохранён',
                )
                self.logged.emit(
                    f'Готово и сохранено в прогрессе: #{segment.index} '
                    f'{segment.start:.2f}–{segment.end:.2f}'
                )

            self.progressed.emit(100, f'Порция готова · {len(outputs)} роликов')
            self.completed.emit(outputs, plan)
        except Exception:
            self.failed.emit(traceback.format_exc())
