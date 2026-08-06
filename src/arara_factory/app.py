from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QSettings, QThread, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
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
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .brainrot_index import build_index, get_index_info, reset_usage
from .render import RenderOptions, _binary, render_reels

VIDEO_EXTENSIONS = {'.mp4', '.mov', '.mkv', '.webm', '.avi'}


def _default_template() -> str:
    """Return a bundled canonical template when it is included in the build."""
    roots = [Path(getattr(sys, '_MEIPASS', Path.cwd())), Path(sys.executable).parent]
    for root in roots:
        candidate = root / 'assets' / 'arara_template.png'
        if candidate.is_file():
            return str(candidate)
    return ''


class FileDropCard(QFrame):
    changed = Signal(str)

    def __init__(self, title: str, hint: str, button_text: str, saved_path: str = ''):
        super().__init__()
        self.setObjectName('dropCard')
        self.setAcceptDrops(True)
        self.setMinimumHeight(138)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(8)

        self.title_label = QLabel(title)
        self.title_label.setObjectName('cardTitle')
        self.hint_label = QLabel(hint)
        self.hint_label.setObjectName('cardHint')
        self.hint_label.setWordWrap(True)
        self.path_edit = QLineEdit(saved_path)
        self.path_edit.setReadOnly(True)
        self.path_edit.setPlaceholderText('Файл ещё не выбран')
        self.path_edit.textChanged.connect(self._emit_change)

        self.choose_button = QPushButton(button_text)
        self.choose_button.setObjectName('chooseButton')

        bottom = QHBoxLayout()
        bottom.addWidget(self.path_edit, 1)
        bottom.addWidget(self.choose_button)

        layout.addWidget(self.title_label)
        layout.addWidget(self.hint_label)
        layout.addLayout(bottom)

    @property
    def path(self) -> str:
        return self.path_edit.text().strip()

    def set_path(self, value: str) -> None:
        self.path_edit.setText(value)

    def clear_path(self) -> None:
        self.path_edit.clear()

    def _emit_change(self, value: str) -> None:
        self.changed.emit(value)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in VIDEO_EXTENSIONS:
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
                self.set_path(str(path))
                event.acceptProposedAction()
                return
        event.ignore()


