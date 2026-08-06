from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from .app import MainWindow
from .batch import BatchPlan, format_timestamp, load_plan, reset_progress
from .batch_app import BatchRenderWorker
from .render import MAX_REEL_SECONDS, MIN_REEL_SECONDS, RenderOptions


class IntegratedBatchWindow(MainWindow):
    """Main ARARA window with automatic long-recording batch mode."""

    def __init__(self) -> None:
        self.batch_mode = False
        self.batch_worker: BatchRenderWorker | None = None
        self._long_source_duration = 0.0
        super().__init__()

        self.reel_card.title_label.setText("1. ARARA REEL / ДЛИННАЯ ЗАПИСЬ")
        self.reel_card.hint_label.setText(
            "Короткий Reel собирается один раз. Запись длиннее 15 секунд автоматически "
            "переключает программу в режим порций без повторов."
        )

        self.batch_frame = QFrame()
        self.batch_frame.setObjectName("settingsPanel")
        batch_layout = QVBoxLayout(self.batch_frame)
        batch_layout.setContentsMargins(16, 13, 16, 13)
        batch_layout.setSpacing(9)

        title = QLabel("ПАКЕТНАЯ НАРЕЗКА ДЛИННОЙ ЗАПИСИ")
        title.setObjectName("cardTitle")
        batch_layout.addWidget(title)

        row = QHBoxLayout()
        row.addWidget(QLabel("Сделать сейчас:"))
        self.batch_limit = QSpinBox()
        self.batch_limit.setRange(1, 500)
        self.batch_limit.setValue(int(self.settings.value("batch_limit", 10)))
        self.batch_limit.setSuffix(" роликов")
        self.batch_limit.setMaximumWidth(145)
        self.batch_all = QCheckBox("Все оставшиеся")
        self.batch_all.setChecked(
            self.settings.value("batch_all_remaining", False, type=bool)
        )
        self.batch_limit.setDisabled(self.batch_all.isChecked())
        self.batch_all.toggled.connect(self.batch_limit.setDisabled)
        self.batch_limit.valueChanged.connect(self.save_preferences)
        self.batch_all.toggled.connect(self.save_preferences)
        row.addWidget(self.batch_limit)
        row.addWidget(self.batch_all)
        row.addStretch(1)
        batch_layout.addLayout(row)

        self.batch_status = QLabel(
            "Первый клик проанализирует паузы и сразу начнёт собирать выбранную порцию."
        )
        self.batch_status.setObjectName("libraryStatus")
        self.batch_status.setWordWrap(True)
        batch_layout.addWidget(self.batch_status)

        tools = QHBoxLayout()
        self.batch_reset = QPushButton("Сбросить прогресс записи")
        self.batch_reset.setMaximumWidth(205)
        self.batch_reset.clicked.connect(self.reset_batch_progress)
        tools.addWidget(self.batch_reset)
        tools.addStretch(1)
        batch_layout.addLayout(tools)

        main_layout = self.progress.parentWidget().layout()
        progress_index = main_layout.indexOf(self.progress)
        main_layout.insertWidget(progress_index, self.batch_frame)
        self.batch_frame.setVisible(False)
        self.refresh_ready_state()

    def inspect_reel(self, value: str) -> None:
        path = Path(value) if value else Path("__missing__")
        if not path.is_file():
            self.batch_mode = False
            self._long_source_duration = 0.0
            super().inspect_reel(value)
            self._sync_batch_ui()
            return

        try:
            info = self._probe(path)
            valid_long = (
                info.duration > MAX_REEL_SECONDS + 0.05
                and abs(info.width / info.height - 9 / 16) <= 0.015
                and info.has_audio
            )
        except Exception:
            valid_long = False

        if not valid_long:
            self.batch_mode = False
            self._long_source_duration = 0.0
            super().inspect_reel(value)
            self._sync_batch_ui()
            return

        self.batch_mode = True
        self._long_source_duration = float(info.duration)
        self.reel_valid = True
        self.reel_card.set_status(
            f"{info.width}×{info.height} · {info.duration / 60:.1f} мин · пакетный режим 9–15 сек",
            "ok",
        )
        self.preview_panel.load_file(path, autoplay=False, title="длинная запись ARARA")
        self._sync_batch_ui()
        self._refresh_batch_plan(path)
        self.refresh_ready_state()

    def _sync_batch_ui(self) -> None:
        if not hasattr(self, "batch_frame"):
            return
        self.batch_frame.setVisible(self.batch_mode)
        if self.batch_mode:
            self.render_button.setText("СОБРАТЬ ПОРЦИЮ")
            self.render_button.setMaximumWidth(250)
            self.preview_button.setText("ТЕСТ 5 СЕКУНД")
        else:
            self.render_button.setText("СОБРАТЬ ГОТОВЫЙ REEL")
            self.render_button.setMaximumWidth(300)
            self.preview_button.setText("ТЕСТ 5 СЕКУНД")

    def _refresh_batch_plan(self, source: Path | None = None) -> None:
        if not hasattr(self, "batch_status"):
            return
        source = source or Path(self.reel_card.path)
        if not source.is_file():
            self.batch_status.setText("Выбери длинную запись ARARA.")
            return
        plan = load_plan(source)
        if plan is None:
            estimated = max(1, int(self._long_source_duration / 12.0))
            self.batch_status.setText(
                f"Запись ещё не анализировалась · ориентировочно {estimated} роликов. "
                "Нажми «СОБРАТЬ ПОРЦИЮ» — анализ и сборка начнутся автоматически."
            )
            return
        self._show_batch_plan(plan)

    def _show_batch_plan(self, plan: BatchPlan) -> None:
        next_segment = plan.next_segment
        if next_segment is None:
            next_text = "вся запись обработана"
        else:
            next_text = f"следующий старт {format_timestamp(next_segment.start).replace('-', ':')}"
        self.batch_status.setText(
            f"Готово {plan.completed_count} из {len(plan.segments)} · "
            f"осталось {plan.remaining_count} · {next_text}"
        )

    def refresh_ready_state(self) -> None:
        super().refresh_ready_state()
        self._sync_batch_ui()
        if not self.batch_mode:
            return
        ready = self.reel_valid and self.brainrot_valid
        busy = bool(
            (self.render_worker and self.render_worker.isRunning())
            or (self.batch_worker and self.batch_worker.isRunning())
        )
        self.preview_button.setEnabled(ready and not busy)
        self.render_button.setEnabled(ready and not busy)
        if ready and not busy:
            self.status.setText(
                "Длинная запись готова · выбери размер порции и нажми «СОБРАТЬ ПОРЦИЮ»"
            )

    def start_render(self, preview: bool) -> None:
        if self.batch_mode and not preview:
            self.start_batch()
            return
        super().start_render(preview)

    def start_batch(self) -> None:
        source = Path(self.reel_card.path)
        brainrot = Path(self.brainrot_card.path)
        output = Path(self.output_picker.path)
        if not self.reel_valid or not self.brainrot_valid or not self.batch_mode:
            QMessageBox.warning(
                self,
                "Проверь файлы",
                "Нужны длинная вертикальная запись ARARA со звуком и длинный brainrot.",
            )
            return
        if not self.output_picker.path:
            QMessageBox.warning(self, "Нужна папка", "В настройках выбери папку результата.")
            return

        self.save_preferences()
        output.mkdir(parents=True, exist_ok=True)
        limit = 0 if self.batch_all.isChecked() else self.batch_limit.value()
        options = RenderOptions(
            variants=1,
            subtitle_y=self.subtitle_y.value(),
            font="Arial Black",
            encoder_preset="veryfast",
            crf=self.quality.value(),
            encoder_mode=str(self.encoder.currentData()),
            brainrot_zoom=self.zoom.value(),
            subtitles_enabled=self.subtitles_enabled.isChecked(),
        )

        self.preview_panel.player.pause()
        self.set_busy(True)
        self.log.clear()
        self.progress.setValue(0)
        amount = "все оставшиеся" if limit == 0 else str(limit)
        self.status.setText(
            f"Анализирую длинную запись и готовлю порцию: {amount}. Первый анализ может занять несколько минут…"
        )
        self.batch_worker = BatchRenderWorker(source, brainrot, output, limit, options)
        self.batch_worker.progressed.connect(self.on_progress)
        self.batch_worker.logged.connect(self.log.append)
        self.batch_worker.completed.connect(self.batch_done)
        self.batch_worker.failed.connect(self.batch_failed)
        self.batch_worker.start()

    def batch_done(self, files: list[str], plan: BatchPlan) -> None:
        self.batch_worker = None
        self.set_busy(False)
        self.progress.setValue(100)
        self._show_batch_plan(plan)
        self.inspect_brainrot()
        if not files:
            self.status.setText("Все фрагменты этой записи уже собраны")
            return

        result = Path(files[-1])
        self.preview_panel.load_file(
            result,
            autoplay=True,
            title=f"последний готовый Reel · порция {len(files)}",
            editable_source=False,
        )
        self.status.setText(
            f"Порция готова: {len(files)} роликов · прогресс сохранён после каждого файла"
        )
        if self.auto_open.isChecked():
            self.open_output()

    def batch_failed(self, error: str) -> None:
        self.batch_worker = None
        self.set_busy(False)
        self._refresh_batch_plan()
        self.status.setText(
            "Порция остановлена · уже готовые ролики и их прогресс сохранены"
        )
        self.log.setPlainText(error)
        self.log.setVisible(True)
        self.log_button.setText("Скрыть технический журнал")
        QMessageBox.critical(self, "Ошибка пакетной сборки", error.splitlines()[-1])

    def reset_batch_progress(self) -> None:
        source = Path(self.reel_card.path)
        if not source.is_file():
            return
        answer = QMessageBox.question(
            self,
            "Сбросить прогресс?",
            (
                "Программа забудет обработанные отрезки этой записи. Готовые файлы останутся, "
                "но следующая сборка снова начнётся с начала и может создать дубли."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            reset_progress(source)
            self._refresh_batch_plan(source)
            self.status.setText("Прогресс длинной записи сброшен")

    def save_preferences(self, *args) -> None:
        super().save_preferences(*args)
        if hasattr(self, "batch_limit"):
            self.settings.setValue("batch_limit", self.batch_limit.value())
            self.settings.setValue("batch_all_remaining", self.batch_all.isChecked())
            self.settings.sync()

    def set_busy(self, busy: bool) -> None:
        super().set_busy(busy)
        if hasattr(self, "batch_limit"):
            self.batch_limit.setDisabled(busy or self.batch_all.isChecked())
            self.batch_all.setDisabled(busy)
            self.batch_reset.setDisabled(busy)
        if busy and self.batch_mode:
            self.render_button.setEnabled(False)
            self.preview_button.setEnabled(False)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.batch_worker and self.batch_worker.isRunning():
            QMessageBox.information(
                self,
                "Идёт сборка",
                "Дождись завершения текущего ролика или порции. Прогресс сохраняется после каждого готового файла.",
            )
            event.ignore()
            return
        super().closeEvent(event)


def install(app_module) -> None:
    """Replace the original window class before app.main() creates it."""
    app_module.MainWindow = IntegratedBatchWindow
