from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .publishing import PLATFORM_LABELS, Platform, connect_youtube, platform_connected
from .publishing_ui import PublishingWindow
from .secure_store import load_credentials, update_platform_credentials
from .social_oauth import connect_instagram, connect_tiktok


class AccountConnectWorker(QThread):
    completed = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, platform: Platform, values: dict) -> None:
        super().__init__()
        self.platform = platform
        self.values = values

    def run(self) -> None:
        try:
            if self.platform == Platform.TIKTOK:
                result = connect_tiktok(
                    str(self.values.get("client_key") or ""),
                    str(self.values.get("client_secret") or ""),
                )
            elif self.platform == Platform.INSTAGRAM:
                result = connect_instagram(
                    str(self.values.get("app_id") or ""),
                    str(self.values.get("app_secret") or ""),
                    api_version=str(self.values.get("api_version") or "v25.0"),
                    port=int(self.values.get("port") or 8788),
                )
            elif self.platform == Platform.YOUTUBE:
                path = Path(str(self.values.get("path") or ""))
                if not path.is_file():
                    raise RuntimeError("Сначала выбери client_secret.json для YouTube.")
                result = connect_youtube(path)
            else:
                raise RuntimeError("Неизвестная платформа.")
            self.completed.emit(self.platform.value, result)
        except Exception:
            self.failed.emit(self.platform.value, traceback.format_exc())


