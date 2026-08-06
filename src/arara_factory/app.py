from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QSpinBox, QTextEdit, QVBoxLayout, QWidget,
)

from .brainrot_index import build_index
from .downloader import download_video
from .render import RenderOptions, _binary, render_reels


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

    def __init__(self, source: Path, brainrot: Path, template: Path, output: Path, options: RenderOptions, remote_url: str = ''):
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
                        self.progressed.emit(min(18, 2 + int(done / total * 16)), f'Скачано {done // 1048576} / {total // 1048576} МБ')
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
            self.completed.emit([str(x) for x in files])
        except Exception:
            self.failed.emit(traceback.format_exc())


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('ARARA Factory — Fast Hero')
        self.resize(1040, 900)
        self.worker = None
        self.index_worker = None

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(15)

        title = QLabel('ARARA FACTORY')
        title.setObjectName('title')
        subtitle = QLabel('Один длинный brainrot → до 600 неповторяющихся участков → быстрый Hero Reel')
        subtitle.setObjectName('subtitle')
        layout.addWidget(title)
        layout.addWidget(subtitle)

        files = QGroupBox('Основные материалы')
        form = QFormLayout(files)
        self.source = QLineEdit()
        self.template = QLineEdit()
        self.output = QLineEdit(str(Path.home() / 'Videos' / 'ARARA Factory' / 'renders'))
        form.addRow('Готовый Reel со звуком', self._picker(self.source, 'video'))
        form.addRow('PNG-шаблон ARARA', self._picker(self.template, 'image'))
        form.addRow('Папка результата', self._picker(self.output, 'folder'))
        layout.addWidget(files)

        brain = QGroupBox('Brainrot-библиотека')
        bf = QFormLayout(brain)
        self.remote_url = QLineEdit()
        self.remote_url.setPlaceholderText('Прямая разрешённая ссылка на .mp4/.webm — необязательно')
        self.brainrot = QLineEdit()
        self.brainrot.setPlaceholderText('Один длинный MP4 или папка с видео')
        bf.addRow('Скачать по ссылке', self.remote_url)
        bf.addRow('Локальный источник', self._picker(self.brainrot, 'video_or_folder'))
        index_row = QWidget()
        index_layout = QHBoxLayout(index_row)
        index_layout.setContentsMargins(0, 0, 0, 0)
        self.index_button = QPushButton('БЫСТРО ПРОИНДЕКСИРОВАТЬ 600 УЧАСТКОВ')
        self.index_button.clicked.connect(self.index_brainrot)
        self.index_status = QLabel('Индекс создаётся один раз и потом используется мгновенно.')
        self.index_status.setObjectName('hint')
        index_layout.addWidget(self.index_button)
        index_layout.addWidget(self.index_status, 1)
        bf.addRow('', index_row)
        layout.addWidget(brain)

        opts = QGroupBox('Скорость и субтитры')
        of = QFormLayout(opts)
        self.variants = QSpinBox()
        self.variants.setRange(1, 10)
        self.variants.setValue(1)
        self.font = QComboBox()
        self.font.addItems(['Arial Black', 'Montserrat ExtraBold', 'Impact'])
        self.y = QSpinBox()
        self.y.setRange(850, 1260)
        self.y.setValue(1120)
        self.speed = QComboBox()
        self.speed.addItem('Максимально быстро', 'ultrafast')
        self.speed.addItem('Быстро — рекомендуется', 'veryfast')
        self.speed.addItem('Баланс качества', 'faster')
        self.quality = QSpinBox()
        self.quality.setRange(16, 28)
        self.quality.setValue(20)
        of.addRow('Количество вариантов', self.variants)
        of.addRow('Скорость рендера', self.speed)
        of.addRow('Качество CRF', self.quality)
        of.addRow('Шрифт субтитров', self.font)
        of.addRow('Позиция субтитров', self.y)
        layout.addWidget(opts)

        self.button = QPushButton('СОБРАТЬ БЫСТРЫЙ HERO REEL')
        self.button.setObjectName('generate')
        self.button.clicked.connect(self.start)
        layout.addWidget(self.button)

        self.progress = QProgressBar()
        self.status = QLabel('Готов к работе')
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(165)
        layout.addWidget(self.progress)
        layout.addWidget(self.status)
        layout.addWidget(self.log)

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
        if kind == 'folder':
            value = QFileDialog.getExistingDirectory(self, 'Выбрать папку')
        elif kind == 'image':
            value = QFileDialog.getOpenFileName(self, 'Выбрать PNG-шаблон', filter='PNG (*.png)')[0]
        elif kind == 'video_or_folder':
            value = QFileDialog.getOpenFileName(self, 'Выбрать длинное brainrot-видео', filter='Video (*.mp4 *.mov *.mkv *.webm)')[0]
            if not value:
                value = QFileDialog.getExistingDirectory(self, 'Или выбрать папку brainrot')
        else:
            value = QFileDialog.getOpenFileName(self, 'Выбрать видео', filter='Video (*.mp4 *.mov *.mkv *.webm)')[0]
        if value:
            line.setText(value)

    def index_brainrot(self) -> None:
        video = Path(self.brainrot.text().strip())
        if not video.is_file():
            QMessageBox.warning(self, 'Нужен один файл', 'Для индекса выбери один длинный brainrot MP4.')
            return
        self.index_button.setEnabled(False)
        self.index_status.setText('Индексирую…')
        self.index_worker = IndexWorker(video)
        self.index_worker.completed.connect(self.index_done)
        self.index_worker.failed.connect(self.index_failed)
        self.index_worker.start()

    def index_done(self, path: str) -> None:
        self.index_button.setEnabled(True)
        self.index_status.setText('Готово: до 600 участков без создания отдельных MP4.')
        self.log.append(f'Индекс: {path}')

    def index_failed(self, error: str) -> None:
        self.index_button.setEnabled(True)
        self.index_status.setText('Ошибка индексации')
        self.log.setPlainText(error)

    def start(self) -> None:
        source = Path(self.source.text().strip())
        template = Path(self.template.text().strip())
        output = Path(self.output.text().strip())
        remote_url = self.remote_url.text().strip()
        brainrot_text = self.brainrot.text().strip()
        brainrot = Path(brainrot_text) if brainrot_text else Path.home() / 'Videos' / 'ARARA Factory' / 'brainrot-cache'

        if not source.is_file() or not template.is_file():
            QMessageBox.warning(self, 'Не хватает файлов', 'Выбери готовый Reel и PNG-шаблон ARARA.')
            return
        if not remote_url and not brainrot.exists():
            QMessageBox.warning(self, 'Нет brainrot', 'Вставь прямую разрешённую ссылку или выбери длинный brainrot-файл.')
            return

        options = RenderOptions(
            variants=self.variants.value(),
            subtitle_y=self.y.value(),
            font=self.font.currentText(),
            encoder_preset=self.speed.currentData(),
            crf=self.quality.value(),
        )
        self.button.setEnabled(False)
        self.log.clear()
        self.progress.setValue(0)
        self.worker = RenderWorker(source, brainrot, template, output, options, remote_url)
        self.worker.progressed.connect(self.on_progress)
        self.worker.logged.connect(self.log.append)
        self.worker.completed.connect(self.done)
        self.worker.failed.connect(self.fail)
        self.worker.start()

    def on_progress(self, value: int, text: str) -> None:
        self.progress.setValue(value)
        self.status.setText(text)

    def done(self, files: list[str]) -> None:
        self.button.setEnabled(True)
        self.progress.setValue(100)
        self.status.setText(f'Готово: {len(files)} файл(ов)')
        QMessageBox.information(self, 'ARARA Factory', f'Готово. Создано файлов: {len(files)}')

    def fail(self, error: str) -> None:
        self.button.setEnabled(True)
        self.status.setText('Ошибка')
        self.log.setPlainText(error)
        QMessageBox.critical(self, 'Ошибка', error.splitlines()[-1])


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setStyleSheet('''
QWidget { background:#0b0b0e; color:#f4ead8; font-family:Segoe UI; font-size:14px; }
QLabel#title { font-size:34px; font-weight:900; color:#e6ad45; }
QLabel#subtitle { font-size:16px; color:#b8aa94; }
QLabel#hint { color:#8e806d; font-size:12px; }
QGroupBox { border:1px solid #5b421d; border-radius:14px; margin-top:12px; padding:18px; background:#15120f; }
QGroupBox::title { subcontrol-origin:margin; left:14px; padding:0 8px; color:#e6ad45; font-weight:700; }
QLineEdit, QComboBox, QSpinBox, QTextEdit { background:#0e0c0b; border:1px solid #594226; border-radius:8px; padding:9px; }
QPushButton { background:#241c14; border:1px solid #684b27; border-radius:9px; padding:10px 16px; font-weight:700; }
QPushButton:hover { border-color:#e6ad45; }
QPushButton:disabled { color:#665e54; }
QPushButton#generate { background:#d39a38; color:#0a0805; font-size:17px; padding:15px; }
QProgressBar { border:1px solid #594226; border-radius:7px; text-align:center; background:#0e0c0b; }
QProgressBar::chunk { background:#d39a38; border-radius:6px; }
''')
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