class PathPicker(QWidget):
    changed = Signal(str)

    def __init__(self, value: str, placeholder: str, mode: str):
        super().__init__()
        self.mode = mode
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.line = QLineEdit(value)
        self.line.setPlaceholderText(placeholder)
        self.line.textChanged.connect(self.changed.emit)
        self.button = QPushButton('Выбрать')
        self.button.clicked.connect(self.choose)
        layout.addWidget(self.line, 1)
        layout.addWidget(self.button)

    @property
    def path(self) -> str:
        return self.line.text().strip()

    def choose(self) -> None:
        start = str(Path(self.path).parent) if self.path else str(Path.home())
        if self.mode == 'folder':
            value = QFileDialog.getExistingDirectory(self, 'Выбрать папку', start)
        else:
            value = QFileDialog.getOpenFileName(self, 'Выбрать PNG-шаблон ARARA', start, 'PNG (*.png)')[0]
        if value:
            self.line.setText(value)


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
            target = build_index(ffprobe, self.video, target_segments=600)
            self.completed.emit(str(target))
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
    ):
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
                lambda value, text: self.progressed.emit(value, text),
                self.logged.emit,
            )
            self.completed.emit([str(path) for path in files])
        except Exception:
            self.failed.emit(traceback.format_exc())


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings('ARARA', 'ARARA Factory')
        self.render_worker: RenderWorker | None = None
        self.index_worker: IndexWorker | None = None

        self.setWindowTitle('ARARA Factory')
        self.resize(960, 790)
        self.setMinimumSize(820, 690)

        root = QWidget()
        self.setCentralWidget(root)
        main = QVBoxLayout(root)
        main.setContentsMargins(34, 28, 34, 28)
        main.setSpacing(16)

        header = QLabel('ARARA FACTORY')
        header.setObjectName('title')
        description = QLabel('Перетащи два видео, проверь короткий тест и собери готовый вертикальный Reel')
        description.setObjectName('subtitle')
        main.addWidget(header)
        main.addWidget(description)

        self.reel_card = FileDropCard(
            '1. ТВОЙ REEL',
            'Перетащи сюда вертикальное видео со звуком. Его звук останется в готовом ролике.',
            'Выбрать Reel',
        )
        self.reel_card.choose_button.clicked.connect(self.choose_reel)
        main.addWidget(self.reel_card)

        saved_brainrot = str(self.settings.value('brainrot', ''))
        self.brainrot_card = FileDropCard(
            '2. ДЛИННЫЙ BRAINROT',
            'Перетащи часовой Car Falling, GTA, Minecraft или другое длинное фоновое видео. Программа запомнит его.',
            'Выбрать brainrot',
            saved_brainrot,
        )
        self.brainrot_card.choose_button.clicked.connect(self.choose_brainrot)
        self.brainrot_card.changed.connect(self.on_brainrot_changed)
        main.addWidget(self.brainrot_card)

        library_row = QHBoxLayout()
        self.library_status = QLabel('Brainrot ещё не выбран')
        self.library_status.setObjectName('libraryStatus')
        self.prepare_button = QPushButton('Подготовить 600 участков')
        self.prepare_button.clicked.connect(self.prepare_brainrot)
        self.reset_button = QPushButton('Начать участки заново')
        self.reset_button.clicked.connect(self.reset_brainrot)
        library_row.addWidget(self.library_status, 1)
        library_row.addWidget(self.prepare_button)
        library_row.addWidget(self.reset_button)
        main.addLayout(library_row)

        action_row = QHBoxLayout()
        self.preview_button = QPushButton('ТЕСТ 5 СЕКУНД')
        self.preview_button.setObjectName('preview')
        self.preview_button.clicked.connect(lambda: self.start_render(preview=True))
        self.render_button = QPushButton('СОБРАТЬ ГОТОВЫЙ REEL')
        self.render_button.setObjectName('generate')
        self.render_button.clicked.connect(lambda: self.start_render(preview=False))
        action_row.addWidget(self.preview_button)
        action_row.addWidget(self.render_button, 1)
        main.addLayout(action_row)

        utility_row = QHBoxLayout()
        self.settings_button = QPushButton('Настройки')
        self.settings_button.clicked.connect(self.toggle_settings)
        self.open_button = QPushButton('Открыть готовые ролики')
        self.open_button.clicked.connect(self.open_output)
        self.next_button = QPushButton('Следующий Reel')
        self.next_button.clicked.connect(self.reel_card.clear_path)
        utility_row.addWidget(self.settings_button)
        utility_row.addWidget(self.open_button)
        utility_row.addWidget(self.next_button)
        utility_row.addStretch(1)
        main.addLayout(utility_row)

        self.settings_panel = QFrame()
        self.settings_panel.setObjectName('settingsPanel')
        settings_layout = QFormLayout(self.settings_panel)
        settings_layout.setContentsMargins(18, 16, 18, 16)

        bundled = _default_template()
        saved_template = str(self.settings.value('template', bundled))
        default_output = Path.home() / 'Videos' / 'ARARA Factory' / 'renders'
        saved_output = str(self.settings.value('output', str(default_output)))
        self.template_picker = PathPicker(saved_template, 'Выбери PNG-шаблон один раз', 'image')
        self.output_picker = PathPicker(saved_output, 'Папка готовых роликов', 'folder')

        self.subtitle_y = QSpinBox()
        self.subtitle_y.setRange(850, 1260)
        self.subtitle_y.setValue(int(self.settings.value('subtitle_y', 1120)))

        self.encoder = QComboBox()
        self.encoder.addItem('Автоматически: NVIDIA → CPU', 'auto')
        self.encoder.addItem('Только NVIDIA', 'nvidia')
        self.encoder.addItem('Только процессор', 'cpu')
        saved_encoder = str(self.settings.value('encoder', 'auto'))
        self.encoder.setCurrentIndex(max(0, self.encoder.findData(saved_encoder)))

        self.quality = QSpinBox()
        self.quality.setRange(16, 28)
        self.quality.setValue(int(self.settings.value('quality', 20)))

        self.auto_open = QCheckBox('Открывать папку после сборки')
        self.auto_open.setChecked(self.settings.value('auto_open', True, type=bool))

        settings_layout.addRow('PNG-шаблон ARARA', self.template_picker)
        settings_layout.addRow('Куда сохранять', self.output_picker)
        settings_layout.addRow('Высота субтитров', self.subtitle_y)
        settings_layout.addRow('Ускорение', self.encoder)
        settings_layout.addRow('Качество', self.quality)
        settings_layout.addRow('', self.auto_open)
        self.settings_panel.setVisible(not bool(saved_template))
        main.addWidget(self.settings_panel)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.status = QLabel('Готова к работе')
        self.status.setObjectName('status')
        main.addWidget(self.progress)
        main.addWidget(self.status)

        self.log_button = QPushButton('Показать технический журнал')
        self.log_button.setObjectName('linkButton')
        self.log_button.clicked.connect(self.toggle_log)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(130)
        self.log.setVisible(False)
        main.addWidget(self.log_button, alignment=Qt.AlignmentFlag.AlignLeft)
        main.addWidget(self.log)

        for control in (
            self.template_picker,
            self.output_picker,
            self.subtitle_y,
            self.encoder,
            self.quality,
            self.auto_open,
        ):
            if hasattr(control, 'changed'):
                control.changed.connect(self.save_preferences)
            elif hasattr(control, 'valueChanged'):
                control.valueChanged.connect(self.save_preferences)
            elif hasattr(control, 'currentIndexChanged'):
                control.currentIndexChanged.connect(self.save_preferences)
            elif hasattr(control, 'toggled'):
                control.toggled.connect(self.save_preferences)

        self.refresh_library_status()

    def choose_reel(self) -> None:
        value = QFileDialog.getOpenFileName(
            self,
            'Выбрать готовый Reel',
            str(Path.home() / 'Videos'),
            'Видео (*.mp4 *.mov *.mkv *.webm *.avi)',
        )[0]
        if value:
            self.reel_card.set_path(value)

    def choose_brainrot(self) -> None:
        start = str(Path(self.brainrot_card.path).parent) if self.brainrot_card.path else str(Path.home() / 'Videos')
        value = QFileDialog.getOpenFileName(
            self,
            'Выбрать длинное brainrot-видео',
            start,
            'Видео (*.mp4 *.mov *.mkv *.webm *.avi)',
        )[0]
        if value:
            self.brainrot_card.set_path(value)

    def on_brainrot_changed(self, value: str) -> None:
        self.settings.setValue('brainrot', value)
        self.settings.sync()
        self.refresh_library_status()

    def save_preferences(self, *args) -> None:
        self.settings.setValue('template', self.template_picker.path)
        self.settings.setValue('output', self.output_picker.path)
        self.settings.setValue('subtitle_y', self.subtitle_y.value())
        self.settings.setValue('encoder', self.encoder.currentData())
        self.settings.setValue('quality', self.quality.value())
        self.settings.setValue('auto_open', self.auto_open.isChecked())
        self.settings.sync()

    def refresh_library_status(self) -> None:
        path_text = self.brainrot_card.path
        path = Path(path_text) if path_text else Path('__missing__')
        if not path.is_file():
            self.library_status.setText('Выбери один длинный MP4 — программа его запомнит')
            self.prepare_button.setEnabled(False)
            self.reset_button.setEnabled(False)
            return
        info = get_index_info(path)
        self.prepare_button.setEnabled(True)
        self.reset_button.setEnabled(bool(info))
        if not info:
            self.library_status.setText('Готов к использованию · индекс создастся автоматически')
        elif not info.is_current:
            self.library_status.setText('Видео изменилось · индекс обновится автоматически')
        else:
            self.library_status.setText(
                f'{info.duration / 60:.1f} мин · осталось {info.remaining} из {info.total} свежих участков'
            )

    def prepare_brainrot(self) -> None:
        path = Path(self.brainrot_card.path)
        if not path.is_file():
            QMessageBox.warning(self, 'Нет brainrot', 'Сначала выбери длинное brainrot-видео.')
            return
        self.prepare_button.setEnabled(False)
        self.library_status.setText('Подготавливаю 600 участков…')
        self.index_worker = IndexWorker(path)
        self.index_worker.completed.connect(self.index_done)
        self.index_worker.failed.connect(self.index_failed)
        self.index_worker.start()

    def index_done(self, target: str) -> None:
        self.log.append(f'Индекс: {target}')
        self.refresh_library_status()
        self.status.setText('Brainrot подготовлен')

    def index_failed(self, error: str) -> None:
        self.prepare_button.setEnabled(True)
        self.log.setPlainText(error)
        self.log.setVisible(True)
        self.library_status.setText('Не удалось подготовить brainrot')
        QMessageBox.critical(self, 'Ошибка индексации', error.splitlines()[-1])

    def reset_brainrot(self) -> None:
        path = Path(self.brainrot_card.path)
        if reset_usage(path):
            self.refresh_library_status()
            self.status.setText('Все brainrot-участки снова доступны')

    def start_render(self, preview: bool) -> None:
        source = Path(self.reel_card.path)
        brainrot = Path(self.brainrot_card.path)
        template = Path(self.template_picker.path)
        output = Path(self.output_picker.path)

        if not source.is_file():
            QMessageBox.warning(self, 'Нужен Reel', 'Перетащи или выбери вертикальный Reel со звуком.')
            return
        if not brainrot.is_file():
            QMessageBox.warning(self, 'Нужен brainrot', 'Перетащи или выбери длинное brainrot-видео.')
            return
        if not template.is_file():
            self.settings_panel.setVisible(True)
            QMessageBox.warning(self, 'Нужен шаблон', 'В настройках выбери PNG-шаблон ARARA. Это потребуется только один раз.')
            return
        if not self.output_picker.path:
            QMessageBox.warning(self, 'Нужна папка', 'Выбери папку для готовых роликов.')
            return

        self.save_preferences()
        options = RenderOptions(
            variants=1,
            subtitle_y=self.subtitle_y.value(),
            font='Arial Black',
            encoder_preset='veryfast',
            crf=self.quality.value(),
            encoder_mode=str(self.encoder.currentData()),
            preview_seconds=5.0 if preview else None,
        )

        self.set_busy(True)
        self.log.clear()
        self.progress.setValue(0)
        self.status.setText('Запускаю тест…' if preview else 'Собираю готовый Reel…')
        self.render_worker = RenderWorker(source, brainrot, template, output, options)
        self.render_worker.progressed.connect(self.on_progress)
        self.render_worker.logged.connect(self.log.append)
        self.render_worker.completed.connect(self.render_done)
        self.render_worker.failed.connect(self.render_failed)
        self.render_worker.start()

    def set_busy(self, busy: bool) -> None:
        self.preview_button.setEnabled(not busy)
        self.render_button.setEnabled(not busy)
        self.prepare_button.setEnabled(not busy and Path(self.brainrot_card.path).is_file())

    def on_progress(self, value: int, text: str) -> None:
        self.progress.setValue(value)
        self.status.setText(text)

    def render_done(self, files: list[str]) -> None:
        self.set_busy(False)
        self.progress.setValue(100)
        self.status.setText(f'Готово: {Path(files[0]).name}' if files else 'Готово')
        self.refresh_library_status()
        if self.auto_open.isChecked():
            self.open_output()
        QMessageBox.information(self, 'ARARA Factory', 'Ролик успешно собран.')

    def render_failed(self, error: str) -> None:
        self.set_busy(False)
        self.status.setText('Сборка не удалась')
        self.log.setPlainText(error)
        self.log.setVisible(True)
        self.log_button.setText('Скрыть технический журнал')
        QMessageBox.critical(self, 'Ошибка', error.splitlines()[-1])

    def open_output(self) -> None:
        path = Path(self.output_picker.path)
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def toggle_settings(self) -> None:
        self.settings_panel.setVisible(not self.settings_panel.isVisible())

    def toggle_log(self) -> None:
        visible = not self.log.isVisible()
        self.log.setVisible(visible)
        self.log_button.setText('Скрыть технический журнал' if visible else 'Показать технический журнал')

    def closeEvent(self, event) -> None:
        self.save_preferences()
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setApplicationName('ARARA Factory')
    app.setOrganizationName('ARARA')
    app.setStyleSheet('''
QWidget {
    background: #0b0a0d;
    color: #f4ecdf;
    font-family: "Segoe UI";
    font-size: 14px;
}
QLabel#title {
    color: #e7ad43;
    font-size: 36px;
    font-weight: 900;
    letter-spacing: 2px;
}
QLabel#subtitle {
    color: #aa9d8d;
    font-size: 16px;
    margin-bottom: 4px;
}
QFrame#dropCard {
    background: #151117;
    border: 2px dashed #6e502c;
    border-radius: 16px;
}
QFrame#dropCard:hover {
    border-color: #e7ad43;
    background: #19131b;
}
QLabel#cardTitle {
    color: #f1c36d;
    font-size: 20px;
    font-weight: 800;
}
QLabel#cardHint {
    color: #a79a8b;
    font-size: 13px;
}
QLabel#libraryStatus {
    color: #bcae9b;
    padding: 5px 2px;
}
QLabel#status {
    color: #dfc89f;
    font-weight: 600;
}
QFrame#settingsPanel {
    background: #121014;
    border: 1px solid #4c3923;
    border-radius: 12px;
}
QLineEdit, QComboBox, QSpinBox, QTextEdit {
    background: #0d0b0e;
    color: #f4ecdf;
    border: 1px solid #4e3b27;
    border-radius: 8px;
    padding: 9px;
    selection-background-color: #8d6429;
}
QPushButton {
    background: #241b14;
    color: #eee3d3;
    border: 1px solid #6b4d29;
    border-radius: 9px;
    padding: 10px 15px;
    font-weight: 650;
}
QPushButton:hover {
    border-color: #e7ad43;
    background: #2c2117;
}
QPushButton:disabled {
    color: #655e56;
    border-color: #31291f;
    background: #151210;
}
QPushButton#chooseButton {
    min-width: 145px;
}
QPushButton#preview {
    background: #252029;
    min-height: 28px;
}
QPushButton#generate {
    background: #d99d37;
    color: #0b0804;
    border-color: #f1be63;
    font-size: 17px;
    font-weight: 900;
    min-height: 32px;
}
QPushButton#generate:hover {
    background: #edb34c;
}
QPushButton#linkButton {
    background: transparent;
    border: none;
    color: #8f806d;
    padding: 2px;
    font-size: 12px;
}
QProgressBar {
    background: #0d0b0e;
    border: 1px solid #4e3b27;
    border-radius: 7px;
    text-align: center;
    min-height: 20px;
}
QProgressBar::chunk {
    background: #d99d37;
    border-radius: 6px;
}
QCheckBox {
    spacing: 8px;
}
''')
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
