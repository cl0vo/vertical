from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QSettings, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .brainrot_index import build_index, get_index_info, reset_usage
from .downloader import download_video
from .render import RenderOptions, _binary, render_reels


class DropLineEdit(QLineEdit):
    """Line edit that accepts a dropped local file or folder."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.setText(url.toLocalFile())
                event.acceptProposedAction()
                return
        super().dropEvent(event)


class IndexWorker(QThread):
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, video: Path):
        super().__init__()
        self.video = video

    def run(self) -> None:
        try:
            ffprobe = _binary('ffprobe')
            if not ffprobe:
                raise RuntimeError('FFprobe не найден внутри программы.')
            path = build_index(ffprobe, self.video, target_segments=600)
            self.completed.emit(str(path))
        except Exception:
            self.failed.emit(traceback.format_exc())


class RenderWorker(QThread):
    progressed = Signal(int, str)
    logged = Signal(str)
    completed = Signal(list)
    failed = Signal(str)

    def __init__(
        self,
        source: Path,
        brainrot: Path,
        template: Path,
        output: Path,
        options: RenderOptions,
        remote_url: str = '',
    ):
        super().__init__()
        self.source = source
        self.brainrot = brainrot
        self.template = template
        self.output = output
        self.options = options
        self.remote_url = remote_url.strip()

    def run(self) -> None:
        try:
            active_source = self.brainrot
            if self.remote_url:
                cache = Path.home() / 'Videos' / 'ARARA Factory' / 'brainrot-cache'
                self.progressed.emit(2, 'Скачиваю разрешённый brainrot')

                def on_download(done: int, total: int) -> None:
                    if total:
                        pct = min(18, 2 + int(done / total * 16))
                        self.progressed.emit(pct, f'Скачано {done // 1048576} / {total // 1048576} МБ')
                    else:
                        self.progressed.emit(8, f'Скачано {done // 1048576} МБ')

                active_source = download_video(self.remote_url, cache, on_download)
                self.logged.emit(f'Brainrot: {active_source}')

            files = render_reels(
                self.source,
                active_source,
                self.template,
                self.output,
                self.options,
                lambda n, s: self.progressed.emit(max(18, n), s),
                self.logged.emit,
            )
            self.completed.emit([str(path) for path in files])
        except Exception:
            self.failed.emit(traceback.format_exc())


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings('ARARA', 'ARARA Factory')
        self.worker: RenderWorker | None = None
        self.index_worker: IndexWorker | None = None
        self.last_files: list[str] = []

        self.setWindowTitle('ARARA Factory — Personal')
        self.resize(1030, 870)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(14)

        title = QLabel('ARARA FACTORY')
        title.setObjectName('title')
        subtitle = QLabel('Личный режим: выбери новый Reel → нажми одну кнопку → получи готовый ролик')
        subtitle.setObjectName('subtitle')
        layout.addWidget(title)
        layout.addWidget(subtitle)

        reel_group = QGroupBox('1 · Новый Reel')
        reel_form = QFormLayout(reel_group)
        self.source = DropLineEdit()
        self.source.setPlaceholderText('Перетащи сюда готовый вертикальный MP4 со звуком')
        reel_form.addRow('Основное видео', self._picker(self.source, 'video'))
        layout.addWidget(reel_group)

        permanent_group = QGroupBox('2 · Постоянные материалы — программа их запомнит')
        permanent_form = QFormLayout(permanent_group)
        self.template = DropLineEdit(str(self.settings.value('template', '')))
        self.template.setPlaceholderText('Vertical overlay Arara.png')
        self.brainrot = DropLineEdit(str(self.settings.value('brainrot', '')))
        self.brainrot.setPlaceholderText('Один длинный GTA brainrot MP4')
        self.output = DropLineEdit(str(self.settings.value('output', Path.home() / 'Videos' / 'ARARA Factory' / 'renders')))

        permanent_form.addRow('Шаблон ARARA', self._picker(self.template, 'image'))
        permanent_form.addRow('Длинный brainrot', self._picker(self.brainrot, 'video_or_folder'))
        permanent_form.addRow('Готовые ролики', self._picker(self.output, 'folder'))

        index_row = QWidget()
        index_layout = QHBoxLayout(index_row)
        index_layout.setContentsMargins(0, 0, 0, 0)
        self.index_status = QLabel('Выбери длинное brainrot-видео')
        self.index_status.setObjectName('hint')
        self.index_button = QPushButton('Создать индекс')
        self.index_button.clicked.connect(self.index_brainrot)
        self.reset_button = QPushButton('Сбросить использованные')
        self.reset_button.clicked.connect(self.reset_brainrot_usage)
        index_layout.addWidget(self.index_status, 1)
        index_layout.addWidget(self.index_button)
        index_layout.addWidget(self.reset_button)
        permanent_form.addRow('Библиотека', index_row)
        layout.addWidget(permanent_group)

        advanced = QGroupBox('3 · Твои настройки')
        advanced_form = QFormLayout(advanced)
        self.font = QComboBox()
        self.font.addItems(['Arial Black', 'Montserrat ExtraBold', 'Impact'])
        self.font.setCurrentText(str(self.settings.value('font', 'Arial Black')))

        self.subtitle_y = QSpinBox()
        self.subtitle_y.setRange(850, 1260)
        self.subtitle_y.setValue(int(self.settings.value('subtitle_y', 1120)))

        self.encoder = QComboBox()
        self.encoder.addItem('Авто — сначала NVIDIA, потом CPU', 'auto')
        self.encoder.addItem('Только NVIDIA', 'nvidia')
        self.encoder.addItem('Только процессор', 'cpu')
        encoder_value = str(self.settings.value('encoder', 'auto'))
        encoder_index = max(0, self.encoder.findData(encoder_value))
        self.encoder.setCurrentIndex(encoder_index)

        self.speed = QComboBox()
        self.speed.addItem('Максимально быстро', 'ultrafast')
        self.speed.addItem('Быстро — рекомендуется', 'veryfast')
        self.speed.addItem('Чуть качественнее', 'faster')
        speed_value = str(self.settings.value('speed', 'veryfast'))
        speed_index = max(0, self.speed.findData(speed_value))
        self.speed.setCurrentIndex(speed_index)

        self.quality = QSpinBox()
        self.quality.setRange(16, 28)
        self.quality.setValue(int(self.settings.value('quality', 20)))

        self.variants = QSpinBox()
        self.variants.setRange(1, 10)
        self.variants.setValue(int(self.settings.value('variants', 1)))

        self.auto_open = QCheckBox('Открывать папку после готовности')
        self.auto_open.setChecked(self.settings.value('auto_open', True, type=bool))

        advanced_form.addRow('CapCut-шрифт', self.font)
        advanced_form.addRow('Высота субтитров', self.subtitle_y)
        advanced_form.addRow('Кодирование', self.encoder)
        advanced_form.addRow('Скорость CPU', self.speed)
        advanced_form.addRow('Качество', self.quality)
        advanced_form.addRow('Вариантов за раз', self.variants)
        advanced_form.addRow('', self.auto_open)
        layout.addWidget(advanced)

        optional = QGroupBox('Необязательно · Скачать один разрешённый MP4')
        optional_form = QFormLayout(optional)
        self.remote_url = QLineEdit()
        self.remote_url.setPlaceholderText('Прямая ссылка на .mp4/.webm; локальный brainrot тогда не используется')
        optional_form.addRow('Ссылка', self.remote_url)
        layout.addWidget(optional)

        action_row = QWidget()
        action_layout = QHBoxLayout(action_row)
        action_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_button = QPushButton('ТЕСТ 5 СЕКУНД')
        self.preview_button.setObjectName('secondaryAction')
        self.preview_button.clicked.connect(lambda: self.start_render(preview=True))
        self.render_button = QPushButton('СОБРАТЬ ГОТОВЫЙ REEL')
        self.render_button.setObjectName('generate')
        self.render_button.clicked.connect(lambda: self.start_render(preview=False))
        action_layout.addWidget(self.preview_button)
        action_layout.addWidget(self.render_button, 1)
        layout.addWidget(action_row)

        small_actions = QWidget()
        small_layout = QHBoxLayout(small_actions)
        small_layout.setContentsMargins(0, 0, 0, 0)
        self.open_button = QPushButton('Открыть папку результатов')
        self.open_button.clicked.connect(self.open_output)
        self.next_button = QPushButton('Следующий Reel')
        self.next_button.clicked.connect(self.next_reel)
        small_layout.addWidget(self.open_button)
        small_layout.addWidget(self.next_button)
        small_layout.addStretch(1)
        layout.addWidget(small_actions)

        self.progress = QProgressBar()
        self.status = QLabel('Готова к работе')
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(120)
        layout.addWidget(self.progress)
        layout.addWidget(self.status)
        layout.addWidget(self.log)

        self.brainrot.textChanged.connect(self.refresh_index_status)
        self.template.textChanged.connect(self.save_preferences)
        self.output.textChanged.connect(self.save_preferences)
        self.brainrot.textChanged.connect(self.save_preferences)
        self.refresh_index_status()

    def _picker(self, line: QLineEdit, kind: str) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(line)
        button = QPushButton('Выбрать')
        button.clicked.connect(lambda: self.choose(line, kind))
        row.addWidget(button)
        return box

    def choose(self, line: QLineEdit, kind: str) -> None:
        last_dir = str(self.settings.value('last_dir', Path.home()))
        if kind == 'folder':
            value = QFileDialog.getExistingDirectory(self, 'Выбрать папку', last_dir)
        elif kind == 'image':
            value = QFileDialog.getOpenFileName(self, 'Выбрать PNG-шаблон', last_dir, 'PNG (*.png)')[0]
        elif kind == 'video_or_folder':
            value = QFileDialog.getOpenFileName(self, 'Выбрать длинное brainrot-видео', last_dir, 'Video (*.mp4 *.mov *.mkv *.webm)')[0]
            if not value:
                value = QFileDialog.getExistingDirectory(self, 'Или выбрать папку brainrot', last_dir)
        else:
            value = QFileDialog.getOpenFileName(self, 'Выбрать видео', last_dir, 'Video (*.mp4 *.mov *.mkv *.webm)')[0]
        if value:
            line.setText(value)
            selected = Path(value)
            self.settings.setValue('last_dir', str(selected if selected.is_dir() else selected.parent))

    def save_preferences(self) -> None:
        self.settings.setValue('template', self.template.text().strip())
        self.settings.setValue('brainrot', self.brainrot.text().strip())
        self.settings.setValue('output', self.output.text().strip())
        self.settings.setValue('font', self.font.currentText())
        self.settings.setValue('subtitle_y', self.subtitle_y.value())
        self.settings.setValue('encoder', self.encoder.currentData())
        self.settings.setValue('speed', self.speed.currentData())
        self.settings.setValue('quality', self.quality.value())
        self.settings.setValue('variants', self.variants.value())
        self.settings.setValue('auto_open', self.auto_open.isChecked())
        self.settings.sync()

    def refresh_index_status(self) -> None:
        path = Path(self.brainrot.text().strip())
        if path.is_dir():
            count = sum(1 for item in path.rglob('*') if item.suffix.lower() in {'.mp4', '.mov', '.mkv', '.webm'})
            self.index_status.setText(f'Папка: {count} видео. Для каждого файла индекс создастся автоматически.')
            self.index_button.setEnabled(False)
            self.reset_button.setEnabled(False)
            return
        info = get_index_info(path)
        self.index_button.setEnabled(path.is_file())
        self.reset_button.setEnabled(bool(info))
        if not path.is_file():
            self.index_status.setText('Выбери один длинный MP4 — путь сохранится навсегда')
        elif not info:
            self.index_status.setText('Индекса пока нет. Он создастся автоматически при первом рендере.')
        elif not info.is_current:
            self.index_status.setText('Файл изменился — индекс будет пересоздан автоматически.')
        else:
            minutes = info.duration / 60
            self.index_status.setText(f'{minutes:.1f} мин · {info.remaining} из {info.total} свежих участков осталось')

    def index_brainrot(self) -> None:
        video = Path(self.brainrot.text().strip())
        if not video.is_file():
            QMessageBox.warning(self, 'Нужен один файл', 'Выбери один длинный brainrot MP4.')
            return
        self.index_button.setEnabled(False)
        self.index_status.setText('Создаю быстрый индекс…')
        self.index_worker = IndexWorker(video)
        self.index_worker.completed.connect(self.index_done)
        self.index_worker.failed.connect(self.index_failed)
        self.index_worker.start()

    def index_done(self, path: str) -> None:
        self.index_button.setEnabled(True)
        self.log.append(f'Индекс: {path}')
        self.refresh_index_status()

    def index_failed(self, error: str) -> None:
        self.index_button.setEnabled(True)
        self.index_status.setText('Ошибка индексации')
        self.log.setPlainText(error)

    def reset_brainrot_usage(self) -> None:
        video = Path(self.brainrot.text().strip())
        if reset_usage(video):
            self.refresh_index_status()
            self.status.setText('Все участки снова доступны')
        else:
            QMessageBox.information(self, 'ARARA Factory', 'Индекс пока не создан.')

    def _validate(self) -> tuple[Path, Path, Path, Path, str] | None:
        source = Path(self.source.text().strip())
        template = Path(self.template.text().strip())
        output = Path(self.output.text().strip())
        remote_url = self.remote_url.text().strip()
        brainrot_text = self.brainrot.text().strip()
        brainrot = Path(brainrot_text) if brainrot_text else Path.home() / 'Videos' / 'ARARA Factory' / 'brainrot-cache'

        if not source.is_file():
            QMessageBox.warning(self, 'Нужен Reel', 'Перетащи или выбери готовый Reel со звуком.')
            return None
        if not template.is_file():
            QMessageBox.warning(self, 'Нужен шаблон', 'Один раз выбери PNG-шаблон ARARA.')
            return None
        if not remote_url and not brainrot.exists():
            QMessageBox.warning(self, 'Нужен brainrot', 'Один раз выбери длинный GTA brainrot-файл.')
            return None
        return source, brainrot, template, output, remote_url

    def start_render(self, preview: bool) -> None:
        values = self._validate()
        if not values:
            return
        source, brainrot, template, output, remote_url = values
        self.save_preferences()

        options = RenderOptions(
            variants=1 if preview else self.variants.value(),
            subtitle_y=self.subtitle_y.value(),
            font=self.font.currentText(),
            encoder_preset=self.speed.currentData(),
            crf=self.quality.value(),
            encoder_mode=self.encoder.currentData(),
            preview_seconds=5.0 if preview else None,
        )
        self.render_button.setEnabled(False)
        self.preview_button.setEnabled(False)
        self.log.clear()
        self.progress.setValue(0)
        self.status.setText('Запускаю сборку…')
        self.worker = RenderWorker(source, brainrot, template, output, options, remote_url)
        self.worker.progressed.connect(self.on_progress)
        self.worker.logged.connect(self.log.append)
        self.worker.completed.connect(lambda files: self.done(files, preview))
        self.worker.failed.connect(self.fail)
        self.worker.start()

    def on_progress(self, value: int, text: str) -> None:
        self.progress.setValue(value)
        self.status.setText(text)

    def done(self, files: list[str], preview: bool) -> None:
        self.render_button.setEnabled(True)
        self.preview_button.setEnabled(True)
        self.progress.setValue(100)
        self.last_files = files
        self.refresh_index_status()
        self.status.setText('Тест готов' if preview else f'Готово: {len(files)} Reel')
        if self.auto_open.isChecked() and files:
            self.open_output()
        QMessageBox.information(
            self,
            'ARARA Factory',
            'Пятисекундный тест готов.' if preview else f'Готово. Создано роликов: {len(files)}',
        )

    def fail(self, error: str) -> None:
        self.render_button.setEnabled(True)
        self.preview_button.setEnabled(True)
        self.status.setText('Ошибка')
        self.log.setPlainText(error)
        QMessageBox.critical(self, 'Ошибка', error.splitlines()[-1] if error.splitlines() else error)

    def open_output(self) -> None:
        folder = Path(self.output.text().strip())
        folder.mkdir(parents=True, exist_ok=True)
        if sys.platform == 'win32':
            os.startfile(folder)  # type: ignore[attr-defined]
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def next_reel(self) -> None:
        self.source.clear()
        self.remote_url.clear()
        self.progress.setValue(0)
        self.status.setText('Выбери следующий Reel')
        self.source.setFocus()

    def closeEvent(self, event) -> None:
        self.save_preferences()
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName('ARARA Factory')
    app.setOrganizationName('ARARA')
    app.setStyle('Fusion')
    app.setStyleSheet('''
QWidget { background:#0b0b0e; color:#f4ead8; font-family:Segoe UI; font-size:14px; }
QLabel#title { font-size:35px; font-weight:900; color:#e6ad45; }
QLabel#subtitle { font-size:16px; color:#b8aa94; }
QLabel#hint { color:#9c8c75; font-size:12px; }
QGroupBox { border:1px solid #5b421d; border-radius:14px; margin-top:12px; padding:17px; background:#15120f; }
QGroupBox::title { subcontrol-origin:margin; left:14px; padding:0 8px; color:#e6ad45; font-weight:700; }
QLineEdit, QComboBox, QSpinBox, QTextEdit { background:#0e0c0b; border:1px solid #594226; border-radius:8px; padding:9px; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color:#e6ad45; }
QPushButton { background:#241c14; border:1px solid #684b27; border-radius:9px; padding:10px 16px; font-weight:700; }
QPushButton:hover { border-color:#f0bd5f; background:#302317; }
QPushButton:disabled { color:#665e54; border-color:#392d20; }
QPushButton#generate { background:#d39a38; color:#0a0805; font-size:18px; padding:16px; }
QPushButton#secondaryAction { background:#17130f; color:#e6ad45; font-size:15px; padding:16px; }
QProgressBar { border:1px solid #594226; border-radius:7px; text-align:center; background:#0e0c0b; min-height:18px; }
QProgressBar::chunk { background:#d39a38; border-radius:6px; }
QCheckBox { spacing:8px; }
''')
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
