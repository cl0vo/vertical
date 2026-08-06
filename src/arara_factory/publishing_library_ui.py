from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from .publishing import Platform, platform_connected
from .publishing_library import (
    discover_reels,
    effective_queue_start,
    normalize_selected_reels,
)
from .publishing_runtime_ui import PublishingRuntimeWindow


class PublishingLibraryWindow(PublishingRuntimeWindow):
    def __init__(self) -> None:
        self.selected_publish_files: list[Path] = []
        self.selected_publish_folder: Path | None = None
        super().__init__()

        # A disconnected platform should not block a working YouTube-only queue.
        for platform, box in self.platform_boxes.items():
            if not platform_connected(platform):
                box.setChecked(False)

        self.library_frame = QFrame()
        self.library_frame.setObjectName("card")
        layout = QVBoxLayout(self.library_frame)
        layout.setContentsMargins(13, 11, 13, 11)
        layout.setSpacing(8)

        title = QLabel("REELS ДЛЯ ПОСТИНГА")
        title.setObjectName("cardTitle")
        layout.addWidget(title)

        select_row = QHBoxLayout()
        self.choose_reels_button = QPushButton("Выбрать Reels")
        self.choose_reels_button.clicked.connect(self.choose_reels)
        self.choose_folder_button = QPushButton("Выбрать папку")
        self.choose_folder_button.clicked.connect(self.choose_folder)
        self.clear_selection_button = QPushButton("Очистить")
        self.clear_selection_button.clicked.connect(self.clear_selection)
        select_row.addWidget(self.choose_reels_button)
        select_row.addWidget(self.choose_folder_button)
        select_row.addWidget(self.clear_selection_button)
        select_row.addStretch(1)
        layout.addLayout(select_row)

        options_row = QHBoxLayout()
        options_row.addWidget(QLabel("Порядок:"))
        self.order_combo = QComboBox()
        self.order_combo.addItem("По имени", "name")
        self.order_combo.addItem("Сначала старые", "created")
        self.order_combo.addItem("По изменению", "modified")
        saved_order = str(self.publish_settings.value("publish_file_order", "name"))
        order_index = self.order_combo.findData(saved_order)
        self.order_combo.setCurrentIndex(order_index if order_index >= 0 else 0)
        self.order_combo.currentIndexChanged.connect(self.selection_options_changed)

        self.recursive_box = QCheckBox("Включая подпапки")
        self.recursive_box.setChecked(
            self.publish_settings.value("publish_recursive", False, type=bool)
        )
        self.recursive_box.toggled.connect(self.selection_options_changed)

        options_row.addWidget(self.order_combo)
        options_row.addWidget(self.recursive_box)
        options_row.addStretch(1)
        layout.addLayout(options_row)

        schedule_row = QHBoxLayout()
        schedule_row.addWidget(QLabel("Первый пост через:"))
        self.delay_minutes = QSpinBox()
        self.delay_minutes.setRange(0, 10_080)
        self.delay_minutes.setValue(
            int(self.publish_settings.value("publish_start_delay", 0) or 0)
        )
        self.delay_minutes.setSuffix(" мин")
        self.delay_minutes.setMaximumWidth(125)
        self.delay_minutes.valueChanged.connect(self.save_library_preferences)
        schedule_row.addWidget(self.delay_minutes)
        schedule_row.addWidget(QLabel("Дальше используется интервал ниже"))
        schedule_row.addStretch(1)
        layout.addLayout(schedule_row)

        self.selection_status = QLabel("Файлы ещё не выбраны")
        self.selection_status.setObjectName("libraryStatus")
        self.selection_status.setWordWrap(True)
        layout.addWidget(self.selection_status)

        add_row = QHBoxLayout()
        self.schedule_selected_button = QPushButton("ПОСТАВИТЬ В РАСПИСАНИЕ")
        self.schedule_selected_button.setObjectName("generate")
        self.schedule_selected_button.clicked.connect(self.schedule_selected)
        add_row.addWidget(self.schedule_selected_button)
        add_row.addStretch(1)
        layout.addLayout(add_row)

        publish_layout = self.publish_frame.layout()
        # Title, platforms, caption, interval controls, then this selection block.
        publish_layout.insertWidget(4, self.library_frame)
        self.add_ready_button.setVisible(False)

        saved_folder = str(self.publish_settings.value("publish_source_folder", ""))
        if saved_folder and Path(saved_folder).is_dir():
            self.selected_publish_folder = Path(saved_folder)
            self.reload_folder_selection()
        else:
            self.update_selection_status()
        self.refresh_publish_status()

    def save_library_preferences(self, *args) -> None:
        self.publish_settings.setValue("publish_start_delay", self.delay_minutes.value())
        self.publish_settings.setValue("publish_file_order", self.order_combo.currentData())
        self.publish_settings.setValue("publish_recursive", self.recursive_box.isChecked())
        self.publish_settings.setValue(
            "publish_source_folder",
            str(self.selected_publish_folder or ""),
        )
        self.publish_settings.sync()

    def choose_reels(self) -> None:
        start = str(
            self.publish_settings.value(
                "publish_last_directory",
                str(Path.home() / "Videos"),
            )
        )
        values = QFileDialog.getOpenFileNames(
            self,
            "Выбрать готовые Reels",
            start,
            "Видео Reels (*.mp4 *.mov *.m4v *.webm)",
        )[0]
        if not values:
            return
        paths = [Path(value) for value in values]
        self.selected_publish_folder = None
        self.selected_publish_files = normalize_selected_reels(
            paths,
            order=str(self.order_combo.currentData()),
        )
        self.publish_settings.setValue(
            "publish_last_directory",
            str(self.selected_publish_files[0].parent),
        )
        self.save_library_preferences()
        self.update_selection_status()

    def choose_folder(self) -> None:
        start = str(
            self.publish_settings.value(
                "publish_source_folder",
                str(Path.home() / "Videos"),
            )
        )
        value = QFileDialog.getExistingDirectory(
            self,
            "Выбрать папку с готовыми Reels",
            start,
        )
        if not value:
            return
        self.selected_publish_folder = Path(value)
        self.save_library_preferences()
        self.reload_folder_selection()

    def reload_folder_selection(self) -> None:
        if self.selected_publish_folder is None:
            return
        self.selected_publish_files = discover_reels(
            self.selected_publish_folder,
            recursive=self.recursive_box.isChecked(),
            order=str(self.order_combo.currentData()),
        )
        self.update_selection_status()

    def selection_options_changed(self, *args) -> None:
        self.save_library_preferences()
        if self.selected_publish_folder is not None:
            self.reload_folder_selection()
        else:
            self.selected_publish_files = normalize_selected_reels(
                self.selected_publish_files,
                order=str(self.order_combo.currentData()),
            )
            self.update_selection_status()

    def clear_selection(self) -> None:
        self.selected_publish_files = []
        self.selected_publish_folder = None
        self.save_library_preferences()
        self.update_selection_status()

    def update_selection_status(self) -> None:
        count = len(self.selected_publish_files)
        if not count:
            self.selection_status.setText("Файлы ещё не выбраны")
            self.schedule_selected_button.setEnabled(False)
            return
        preview = ", ".join(path.name for path in self.selected_publish_files[:3])
        if count > 3:
            preview += f" … ещё {count - 3}"
        source = (
            f"папка {self.selected_publish_folder.name}"
            if self.selected_publish_folder is not None
            else "выбранные файлы"
        )
        self.selection_status.setText(f"Найдено {count} · {source} · {preview}")
        self.schedule_selected_button.setEnabled(True)

    def _effective_start(self, interval_minutes: int) -> float:
        existing = [
            job.due_at
            for job in self.publish_queue.jobs
            if not job.done
        ]
        return effective_queue_start(
            existing,
            delay_minutes=self.delay_minutes.value(),
            interval_minutes=interval_minutes,
        )

    def enqueue_files(self, files: list[str | Path]) -> int:
        platforms = self.selected_platforms()
        if not platforms:
            return 0
        paths = normalize_selected_reels(
            [Path(item) for item in files],
            order=str(self.order_combo.currentData()) if hasattr(self, "order_combo") else "name",
        )
        interval = int(self.interval.currentData())
        start_at = self._effective_start(interval) if hasattr(self, "delay_minutes") else time.time()
        added = self.publish_queue.enqueue(
            paths,
            platforms,
            self.caption.toPlainText(),
            interval,
            start_at=start_at,
        )
        self.refresh_publish_status()
        return len(added)

    def schedule_selected(self) -> None:
        if not self.selected_publish_files:
            QMessageBox.warning(self, "Нет Reels", "Выбери файлы или папку с готовыми Reels.")
            return
        if not self.selected_platforms():
            QMessageBox.warning(self, "Нет платформ", "Отметь YouTube или другую подключённую платформу.")
            return
        disconnected = [
            platform.value
            for platform in self.selected_platforms()
            if not platform_connected(platform)
        ]
        if disconnected:
            QMessageBox.warning(
                self,
                "Платформа не подключена",
                "Оставь отмеченными только подключённые платформы.",
            )
            return

        added = self.enqueue_files(self.selected_publish_files)
        skipped = len(self.selected_publish_files) - added
        if added == 0:
            self.status.setText("Эти Reels уже есть в очереди или уже публиковались")
            return

        if not self.publish_timer.isActive():
            self.toggle_publish_queue()
        delay = self.delay_minutes.value()
        text = f"В расписание добавлено {added}"
        if skipped:
            text += f" · пропущено повторов {skipped}"
        if delay:
            text += f" · первый пост не раньше чем через {delay} мин"
        self.status.setText(text)
        self.refresh_publish_status()

    def refresh_publish_status(self) -> None:
        super().refresh_publish_status()
        if not hasattr(self, "publish_status"):
            return
        next_job = self.publish_queue.next_scheduled()
        if next_job is None:
            return
        exact = datetime.fromtimestamp(next_job.due_at).strftime("%d.%m %H:%M")
        self.publish_status.setText(self.publish_status.text() + f" · время {exact}")


def install(app_module) -> None:
    app_module.MainWindow = PublishingLibraryWindow
