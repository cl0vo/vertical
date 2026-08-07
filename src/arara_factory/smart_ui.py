from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .publishing import PLATFORM_LABELS, Platform, platform_connected
from .publishing_library_ui import PublishingLibraryWindow


class SmartMainWindow(PublishingLibraryWindow):
    """Final user-facing shell: one creation workflow and one publishing workflow."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"ARARA Factory {self.windowTitle().split()[-1]}")
        self.resize(1320, 860)
        self.setMinimumSize(1040, 700)
        self._rebuild_smart_layout()
        self._apply_smart_copy()
        self._apply_smart_style()
        self.refresh_connections()
        self.refresh_publish_status()

    # ------------------------------------------------------------------
    # Layout shell
    # ------------------------------------------------------------------
    def _rebuild_smart_layout(self) -> None:
        root = self.centralWidget()
        root_layout = root.layout()
        splitter = self.splitter
        left_scroll = splitter.widget(0)
        old_left = left_scroll.takeWidget()

        # Move global activity widgets before deleting the old left panel.
        activity = self._build_activity_bar()

        # Publishing widgets currently live inside the old left panel. Move all
        # interactive controls into a dedicated publishing page first.
        publish_page = self._build_publish_page()

        # Rebuild the creator column with the same proven render controls, just in
        # the order a user actually thinks about the task.
        creator = self._build_creator_panel()
        left_scroll.setWidget(creator)
        left_scroll.setMinimumWidth(535)
        left_scroll.setMaximumWidth(680)

        # Controls still referenced by the engine must remain alive even though
        # they are intentionally hidden from the main workflow.
        technical_host = QWidget(creator)
        technical_host.hide()
        hidden_layout = QVBoxLayout(technical_host)
        hidden_layout.setContentsMargins(0, 0, 0, 0)
        for widget in (
            self.prepare_button,
            self.reset_button,
            self.next_button,
            self.add_ready_button,
        ):
            widget.hide()
            hidden_layout.addWidget(widget)

        if old_left is not None:
            old_left.deleteLater()

        # Replace the old single long screen with two clearly separated jobs.
        root_layout.removeWidget(splitter)
        self.mode_tabs = QTabWidget()
        self.mode_tabs.setObjectName("modeTabs")
        self.mode_tabs.setDocumentMode(True)
        self.mode_tabs.setMovable(False)
        self.mode_tabs.addTab(splitter, "Создать Reels")
        self.mode_tabs.addTab(publish_page, "Опубликовать")
        saved_tab = int(self.settings.value("smart_tab", 0) or 0)
        self.mode_tabs.setCurrentIndex(1 if saved_tab == 1 else 0)
        self.mode_tabs.currentChanged.connect(self._mode_changed)

        root_layout.insertWidget(1, self.mode_tabs, 1)
        root_layout.addWidget(activity)

        splitter.setSizes([610, 600])
        self.preview_panel.setMinimumWidth(350)
        self.preview_panel.setMaximumWidth(520)
        self.preview_panel.title.setText("СЦЕНА BRAINROT")
        self.preview_panel.source_label.setText("перетащи рамку мышью")

    def _build_activity_bar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("activityBar")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 9, 14, 9)
        layout.setSpacing(5)

        top = QHBoxLayout()
        top.addWidget(self.status, 1)
        self.log_button.setMaximumWidth(190)
        top.addWidget(self.log_button)
        layout.addLayout(top)
        layout.addWidget(self.progress)
        layout.addWidget(self.log)
        self.log.setMaximumHeight(115)
        return frame

    # ------------------------------------------------------------------
    # Create page
    # ------------------------------------------------------------------
    def _build_creator_panel(self) -> QWidget:
        creator = QWidget()
        creator.setObjectName("smartCreator")
        main = QVBoxLayout(creator)
        main.setContentsMargins(6, 4, 16, 12)
        main.setSpacing(12)

        hero = QFrame()
        hero.setObjectName("workflowHero")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(16, 13, 16, 13)
        hero_layout.setSpacing(4)
        title = QLabel("СОЗДАТЬ REELS")
        title.setObjectName("workflowTitle")
        subtitle = QLabel(
            "Запись ARARA + длинный brainrot → готовая порция вертикальных роликов. "
            "Всё техническое программа делает сама."
        )
        subtitle.setObjectName("workflowHint")
        subtitle.setWordWrap(True)
        steps = QLabel("1  Запись     →     2  Brainrot     →     3  Порция     →     Готово")
        steps.setObjectName("stepLine")
        hero_layout.addWidget(title)
        hero_layout.addWidget(subtitle)
        hero_layout.addWidget(steps)
        main.addWidget(hero)

        main.addWidget(self.reel_card)
        main.addWidget(self.brainrot_card)

        self.library_status.setObjectName("subtleStatus")
        main.addWidget(self.library_status)

        # For long recordings the amount belongs before the action button.
        main.addWidget(self.batch_frame)

        action_card = QFrame()
        action_card.setObjectName("actionCard")
        action_layout = QVBoxLayout(action_card)
        action_layout.setContentsMargins(14, 12, 14, 12)
        action_layout.setSpacing(8)

        action_title = QLabel("ГОТОВО К СБОРКЕ")
        action_title.setObjectName("miniTitle")
        action_layout.addWidget(action_title)

        actions = QHBoxLayout()
        actions.setSpacing(9)
        self.preview_button.setMaximumWidth(155)
        self.render_button.setMaximumWidth(300)
        self.render_button.setMinimumWidth(190)
        actions.addWidget(self.preview_button)
        actions.addWidget(self.render_button)
        actions.addStretch(1)
        action_layout.addLayout(actions)

        secondary = QHBoxLayout()
        self.settings_button.setText("Настройки рендера")
        self.settings_button.setMaximumWidth(155)
        self.open_button.setText("Открыть готовые")
        self.open_button.setMaximumWidth(145)
        secondary.addWidget(self.settings_button)
        secondary.addWidget(self.open_button)
        secondary.addStretch(1)
        action_layout.addLayout(secondary)
        main.addWidget(action_card)

        main.addWidget(self.settings_panel)
        main.addStretch(1)
        return creator

    # ------------------------------------------------------------------
    # Publish page
    # ------------------------------------------------------------------
    def _build_publish_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("publishScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        page = QWidget()
        page.setObjectName("publishPage")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(30, 18, 30, 24)
        outer.setSpacing(14)

        content = QWidget()
        content.setObjectName("publishContent")
        content.setMaximumWidth(900)
        content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(14)

        hero = QFrame()
        hero.setObjectName("workflowHero")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(18, 14, 18, 14)
        title = QLabel("ОПУБЛИКОВАТЬ")
        title.setObjectName("workflowTitle")
        hint = QLabel(
            "Выбери готовые Reels пачкой → выбери платформы → задай задержку и интервал. "
            "Очередь помнит каждый файл и не создаёт повторов."
        )
        hint.setObjectName("workflowHint")
        hint.setWordWrap(True)
        steps = QLabel("1  Reels     →     2  Платформы     →     3  Расписание     →     Очередь")
        steps.setObjectName("stepLine")
        hero_layout.addWidget(title)
        hero_layout.addWidget(hint)
        hero_layout.addWidget(steps)
        content_layout.addWidget(hero)

        content_layout.addWidget(self._build_files_card())
        content_layout.addWidget(self._build_platforms_card())
        content_layout.addWidget(self._build_schedule_card())
        content_layout.addStretch(1)

        center = QHBoxLayout()
        center.addStretch(1)
        center.addWidget(content, 1)
        center.addStretch(1)
        outer.addLayout(center)
        scroll.setWidget(page)
        return scroll

    def _new_card(self, title_text: str, hint_text: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("smartCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 15, 18, 15)
        layout.setSpacing(10)
        title = QLabel(title_text)
        title.setObjectName("cardTitle")
        hint = QLabel(hint_text)
        hint.setObjectName("cardHint")
        hint.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(hint)
        return card, layout

    def _build_files_card(self) -> QFrame:
        card, layout = self._new_card(
            "1. ВЫБЕРИ ГОТОВЫЕ REELS",
            "Можно выделить сразу много видео в Проводнике или выбрать целую папку.",
        )

        buttons = QHBoxLayout()
        self.choose_reels_button.setText("Выбрать файлы")
        self.choose_reels_button.setMaximumWidth(150)
        self.choose_folder_button.setText("Выбрать папку")
        self.choose_folder_button.setMaximumWidth(150)
        self.clear_selection_button.setText("Очистить")
        self.clear_selection_button.setObjectName("linkButton")
        self.clear_selection_button.setMaximumWidth(90)
        buttons.addWidget(self.choose_reels_button)
        buttons.addWidget(self.choose_folder_button)
        buttons.addWidget(self.clear_selection_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        options = QHBoxLayout()
        options.addWidget(QLabel("Порядок"))
        self.order_combo.setMaximumWidth(180)
        options.addWidget(self.order_combo)
        options.addWidget(self.recursive_box)
        options.addStretch(1)
        layout.addLayout(options)

        self.selection_status.setObjectName("selectionStatus")
        layout.addWidget(self.selection_status)
        return card

    def _build_platforms_card(self) -> QFrame:
        card, layout = self._new_card(
            "2. КУДА ПОСТИТЬ",
            "Оставь отмеченными только нужные подключённые аккаунты. Сейчас можно работать только с YouTube.",
        )

        head = QHBoxLayout()
        account_hint = QLabel("Аккаунты")
        account_hint.setObjectName("miniTitle")
        head.addWidget(account_hint)
        head.addStretch(1)
        self.connections_button.setText("Подключения")
        self.connections_button.setMaximumWidth(130)
        head.addWidget(self.connections_button)
        layout.addLayout(head)

        platforms = QGridLayout()
        platforms.setHorizontalSpacing(18)
        for column, platform in enumerate(Platform):
            box = self.platform_boxes[platform]
            label = self.platform_labels[platform]
            box.setText(PLATFORM_LABELS[platform])
            box.setMinimumWidth(150)
            label.setObjectName("connectionState")
            platforms.addWidget(box, 0, column)
            platforms.addWidget(label, 1, column)
            platforms.setColumnStretch(column, 1)
        layout.addLayout(platforms)

        caption_label = QLabel("Подпись и хэштеги")
        caption_label.setObjectName("miniTitle")
        layout.addWidget(caption_label)
        self.caption.setMaximumHeight(96)
        self.caption.setPlaceholderText("Например: ARARA RARA RARARA\n#arara #gaming #shorts")
        layout.addWidget(self.caption)
        return card

    def _build_schedule_card(self) -> QFrame:
        card, layout = self._new_card(
            "3. РАСПИСАНИЕ",
            "Задержка относится к первому ролику. Остальные публикуются через выбранный интервал.",
        )

        schedule = QGridLayout()
        schedule.setHorizontalSpacing(12)
        schedule.setVerticalSpacing(7)
        schedule.addWidget(QLabel("Первый пост через"), 0, 0)
        self.delay_minutes.setMaximumWidth(145)
        schedule.addWidget(self.delay_minutes, 0, 1)
        schedule.addWidget(QLabel("Между роликами"), 0, 2)
        self.interval.setMaximumWidth(145)
        schedule.addWidget(self.interval, 0, 3)
        schedule.setColumnStretch(4, 1)
        layout.addLayout(schedule)

        self.auto_queue.setText("Новые Reels после рендера автоматически добавлять в очередь")
        layout.addWidget(self.auto_queue)

        primary = QHBoxLayout()
        self.schedule_selected_button.setText("ДОБАВИТЬ В ОЧЕРЕДЬ")
        self.schedule_selected_button.setMaximumWidth(245)
        self.schedule_selected_button.setMinimumWidth(210)
        primary.addWidget(self.schedule_selected_button)
        primary.addStretch(1)
        layout.addLayout(primary)

        queue_box = QFrame()
        queue_box.setObjectName("queueBox")
        queue_layout = QVBoxLayout(queue_box)
        queue_layout.setContentsMargins(12, 10, 12, 10)
        queue_layout.setSpacing(7)

        queue_title = QHBoxLayout()
        label = QLabel("ОЧЕРЕДЬ ПОСТИНГА")
        label.setObjectName("miniTitle")
        queue_title.addWidget(label)
        queue_title.addStretch(1)
        self.publish_toggle.setMaximumWidth(190)
        self.retry_button.setMaximumWidth(145)
        queue_title.addWidget(self.publish_toggle)
        queue_title.addWidget(self.retry_button)
        queue_layout.addLayout(queue_title)
        queue_layout.addWidget(self.publish_status)
        layout.addWidget(queue_box)
        return card

    # ------------------------------------------------------------------
    # Smart state
    # ------------------------------------------------------------------
    def _mode_changed(self, index: int) -> None:
        self.settings.setValue("smart_tab", int(index))
        self.settings.sync()
        if index == 1:
            self.refresh_connections()
            self.refresh_publish_status()

    def _apply_smart_copy(self) -> None:
        self.reel_card.title_label.setText("1. ЗАПИСЬ ARARA")
        self.reel_card.hint_label.setText(
            "Короткий Reel соберётся один раз. Длинная запись автоматически режется на фрагменты 9–15 секунд."
        )
        self.brainrot_card.title_label.setText("2. BRAINROT")
        self.brainrot_card.hint_label.setText(
            "Выбери длинный фон один раз. Размер и положение меняются мышью справа и применяются ко всей порции."
        )
        self.library_status.setText("Участки brainrot выбираются автоматически без повторов")

        batch_layout = self.batch_frame.layout()
        if batch_layout and batch_layout.count():
            first = batch_layout.itemAt(0).widget()
            if isinstance(first, QLabel):
                first.setText("3. ПОРЦИЯ")
        self.batch_reset.setText("Сбросить прогресс записи")
        self.batch_reset.setMaximumWidth(180)

    def refresh_connections(self) -> None:
        super().refresh_connections()
        if not hasattr(self, "platform_boxes"):
            return
        for platform, box in self.platform_boxes.items():
            connected = platform_connected(platform)
            box.setEnabled(connected)
            if not connected:
                box.setChecked(False)
            box.setToolTip(
                "Аккаунт подключён" if connected else "Сначала открой «Подключения»"
            )

    def refresh_publish_status(self) -> None:
        super().refresh_publish_status()
        if hasattr(self, "mode_tabs"):
            remaining = self.publish_queue.remaining
            self.mode_tabs.setTabText(
                1,
                f"Опубликовать · {remaining}" if remaining else "Опубликовать",
            )

    def _apply_smart_style(self) -> None:
        self.setStyleSheet(
            """
