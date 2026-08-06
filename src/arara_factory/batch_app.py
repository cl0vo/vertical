from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QSettings, QThread, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .batch import (
    BatchPlan,
    create_plan,
    ensure_plan,
    format_timestamp,
    load_plan,
    mark_completed,
    pending_segments,
    reset_progress,
)
from .preview import PreviewPanel
from .render import RenderOptions, _binary, probe_media, render_reels
from .version import __version__

VIDEO_EXTENSIONS = {'.mp4', '.mov', '.mkv', '.webm', '.avi'}


class DropEdit(QLineEdit):
    fileDropped = Signal(str)

    def __init__(self, placeholder: str = ''):
        super().__init__()
        self.setReadOnly(True)
        self.setAcceptDrops(True)
        self.setPlaceholderText(placeholder)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in VIDEO_EXTENSIONS:
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
                self.setText(str(path))
                self.fileDropped.emit(str(path))
                event.acceptProposedAction()
                return
        event.ignore()


class PlanWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, source: Path, rebuild: bool = False):
        super().__init__()
        self.source = source
        self.rebuild = rebuild

    def run(self) -> None:
        try:
            ffmpeg = _binary('ffmpeg')
            ffprobe = _binary('ffprobe')
            if not ffmpeg or not ffprobe:
                raise RuntimeError('FFmpeg не найден внутри программы.')
            info = probe_media(ffprobe, self.source)
            if self.rebuild:
                reset_progress(self.source)
                plan = create_plan(ffmpeg, self.source, info.duration)
            else:
                plan = ensure_plan(ffmpeg, self.source, info.duration)
            self.completed.emit(plan)
        except Exception:
            self.failed.emit(traceback.format_exc())


class BatchRenderWorker(QThread):
    progressed = Signal(int, str)
    logged = Signal(str)
    completed = Signal(list, object)
    failed = Signal(str)

    def __init__(
        self,
        source: Path,
        brainrot: Path,
        output: Path,
        limit: int,
        options: RenderOptions,
    ):
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
            plan = ensure_plan(ffmpeg, self.source, info.duration)
            todo = pending_segments(plan, self.limit)
            if not todo:
                self.completed.emit([], plan)
                return

            outputs: list[str] = []
            total = len(todo)
            for position, segment in enumerate(todo):
                base = int(position * 100 / total)
                span = max(1, int(100 / total))
                self.progressed.emit(
                    base,
                    f'Ролик {position + 1} из {total} · исходник {format_timestamp(segment.start)}',
                )

                def mapped_progress(value: int, text: str) -> None:
                    mapped = min(99, base + int(span * value / 100))
                    self.progressed.emit(mapped, f'{position + 1}/{total} · {text}')

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
                self.logged.emit(
                    f'Готово и сохранено в прогрессе: #{segment.index} '
                    f'{segment.start:.2f}–{segment.end:.2f}'
                )

            self.progressed.emit(100, 'Порция готова')
            self.completed.emit(outputs, plan)
        except Exception:
            self.failed.emit(traceback.format_exc())


class BatchWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings('ARARA', 'ARARA Factory')
        self.plan_worker: PlanWorker | None = None
        self.render_worker: BatchRenderWorker | None = None

        self.setWindowTitle(f'ARARA Factory {__version__} — часовая запись')
        self.resize(1260, 840)
        self.setMinimumSize(1020, 700)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel('ARARA FACTORY · ЧАСОВАЯ ЗАПИСЬ')
        title.setObjectName('title')
        version = QLabel(f'v{__version__} · RESUME MODE')
        version.setObjectName('version')
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(version)
        outer.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        outer.addWidget(splitter, 1)

        left = QWidget()
        left.setMaximumWidth(620)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 14, 0)
        left_layout.setSpacing(12)
        splitter.addWidget(left)

        preview_host = QWidget()
        preview_layout = QHBoxLayout(preview_host)
        preview_layout.addStretch(1)
        self.preview = PreviewPanel()
        preview_layout.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignCenter)
        preview_layout.addStretch(1)
        splitter.addWidget(preview_host)
        splitter.setSizes([590, 560])

        description = QLabel(
            'Одна длинная запись автоматически делится по паузам на Reel 9–15 секунд. '
            'После каждого готового файла прогресс сохраняется, поэтому повторов не будет.'
        )
        description.setObjectName('subtitle')
        description.setWordWrap(True)
        left_layout.addWidget(description)

        self.source_edit = self._file_row(
            left_layout,
            '1. ЧАСОВАЯ ЗАПИСЬ ARARA',
            'Перетащи вертикальную запись со звуком',
            self.choose_source,
        )
        self.source_edit.textChanged.connect(self.source_changed)

        self.brainrot_edit = self._file_row(
            left_layout,
            '2. ДЛИННЫЙ BRAINROT',
            'Часовой Car Falling или другой фон',
            self.choose_brainrot,
            str(self.settings.value('brainrot', '')),
        )

        output_frame = QFrame()
        output_frame.setObjectName('card')
        output_layout = QVBoxLayout(output_frame)
        output_layout.addWidget(QLabel('3. ПАПКА ГОТОВЫХ РОЛИКОВ', objectName='cardTitle'))
        output_row = QHBoxLayout()
        default_output = Path.home() / 'Videos' / 'ARARA Factory' / 'batch-renders'
        self.output_edit = QLineEdit(str(self.settings.value('batch_output', str(default_output))))
        choose_output = QPushButton('Выбрать')
        choose_output.setMaximumWidth(95)
        choose_output.clicked.connect(self.choose_output)
        output_row.addWidget(self.output_edit, 1)
        output_row.addWidget(choose_output)
        output_layout.addLayout(output_row)
        left_layout.addWidget(output_frame)

        batch_frame = QFrame()
        batch_frame.setObjectName('card')
        batch_layout = QVBoxLayout(batch_frame)
        batch_layout.addWidget(QLabel('4. ПЕРВАЯ / СЛЕДУЮЩАЯ ПОРЦИЯ', objectName='cardTitle'))
        batch_row = QHBoxLayout()
        batch_row.addWidget(QLabel('Сделать сейчас:'))
        self.limit = QSpinBox()
        self.limit.setRange(1, 500)
        self.limit.setValue(int(self.settings.value('batch_limit', 10)))
        self.limit.setSuffix(' роликов')
        self.limit.setMaximumWidth(150)
        self.all_remaining = QCheckBox('Все оставшиеся')
        self.all_remaining.toggled.connect(self.limit.setDisabled)
        batch_row.addWidget(self.limit)
        batch_row.addWidget(self.all_remaining)
        batch_row.addStretch(1)
        batch_layout.addLayout(batch_row)
        self.plan_status = QLabel('Выбери часовую запись')
        self.plan_status.setObjectName('planStatus')
        self.plan_status.setWordWrap(True)
        batch_layout.addWidget(self.plan_status)
        left_layout.addWidget(batch_frame)

        settings_frame = QFrame()
        settings_frame.setObjectName('card')
        settings_layout = QFormLayout(settings_frame)
        self.zoom = QDoubleSpinBox()
        self.zoom.setRange(1.0, 1.5)
        self.zoom.setSingleStep(0.05)
        self.zoom.setValue(float(self.settings.value('zoom', 1.25)))
        self.zoom.setSuffix('×')
        self.subtitle_y = QSpinBox()
        self.subtitle_y.setRange(850, 1250)
        self.subtitle_y.setValue(int(self.settings.value('subtitle_y', 1050)))
        self.subtitles = QCheckBox('CapCut-субтитры ARARA')
        self.subtitles.setChecked(self.settings.value('subtitles_enabled', True, type=bool))
        self.quality = QSpinBox()
        self.quality.setRange(16, 28)
        self.quality.setValue(int(self.settings.value('quality', 20)))
        settings_layout.addRow('Приближение машины', self.zoom)
        settings_layout.addRow('Высота субтитров', self.subtitle_y)
        settings_layout.addRow('', self.subtitles)
        settings_layout.addRow('Качество', self.quality)
        left_layout.addWidget(settings_frame)

        buttons = QHBoxLayout()
        self.analyze_button = QPushButton('ПЕРЕАНАЛИЗИРОВАТЬ')
        self.analyze_button.setMaximumWidth(185)
        self.analyze_button.clicked.connect(lambda: self.start_plan(rebuild=True))
        self.render_button = QPushButton('СОБРАТЬ СЛЕДУЮЩУЮ ПОРЦИЮ')
        self.render_button.setObjectName('generate')
        self.render_button.setMaximumWidth(315)
        self.render_button.clicked.connect(self.start_batch)
        buttons.addWidget(self.analyze_button)
        buttons.addWidget(self.render_button)
        buttons.addStretch(1)
        left_layout.addLayout(buttons)

        utility = QHBoxLayout()
        self.reset_button = QPushButton('Сбросить прогресс')
        self.reset_button.clicked.connect(self.reset_batch)
        self.open_button = QPushButton('Открыть готовые')
        self.open_button.clicked.connect(self.open_output)
        utility.addWidget(self.reset_button)
        utility.addWidget(self.open_button)
        utility.addStretch(1)
        left_layout.addLayout(utility)

        self.progress = QProgressBar()
        self.status = QLabel('Готово к работе')
        self.status.setObjectName('status')
        self.status.setWordWrap(True)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(130)
        left_layout.addWidget(self.progress)
        left_layout.addWidget(self.status)
        left_layout.addWidget(self.log)
        left_layout.addStretch(1)

        if self.brainrot_edit.text():
            self.settings.setValue('brainrot', self.brainrot_edit.text())

    def _file_row(
        self,
        parent: QVBoxLayout,
        title: str,
        hint: str,
        choose,
        saved: str = '',
    ) -> DropEdit:
        frame = QFrame()
        frame.setObjectName('card')
        layout = QVBoxLayout(frame)
        layout.addWidget(QLabel(title, objectName='cardTitle'))
        label = QLabel(hint)
        label.setObjectName('hint')
        layout.addWidget(label)
        row = QHBoxLayout()
        edit = DropEdit('Перетащи видео сюда')
        edit.setText(saved)
        edit.fileDropped.connect(edit.setText)
        button = QPushButton('Выбрать')
        button.setMaximumWidth(95)
        button.clicked.connect(choose)
        row.addWidget(edit, 1)
        row.addWidget(button)
        layout.addLayout(row)
        parent.addWidget(frame)
        return edit

    def choose_source(self) -> None:
        value = QFileDialog.getOpenFileName(
            self, 'Выбрать часовую запись', str(Path.home() / 'Videos'),
            'Видео (*.mp4 *.mov *.mkv *.webm *.avi)',
        )[0]
        if value:
            self.source_edit.setText(value)

    def choose_brainrot(self) -> None:
        value = QFileDialog.getOpenFileName(
            self, 'Выбрать длинный brainrot', str(Path.home() / 'Videos'),
            'Видео (*.mp4 *.mov *.mkv *.webm *.avi)',
        )[0]
        if value:
            self.brainrot_edit.setText(value)
            self.settings.setValue('brainrot', value)

    def choose_output(self) -> None:
        value = QFileDialog.getExistingDirectory(
            self, 'Папка готовых роликов', self.output_edit.text() or str(Path.home() / 'Videos')
        )
        if value:
            self.output_edit.setText(value)

    def source_changed(self, value: str) -> None:
        source = Path(value) if value else Path('__missing__')
        if not source.is_file():
            self.plan_status.setText('Выбери часовую запись')
            return
        self.preview.load_file(source, autoplay=False, title='часовая запись')
        plan = load_plan(source)
        if plan:
            self.show_plan(plan)
        else:
            self.plan_status.setText('Запись ещё не анализировалась · анализ выполнится перед сборкой')

    def show_plan(self, plan: BatchPlan) -> None:
        next_segment = plan.next_segment
        next_text = (
            f' · следующий {format_timestamp(next_segment.start)}'
            if next_segment is not None else ' · всё готово'
        )
        self.plan_status.setText(
            f'Готово {plan.completed_count} из {len(plan.segments)} · '
            f'осталось {plan.remaining_count}{next_text}'
        )

    def validate_paths(self) -> tuple[Path, Path, Path] | None:
        source = Path(self.source_edit.text())
        brainrot = Path(self.brainrot_edit.text())
        output = Path(self.output_edit.text())
        if not source.is_file() or not brainrot.is_file() or not self.output_edit.text().strip():
            QMessageBox.warning(self, 'Не хватает файлов', 'Выбери часовую запись, brainrot и папку результата.')
            return None
        ffprobe = _binary('ffprobe')
        if not ffprobe:
            QMessageBox.critical(self, 'Ошибка', 'FFprobe не найден внутри программы.')
            return None
        try:
            info = probe_media(ffprobe, source)
            if abs(info.width / info.height - 9 / 16) > 0.015:
                raise RuntimeError(f'Запись должна быть вертикальной 9:16, сейчас {info.width}×{info.height}.')
            if not info.has_audio:
                raise RuntimeError('В часовой записи нет звука.')
            brain = probe_media(ffprobe, brainrot)
            if brain.duration < 15:
                raise RuntimeError('Brainrot должен быть длиннее 15 секунд.')
        except Exception as exc:
            QMessageBox.critical(self, 'Проверь видео', str(exc))
            return None
        return source, brainrot, output

    def start_plan(self, rebuild: bool = False) -> None:
        paths = self.validate_paths()
        if not paths:
            return
        source, _, _ = paths
        self.set_busy(True)
        self.status.setText('Анализирую паузы в часовой записи…')
        self.plan_worker = PlanWorker(source, rebuild)
        self.plan_worker.completed.connect(self.plan_done)
        self.plan_worker.failed.connect(self.worker_failed)
        self.plan_worker.start()

    def plan_done(self, plan: BatchPlan) -> None:
        self.set_busy(False)
        self.show_plan(plan)
        self.status.setText(f'План готов: {len(plan.segments)} роликов по 9–15 секунд')

    def start_batch(self) -> None:
        paths = self.validate_paths()
        if not paths:
            return
        source, brainrot, output = paths
        output.mkdir(parents=True, exist_ok=True)
        self.settings.setValue('brainrot', str(brainrot))
        self.settings.setValue('batch_output', str(output))
        self.settings.setValue('batch_limit', self.limit.value())
        self.settings.setValue('zoom', self.zoom.value())
        self.settings.setValue('subtitle_y', self.subtitle_y.value())
        self.settings.setValue('subtitles_enabled', self.subtitles.isChecked())
        self.settings.setValue('quality', self.quality.value())
        self.settings.sync()

        limit = 0 if self.all_remaining.isChecked() else self.limit.value()
        options = RenderOptions(
            subtitle_y=self.subtitle_y.value(),
            font='Arial Black',
            encoder_mode='auto',
            encoder_preset='veryfast',
            crf=self.quality.value(),
            brainrot_zoom=self.zoom.value(),
            subtitles_enabled=self.subtitles.isChecked(),
        )
        self.set_busy(True)
        self.log.clear()
        self.progress.setValue(0)
        self.status.setText('Готовлю следующую порцию…')
        self.render_worker = BatchRenderWorker(source, brainrot, output, limit, options)
        self.render_worker.progressed.connect(self.on_progress)
        self.render_worker.logged.connect(self.log.append)
        self.render_worker.completed.connect(self.batch_done)
        self.render_worker.failed.connect(self.worker_failed)
        self.render_worker.start()

    def batch_done(self, files: list[str], plan: BatchPlan) -> None:
        self.set_busy(False)
        self.progress.setValue(100)
        self.show_plan(plan)
        if files:
            result = Path(files[-1])
            self.preview.load_file(result, autoplay=True, title='последний готовый Reel')
            self.status.setText(f'Порция готова: {len(files)} роликов · последний {result.name}')
        else:
            self.status.setText('Все фрагменты этой записи уже собраны')

    def worker_failed(self, error: str) -> None:
        self.set_busy(False)
        self.status.setText('Операция остановлена · прогресс готовых роликов сохранён')
        self.log.setPlainText(error)
        QMessageBox.critical(self, 'Ошибка', error.splitlines()[-1])

    def on_progress(self, value: int, text: str) -> None:
        self.progress.setValue(value)
        self.status.setText(text)

    def reset_batch(self) -> None:
        source = Path(self.source_edit.text())
        if not source.is_file():
            return
        answer = QMessageBox.question(
            self,
            'Сбросить прогресс?',
            'Программа забудет, какие отрезки уже были собраны. Готовые файлы не удалятся, но при новой сборке возможны дубли.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            reset_progress(source)
            self.plan_status.setText('Прогресс сброшен · запись будет проанализирована заново')

    def open_output(self) -> None:
        path = Path(self.output_edit.text())
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def set_busy(self, busy: bool) -> None:
        self.render_button.setDisabled(busy)
        self.analyze_button.setDisabled(busy)
        self.reset_button.setDisabled(busy)


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setApplicationName('ARARA Factory Batch')
    app.setOrganizationName('ARARA')
    app.setStyleSheet('''
QWidget { background: #0b0a0d; color: #f4ecdf; font-family: "Segoe UI"; font-size: 14px; }
QLabel#title { color: #e7ad43; font-size: 27px; font-weight: 900; }
QLabel#version { color: #8f806d; font-size: 12px; }
QLabel#subtitle, QLabel#hint { color: #aa9d8d; font-size: 12px; }
QLabel#cardTitle { color: #f1c36d; font-size: 16px; font-weight: 800; }
QLabel#planStatus { color: #80d786; font-weight: 700; }
QLabel#status { color: #dfc89f; font-weight: 650; }
QFrame#card { background: #151117; border: 1px solid #5d452b; border-radius: 12px; }
QFrame#previewPanel { background: #111014; border: 1px solid #4c3923; border-radius: 14px; }
QWidget#previewCanvas { background: #070609; border-radius: 10px; }
QLabel#previewTitle { color: #f1c36d; font-size: 15px; font-weight: 800; }
QLabel#previewSource, QLabel#previewTime { color: #8f806d; font-size: 11px; }
QLineEdit, QSpinBox, QDoubleSpinBox, QTextEdit {
 background: #0d0b0e; color: #f4ecdf; border: 1px solid #4e3b27; border-radius: 7px; padding: 7px;
}
QPushButton { background: #241b14; color: #eee3d3; border: 1px solid #6b4d29; border-radius: 8px; padding: 8px 12px; font-weight: 650; }
QPushButton:hover { border-color: #e7ad43; background: #2c2117; }
QPushButton:disabled { color: #655e56; border-color: #31291f; background: #151210; }
QPushButton#generate { background: #d99d37; color: #0b0804; border-color: #f1be63; font-size: 15px; font-weight: 900; min-height: 34px; }
QProgressBar { background: #0d0b0e; border: 1px solid #4e3b27; border-radius: 6px; text-align: center; min-height: 18px; }
QProgressBar::chunk { background: #d99d37; border-radius: 5px; }
QSplitter::handle { background: #1e1813; width: 1px; }
''')
    window = BatchWindow()
    window.show()
    if QApplication.instance() is app:
        sys.exit(app.exec())


if __name__ == '__main__':
    main()
