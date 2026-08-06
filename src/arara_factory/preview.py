from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoFrame, QVideoSink
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .geometry import canonical_layout


class PreviewCanvas(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._image = QImage()
        self._guides = True
        self._placeholder = "Сделай тест 5 секунд — результат появится здесь"
        self.setMinimumSize(300, 500)
        self.setObjectName("previewCanvas")

    def set_frame(self, frame: QVideoFrame) -> None:
        if not frame.isValid():
            return
        image = frame.toImage()
        if not image.isNull():
            self._image = image.copy()
            self.update()

    def set_guides(self, enabled: bool) -> None:
        self._guides = enabled
        self.update()

    def clear(self, placeholder: str | None = None) -> None:
        self._image = QImage()
        if placeholder:
            self._placeholder = placeholder
        self.update()

    def _video_rect(self) -> QRectF:
        area = QRectF(self.rect()).adjusted(14, 14, -14, -14)
        aspect = 9 / 16
        if area.width() / max(area.height(), 1) > aspect:
            height = area.height()
            width = height * aspect
        else:
            width = area.width()
            height = width / aspect
        return QRectF(
            area.center().x() - width / 2,
            area.center().y() - height / 2,
            width,
            height,
        )

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), QColor("#070609"))
        target = self._video_rect()

        if not self._image.isNull():
            painter.drawImage(target, self._image)
        else:
            painter.fillRect(target, QColor("#0e0c10"))
            painter.setPen(QColor("#7f7467"))
            painter.setFont(QFont("Segoe UI", 11))
            painter.drawText(
                target.adjusted(22, 22, -22, -22),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                self._placeholder,
            )

        painter.setPen(QPen(QColor("#5b4327"), 2))
        painter.drawRoundedRect(target, 10, 10)

        if self._guides:
            self._draw_guides(painter, target)

    def _draw_guides(self, painter: QPainter, target: QRectF) -> None:
        main, brain = canonical_layout(1080, 1920)
        scale_x = target.width() / 1080
        scale_y = target.height() / 1920

        def mapped(rect) -> QRectF:
            return QRectF(
                target.left() + rect.x * scale_x,
                target.top() + rect.y * scale_y,
                rect.width * scale_x,
                rect.height * scale_y,
            )

        painter.save()
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))

        main_rect = mapped(main)
        painter.fillRect(main_rect, QColor(231, 173, 67, 24))
        painter.setPen(QPen(QColor("#e7ad43"), 1.5, Qt.PenStyle.DashLine))
        painter.drawRect(main_rect)
        self._draw_label(painter, main_rect, "REEL", QColor("#e7ad43"))

        brain_rect = mapped(brain)
        painter.fillRect(brain_rect, QColor(77, 255, 53, 24))
        painter.setPen(QPen(QColor("#4dff35"), 1.5, Qt.PenStyle.DashLine))
        painter.drawRect(brain_rect)
        self._draw_label(painter, brain_rect, "BRAINROT", QColor("#4dff35"))
        painter.restore()

    @staticmethod
    def _draw_label(painter: QPainter, rect: QRectF, text: str, color: QColor) -> None:
        label = QRectF(rect.left() + 5, rect.top() + 5, 72, 20)
        painter.fillRect(label, QColor(8, 7, 9, 205))
        painter.setPen(color)
        painter.drawText(label, Qt.AlignmentFlag.AlignCenter, text)


class PreviewPanel(QFrame):
    file_loaded = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("previewPanel")
        self.setMinimumWidth(340)
        self.setMaximumWidth(500)

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.65)
        self.sink = QVideoSink(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoSink(self.sink)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        self.title = QLabel("ПРЕДПРОСМОТР")
        self.title.setObjectName("previewTitle")
        self.source_label = QLabel("ожидает тест")
        self.source_label.setObjectName("previewSource")
        header.addWidget(self.title)
        header.addStretch(1)
        header.addWidget(self.source_label)
        layout.addLayout(header)

        self.canvas = PreviewCanvas()
        layout.addWidget(self.canvas, 1)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderMoved.connect(self.player.setPosition)
        layout.addWidget(self.slider)

        controls = QHBoxLayout()
        self.play_button = QPushButton("▶")
        self.play_button.setObjectName("mediaButton")
        self.play_button.setFixedWidth(44)
        self.play_button.clicked.connect(self.toggle_play)
        self.mute_button = QPushButton("Звук")
        self.mute_button.setObjectName("mediaButton")
        self.mute_button.setFixedWidth(70)
        self.mute_button.clicked.connect(self.toggle_mute)
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setObjectName("previewTime")
        self.guides = QCheckBox("Показывать зоны")
        self.guides.setChecked(True)
        self.guides.toggled.connect(self.canvas.set_guides)

        controls.addWidget(self.play_button)
        controls.addWidget(self.mute_button)
        controls.addWidget(self.time_label)
        controls.addStretch(1)
        controls.addWidget(self.guides)
        layout.addLayout(controls)

        self.sink.videoFrameChanged.connect(self.canvas.set_frame)
        self.player.positionChanged.connect(self._position_changed)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.playbackStateChanged.connect(self._playback_changed)
        self.player.mediaStatusChanged.connect(self._media_status_changed)

    def load_file(self, path: Path, *, autoplay: bool, title: str) -> None:
        if not path.is_file():
            return
        self.player.stop()
        self.canvas.clear("Загружаю видео…")
        self.source_label.setText(title)
        self.player.setSource(QUrl.fromLocalFile(str(path.resolve())))
        self.file_loaded.emit(str(path))
        if autoplay:
            self.player.play()

    def clear(self, placeholder: str | None = None) -> None:
        self.player.stop()
        self.player.setSource(QUrl())
        self.source_label.setText("ожидает тест")
        self.slider.setRange(0, 0)
        self.time_label.setText("00:00 / 00:00")
        self.canvas.clear(placeholder)

    def toggle_play(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def toggle_mute(self) -> None:
        muted = not self.audio.isMuted()
        self.audio.setMuted(muted)
        self.mute_button.setText("Без звука" if muted else "Звук")

    def _position_changed(self, position: int) -> None:
        if not self.slider.isSliderDown():
            self.slider.setValue(position)
        self.time_label.setText(
            f"{self._format_time(position)} / {self._format_time(self.player.duration())}"
        )

    def _duration_changed(self, duration: int) -> None:
        self.slider.setRange(0, max(0, duration))
        self._position_changed(self.player.position())

    def _playback_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        self.play_button.setText(
            "Ⅱ" if state == QMediaPlayer.PlaybackState.PlayingState else "▶"
        )

    def _media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.player.setPosition(0)
            self.player.play()

    @staticmethod
    def _format_time(milliseconds: int) -> str:
        seconds = max(0, milliseconds // 1000)
        minutes, seconds = divmod(seconds, 60)
        return f"{minutes:02d}:{seconds:02d}"