QTabWidget#modeTabs::pane {
    border: 1px solid #35291f;
    border-radius: 14px;
    background: #09080b;
    top: -1px;
}
QTabWidget#modeTabs QTabBar::tab {
    background: #121015;
    color: #9f9385;
    border: 1px solid #35291f;
    border-bottom: none;
    padding: 11px 24px;
    min-width: 155px;
    font-size: 14px;
    font-weight: 750;
    margin-right: 5px;
    border-top-left-radius: 9px;
    border-top-right-radius: 9px;
}
QTabWidget#modeTabs QTabBar::tab:selected {
    background: #21180f;
    color: #f1c36d;
    border-color: #7b582c;
}
QWidget#smartCreator, QScrollArea#publishScroll, QWidget#publishPage {
    background: #09080b;
}
QWidget#publishContent { background: transparent; }
QFrame#workflowHero {
    background: #111014;
    border: 1px solid #3e3024;
    border-radius: 13px;
}
QLabel#workflowTitle {
    color: #f0b64e;
    font-size: 24px;
    font-weight: 900;
    letter-spacing: 1px;
}
QLabel#workflowHint { color: #b1a596; font-size: 13px; }
QLabel#stepLine { color: #806f5b; font-size: 12px; padding-top: 5px; }
QFrame#smartCard, QFrame#actionCard {
    background: #131015;
    border: 1px solid #4e3a27;
    border-radius: 13px;
}
QFrame#smartCard:hover { border-color: #6a4c29; }
QFrame#queueBox {
    background: #0d0b0e;
    border: 1px solid #34291f;
    border-radius: 9px;
}
QLabel#miniTitle { color: #d9b06a; font-size: 12px; font-weight: 800; }
QLabel#selectionStatus {
    color: #c1b39f;
    background: #0c0a0d;
    border: 1px solid #30261e;
    border-radius: 7px;
    padding: 8px 10px;
}
QLabel#connectionState { color: #8f857a; font-size: 11px; }
QLabel#subtleStatus { color: #8e806f; font-size: 11px; padding: 0 4px; }
QFrame#activityBar {
    background: #100d11;
    border: 1px solid #33271d;
    border-radius: 10px;
}
QPushButton#generate {
    border-radius: 8px;
    padding: 9px 15px;
}
QPushButton#linkButton { padding: 5px 7px; }
"""
        )


def install(app_module) -> None:
    app_module.MainWindow = SmartMainWindow