class BrowserConnectionsDialog(QDialog):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Подключение платформ")
        self.resize(680, 520)
        self.workers: dict[str, AccountConnectWorker] = {}
        credentials = load_credentials()

        outer = QVBoxLayout(self)
        tabs = QTabWidget()
        outer.addWidget(tabs, 1)

        self._build_tiktok_tab(tabs, credentials.get(Platform.TIKTOK.value) or {})
        self._build_instagram_tab(tabs, credentials.get(Platform.INSTAGRAM.value) or {})
        self._build_youtube_tab(tabs, credentials.get(Platform.YOUTUBE.value) or {})

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Close
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).clicked.connect(self.save_settings)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self.refresh_statuses()

    def _build_tiktok_tab(self, tabs: QTabWidget, data: dict) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        form = QFormLayout()
        self.tt_key = QLineEdit(str(data.get("client_key") or ""))
        self.tt_secret = QLineEdit(str(data.get("client_secret") or ""))
        self.tt_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.tt_privacy = QComboBox()
        self.tt_privacy.addItem("Публично", "PUBLIC_TO_EVERYONE")
        self.tt_privacy.addItem("Только я", "SELF_ONLY")
        index = self.tt_privacy.findData(
            str(data.get("privacy_level") or "PUBLIC_TO_EVERYONE")
        )
        self.tt_privacy.setCurrentIndex(max(0, index))
        form.addRow("Client key", self.tt_key)
        form.addRow("Client secret", self.tt_secret)
        form.addRow("Видимость", self.tt_privacy)
        layout.addLayout(form)
        self.tt_connect = QPushButton("Подключить TikTok через браузер")
        self.tt_connect.clicked.connect(self.connect_tiktok_clicked)
        layout.addWidget(self.tt_connect)
        self.tt_status = QLabel()
        self.tt_status.setWordWrap(True)
        layout.addWidget(self.tt_status)
        note = QLabel(
            "В TikTok Developer App нужны Login Kit, Content Posting API и scope "
            "video.publish. До аудита TikTok публикации могут быть только приватными."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        tabs.addTab(tab, "TikTok")

    def _build_instagram_tab(self, tabs: QTabWidget, data: dict) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        form = QFormLayout()
        self.ig_app_id = QLineEdit(str(data.get("app_id") or ""))
        self.ig_app_secret = QLineEdit(str(data.get("app_secret") or ""))
        self.ig_app_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.ig_version = QLineEdit(str(data.get("api_version") or "v25.0"))
        self.ig_port = QSpinBox()
        self.ig_port.setRange(1025, 65535)
        self.ig_port.setValue(int(data.get("oauth_port") or 8788))
        form.addRow("Instagram App ID", self.ig_app_id)
        form.addRow("App Secret", self.ig_app_secret)
        form.addRow("Graph API", self.ig_version)
        form.addRow("Callback port", self.ig_port)
        layout.addLayout(form)
        self.ig_connect = QPushButton("Подключить Instagram через браузер")
        self.ig_connect.clicked.connect(self.connect_instagram_clicked)
        layout.addWidget(self.ig_connect)
        self.ig_status = QLabel()
        self.ig_status.setWordWrap(True)
        layout.addWidget(self.ig_status)
        note = QLabel(
            "Нужен профессиональный Instagram Business/Creator. В Meta Developer укажи "
            "redirect URI http://127.0.0.1:8788/callback/ и разрешения "
            "instagram_business_basic, instagram_business_content_publish."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        tabs.addTab(tab, "Instagram")

    def _build_youtube_tab(self, tabs: QTabWidget, data: dict) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        form = QFormLayout()
        self.yt_path = QLineEdit(str(data.get("client_secret_path") or ""))
        path_host = QWidget()
        path_row = QHBoxLayout(path_host)
        path_row.setContentsMargins(0, 0, 0, 0)
        path_row.addWidget(self.yt_path, 1)
        choose = QPushButton("Выбрать JSON")
        choose.clicked.connect(self.choose_youtube_json)
        path_row.addWidget(choose)
        self.yt_privacy = QComboBox()
        self.yt_privacy.addItem("Публично", "public")
        self.yt_privacy.addItem("По ссылке", "unlisted")
        self.yt_privacy.addItem("Приватно", "private")
        index = self.yt_privacy.findData(str(data.get("privacy_status") or "public"))
        self.yt_privacy.setCurrentIndex(max(0, index))
        form.addRow("OAuth client JSON", path_host)
        form.addRow("Видимость", self.yt_privacy)
        layout.addLayout(form)
        self.yt_connect = QPushButton("Подключить YouTube через браузер")
        self.yt_connect.clicked.connect(self.connect_youtube_clicked)
        layout.addWidget(self.yt_connect)
        self.yt_status = QLabel()
        self.yt_status.setWordWrap(True)
        layout.addWidget(self.yt_status)
        note = QLabel(
            "В Google Cloud включи YouTube Data API, создай Desktop OAuth Client и "
            "скачай client_secret.json. Неаудированный API-проект может загружать только приватно."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        tabs.addTab(tab, "YouTube")

    def refresh_statuses(self) -> None:
        credentials = load_credentials()
        tt = credentials.get(Platform.TIKTOK.value) or {}
        ig = credentials.get(Platform.INSTAGRAM.value) or {}
        yt = credentials.get(Platform.YOUTUBE.value) or {}
        self.tt_status.setText(
            "● Подключён: " + str(tt.get("display_name") or "TikTok")
            if tt.get("access_token")
            else "○ TikTok не подключён"
        )
        self.ig_status.setText(
            "● Подключён: @" + str(ig.get("username") or ig.get("ig_user_id") or "Instagram")
            if ig.get("access_token") and ig.get("ig_user_id")
            else "○ Instagram не подключён"
        )
        self.yt_status.setText(
            "● YouTube подключён" if yt.get("token") else "○ YouTube не подключён"
        )

    def _start_worker(
        self,
        platform: Platform,
        values: dict,
        button: QPushButton,
    ) -> None:
        current = self.workers.get(platform.value)
        if current and current.isRunning():
            return
        self.save_settings(show_message=False)
        button.setEnabled(False)
        button.setText("Ожидаю вход в браузере…")
        worker = AccountConnectWorker(platform, values)
        self.workers[platform.value] = worker
        worker.completed.connect(self.account_connected)
        worker.failed.connect(self.account_failed)
        worker.start()

    def connect_tiktok_clicked(self) -> None:
        self._start_worker(
            Platform.TIKTOK,
            {
                "client_key": self.tt_key.text().strip(),
                "client_secret": self.tt_secret.text().strip(),
            },
            self.tt_connect,
        )

    def connect_instagram_clicked(self) -> None:
        self._start_worker(
            Platform.INSTAGRAM,
            {
                "app_id": self.ig_app_id.text().strip(),
                "app_secret": self.ig_app_secret.text().strip(),
                "api_version": self.ig_version.text().strip() or "v25.0",
                "port": self.ig_port.value(),
            },
            self.ig_connect,
        )

    def choose_youtube_json(self) -> None:
        value = QFileDialog.getOpenFileName(
            self,
            "Выбрать Google OAuth client JSON",
            self.yt_path.text() or str(Path.home() / "Downloads"),
            "JSON (*.json)",
        )[0]
        if value:
            self.yt_path.setText(value)

    def connect_youtube_clicked(self) -> None:
        self._start_worker(
            Platform.YOUTUBE,
            {"path": self.yt_path.text().strip()},
            self.yt_connect,
        )

    def account_connected(self, platform_name: str, result: object) -> None:
        platform = Platform(platform_name)
        button = self._button(platform)
        button.setEnabled(True)
        button.setText(f"Переподключить {PLATFORM_LABELS[platform]}")
        self.save_settings(show_message=False)
        self.refresh_statuses()
        self.changed.emit()

    def account_failed(self, platform_name: str, error: str) -> None:
        platform = Platform(platform_name)
        button = self._button(platform)
        button.setEnabled(True)
        button.setText(f"Подключить {PLATFORM_LABELS[platform]} через браузер")
        QMessageBox.critical(
            self,
            f"Подключение {PLATFORM_LABELS[platform]}",
            error.splitlines()[-1],
        )

    def _button(self, platform: Platform) -> QPushButton:
        return {
            Platform.TIKTOK: self.tt_connect,
            Platform.INSTAGRAM: self.ig_connect,
            Platform.YOUTUBE: self.yt_connect,
        }[platform]

    def save_settings(self, *, show_message: bool = True) -> None:
        credentials = load_credentials()
        tiktok = dict(credentials.get(Platform.TIKTOK.value) or {})
        tiktok.update(
            {
                "client_key": self.tt_key.text().strip(),
                "client_secret": self.tt_secret.text().strip(),
                "privacy_level": self.tt_privacy.currentData(),
            }
        )
        update_platform_credentials(Platform.TIKTOK.value, tiktok)

        instagram = dict(credentials.get(Platform.INSTAGRAM.value) or {})
        instagram.update(
            {
                "app_id": self.ig_app_id.text().strip(),
                "app_secret": self.ig_app_secret.text().strip(),
                "api_version": self.ig_version.text().strip() or "v25.0",
                "oauth_port": self.ig_port.value(),
                "graph_host": "graph.instagram.com",
            }
        )
        update_platform_credentials(Platform.INSTAGRAM.value, instagram)

        youtube = dict(credentials.get(Platform.YOUTUBE.value) or {})
        youtube.update(
            {
                "client_secret_path": self.yt_path.text().strip(),
                "privacy_status": self.yt_privacy.currentData(),
            }
        )
        update_platform_credentials(Platform.YOUTUBE.value, youtube)
        self.changed.emit()
        if show_message:
            QMessageBox.information(self, "Сохранено", "Настройки подключений сохранены.")


class PublishingOAuthWindow(PublishingWindow):
    def open_connections(self) -> None:
        dialog = BrowserConnectionsDialog(self)
        dialog.changed.connect(self.refresh_connections)
        dialog.exec()
        self.refresh_connections()

    def refresh_connections(self) -> None:
        if not hasattr(self, "platform_labels"):
            return
        credentials = load_credentials()
        for platform, label in self.platform_labels.items():
            connected = platform_connected(platform)
            data = credentials.get(platform.value) or {}
            account = ""
            if platform == Platform.TIKTOK:
                account = str(data.get("display_name") or "")
            elif platform == Platform.INSTAGRAM:
                username = str(data.get("username") or "")
                account = "@" + username if username else ""
            label.setText(
                "● подключён" + (f" · {account}" if account else "")
                if connected
                else "○ не подключён"
            )
            label.setStyleSheet("color: #77d57a" if connected else "color: #8f857a")


def install(app_module) -> None:
    app_module.MainWindow = PublishingOAuthWindow
