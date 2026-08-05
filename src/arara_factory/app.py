from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton, QSpinBox, QTextEdit, QVBoxLayout, QWidget

from .render import RenderOptions, render_reels


class RenderWorker(QThread):
    progressed = Signal(int, str)
    logged = Signal(str)
    completed = Signal(list)
    failed = Signal(str)

    def __init__(self, source: Path, brainrot: Path, output: Path, options: RenderOptions):
        super().__init__()
        self.source = source
        self.brainrot = brainrot
        self.output = output
        self.options = options

    def run(self) -> None:
        try:
            files = render_reels(
                self.source,
                self.brainrot,
                self.output,
                self.options,
                lambda n, s: self.progressed.emit(n, s),
                self.logged.emit,
            )
            self.completed.emit([str(x) for x in files])
        except Exception:
            self.failed.emit(traceback.format_exc())


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('ARARA Factory')
        self.resize(980, 760)
        self.worker = None

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)

        title = QLabel('ARARA FACTORY')
        title.setObjectName('title')
        subtitle = QLabel('Умная сборка вертикальных brainrot-рилсов')
        subtitle.setObjectName('subtitle')
        layout.addWidget(title)
        layout.addWidget(subtitle)

        files = QGroupBox('Материалы')
        form = QFormLayout(files)
        self.source = QLineEdit()
        self.brainrot = QLineEdit()
        self.output = QLineEdit(str(Path.home() / 'Videos' / 'ARARA Factory'))
        form.addRow('Исходный Reel', self._picker(self.source, False))
        form.addRow('Папка brainrot', self._picker(self.brainrot, True))
        form.addRow('Папка результата', self._picker(self.output, True))
        layout.addWidget(files)

        opts = QGroupBox('Монтажный движок')
        of = QFormLayout(opts)
        self.variants = QSpinBox()
        self.variants.setRange(1, 20)
        self.variants.setValue(3)
        self.chance = QDoubleSpinBox()
        self.chance.setRange(0, 1)
        self.chance.setSingleStep(.05)
        self.chance.setValue(.65)
        self.font = QComboBox()
        self.font.addItems(['Arial Black', 'Montserrat ExtraBold', 'Impact'])
        self.y = QSpinBox()
        self.y.setRange(900, 1700)
        self.y.setValue(1380)
        of.addRow('Количество версий', self.variants)
        of.addRow('Плотность перебивок', self.chance)
        of.addRow('Шрифт субтитров', self.font)
        of.addRow('Высота субтитров', self.y)
        layout.addWidget(opts)

        self.button = QPushButton('СОБРАТЬ REELS')
        self.button.setObjectName('generate')
        self.button.clicked.connect(self.start)
        layout.addWidget(self.button)

        self.progress = QProgressBar()
        self.status = QLabel('Готов к работе')
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(170)
        layout.addWidget(self.progress)
        layout.addWidget(self.status)
        layout.addWidget(self.log)

    def _picker(self, line: QLineEdit, folder: bool) -> QWidget:
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(line)
        button = QPushButton('Выбрать')
        button.clicked.connect(lambda: self.choose(line, folder))
        h.addWidget(button)
        return box

    def choose(self, line: QLineEdit, folder: bool) -> None:
        value = QFileDialog.getExistingDirectory(self, 'Выбрать папку') if folder else QFileDialog.getOpenFileName(self, 'Выбрать видео', filter='Video (*.mp4 *.mov *.mkv *.webm)')[0]
        if value:
            line.setText(value)

    def start(self) -> None:
        source = Path(self.source.text().strip())
        brainrot = Path(self.brainrot.text().strip())
        output = Path(self.output.text().strip())
        if not source.is_file() or not brainrot.is_dir():
            QMessageBox.warning(self, 'Не хватает файлов', 'Выбери исходное видео и папку с brainrot-клипами.')
            return
        options = RenderOptions(
            variants=self.variants.value(),
            cutaway_chance=self.chance.value(),
            subtitle_y=self.y.value(),
            font=self.font.currentText(),
        )
        self.button.setEnabled(False)
        self.log.clear()
        self.worker = RenderWorker(source, brainrot, output, options)
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
        self.status.setText(f'Готово: {len(files)} файлов')
        QMessageBox.information(self, 'ARARA Factory', 'Рилсы успешно собраны.')

    def fail(self, error: str) -> None:
        self.button.setEnabled(True)
        self.status.setText('Ошибка')
        self.log.setPlainText(error)
        QMessageBox.critical(self, 'Ошибка', error.splitlines()[-1])


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setStyleSheet('''
QWidget { background:#0c0d12; color:#f3f3f6; font-family:Segoe UI; font-size:14px; }
QLabel#title { font-size:34px; font-weight:900; color:#79ff43; }
QLabel#subtitle { font-size:16px; color:#9da0ad; }
QGroupBox { border:1px solid #292c37; border-radius:14px; margin-top:12px; padding:18px; background:#14161d; }
QGroupBox::title { subcontrol-origin:margin; left:14px; padding:0 8px; color:#79ff43; font-weight:700; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit { background:#0d0f15; border:1px solid #303440; border-radius:8px; padding:9px; }
QPushButton { background:#222632; border:1px solid #343947; border-radius:9px; padding:10px 16px; font-weight:700; }
QPushButton:hover { border-color:#79ff43; }
QPushButton:disabled { color:#666; }
QPushButton#generate { background:#79ff43; color:#090a0d; font-size:17px; padding:15px; }
QProgressBar { border:1px solid #303440; border-radius:7px; text-align:center; background:#0d0f15; }
QProgressBar::chunk { background:#79ff43; border-radius:6px; }
''')
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
