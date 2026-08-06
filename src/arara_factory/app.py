from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton, QSpinBox, QTextEdit, QVBoxLayout, QWidget

from .render import RenderOptions, render_reels


class RenderWorker(QThread):
    progressed = Signal(int, str)
    logged = Signal(str)
    completed = Signal(list)
    failed = Signal(str)

    def __init__(self, source: Path, brainrot: Path, template: Path, output: Path, options: RenderOptions):
        super().__init__()
        self.source = source
        self.brainrot = brainrot
        self.template = template
        self.output = output
        self.options = options

    def run(self) -> None:
        try:
            files = render_reels(
                self.source,
                self.brainrot,
                self.template,
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
        self.setWindowTitle('ARARA Factory — Hero')
        self.resize(980, 790)
        self.worker = None

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)

        title = QLabel('ARARA FACTORY')
        title.setObjectName('title')
        subtitle = QLabel('Персонаж сверху · основной Reel по центру · полный бесшумный brainrot снизу')
        subtitle.setObjectName('subtitle')
        layout.addWidget(title)
        layout.addWidget(subtitle)

        files = QGroupBox('Материалы')
        form = QFormLayout(files)
        self.source = QLineEdit()
        self.brainrot = QLineEdit()
        self.template = QLineEdit()
        self.output = QLineEdit(str(Path.home() / 'Videos' / 'ARARA Factory'))
        form.addRow('Готовый Reel со звуком', self._picker(self.source, 'video'))
        form.addRow('Папка тихих brainrot-видео', self._picker(self.brainrot, 'folder'))
        form.addRow('PNG-шаблон ARARA', self._picker(self.template, 'image'))
        form.addRow('Папка результата', self._picker(self.output, 'folder'))
        layout.addWidget(files)

        opts = QGroupBox('Hero layout')
        of = QFormLayout(opts)
        self.variants = QSpinBox()
        self.variants.setRange(1, 20)
        self.variants.setValue(3)
        self.font = QComboBox()
        self.font.addItems(['Arial Black', 'Montserrat ExtraBold', 'Impact'])
        self.y = QSpinBox()
        self.y.setRange(850, 1260)
        self.y.setValue(1120)
        of.addRow('Количество вариантов', self.variants)
        of.addRow('Шрифт субтитров', self.font)
        of.addRow('Позиция субтитров', self.y)
        layout.addWidget(opts)

        self.button = QPushButton('СОБРАТЬ HERO REELS')
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
        else:
            value = QFileDialog.getOpenFileName(self, 'Выбрать видео', filter='Video (*.mp4 *.mov *.mkv *.webm)')[0]
        if value:
            line.setText(value)

    def start(self) -> None:
        source = Path(self.source.text().strip())
        brainrot = Path(self.brainrot.text().strip())
        template = Path(self.template.text().strip())
        output = Path(self.output.text().strip())
        if not source.is_file() or not brainrot.is_dir() or not template.is_file():
            QMessageBox.warning(self, 'Не хватает файлов', 'Выбери Reel, папку brainrot и PNG-шаблон ARARA.')
            return
        options = RenderOptions(
            variants=self.variants.value(),
            subtitle_y=self.y.value(),
            font=self.font.currentText(),
        )
        self.button.setEnabled(False)
        self.log.clear()
        self.worker = RenderWorker(source, brainrot, template, output, options)
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
        QMessageBox.information(self, 'ARARA Factory', 'Hero Reels успешно собраны.')

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
