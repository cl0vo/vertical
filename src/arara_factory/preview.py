from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QImage, QMouseEvent, QPainter, QPen
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

from .geometry import (
    DEFAULT_BRAINROT_TRANSFORM,
    NormalizedRect,
    canonical_layout,
    clamp_normalized_rect,
)
from .scene_state import (
    load_brainrot_transform,
    save_brainrot_transform,
    saved_brainrot_path,
)


class PreviewCanvas(QWidget):
    transform_changed = Signal(float, float, float, float)

    def __init__(self) -> None:
        super().__init__()
        self._image = QImage()
        self._brain_image = QImage()
        self._guides = True
        self._edit_enabled = True
        self._source_mode = False
        self._brain_zoom = 1.25
        self._transform = load_brainrot_transform()
        self._placeholder = "Сделай тест 5 секунд — результат появится здесь"
        self._drag_mode: str | None = None
        self._press_pos = QPointF()
        self._press_transform = self._transform
        self.setMinimumSize(300, 500)
        self.setMouseTracking(True)
        self.setObjectName("previewCanvas")

    def set_frame(self, frame: QVideoFrame) -> None:
        if not frame.isValid():
            return
        image = frame.toImage()
        if not image.isNull():
            self._image = image.copy()
            self.update()

    def set_brain_frame(self, frame: QVideoFrame) -> None:
        if not frame.isValid():
            return
        image = frame.toImage()
        if not image.isNull():
            self._brain_image = image.copy()
            self.update()

    def set_guides(self, enabled: bool) -> None:
        self._guides = enabled
        self.update()

    def set_edit_enabled(self, enabled: bool) -> None:
        self._edit_enabled = enabled
        self.update()

    def set_source_mode(self, enabled: bool) -> None:
        self._source_mode = enabled
        self.update()

    def set_brain_zoom(self, zoom: float) -> None:
        self._brain_zoom = max(1.0, min(1.5, float(zoom)))
        self.update()

    def set_brain_transform(self, rect: NormalizedRect, *, emit: bool = False) -> None:
        self._transform = clamp_normalized_rect(rect)
        self.update()
        if emit:
            self.transform_changed.emit(
                self._transform.x,
                self._transform.y,
                self._transform.width,
                self._transform.height,
            )

    def brain_transform(self) -> NormalizedRect:
        return self._transform

    def reset_brain_transform(self) -> None:
        self.set_brain_transform(DEFAULT_BRAINROT_TRANSFORM, emit=True)

    def clear(self, placeholder: str | None = None) -> None:
        self._image = QImage()
        if placeholder:
            self._placeholder = placeholder
        self.update()

    def clear_brainrot(self) -> None:
        self._brain_image = QImage()
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

    def _mapped_transform(self, target: QRectF) -> QRectF:
        rect = self._transform
        return QRectF(
            target.left() + rect.x * target.width(),
            target.top() + rect.y * target.height(),
            rect.width * target.width(),
            rect.height * target.height(),
        )

    def _draw_brainrot(self, painter: QPainter, destination: QRectF) -> None:
        if self._brain_image.isNull() or destination.isEmpty():
            painter.fillRect(destination, QColor("#161118"))
            return

        source_width = float(self._brain_image.width())
        source_height = float(self._brain_image.height())
        target_aspect = destination.width() / max(destination.height(), 1.0)
        source_aspect = source_width / max(source_height, 1.0)

        if source_aspect >= target_aspect:
            crop_height = source_height
            crop_width = crop_height * target_aspect
        else:
            crop_width = source_width
            crop_height = crop_width / target_aspect

        crop_width /= self._brain_zoom
        crop_height /= self._brain_zoom
        source = QRectF(
            (source_width - crop_width) / 2,
            (source_height - crop_height) / 2,
            crop_width,
            crop_height,
        )
        painter.drawImage(destination, self._brain_image, source)

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

        if self._source_mode:
            self._draw_brainrot(painter, self._mapped_transform(target))

        painter.setPen(QPen(QColor("#5b4327"), 2))
        painter.drawRoundedRect(target, 10, 10)

        if self._guides:
            self._draw_guides(painter, target)
        if self._source_mode and self._edit_enabled:
            self._draw_transform_handles(painter, self._mapped_transform(target))

    def _draw_guides(self, painter: QPainter, target: QRectF) -> None:
        main, _ = canonical_layout(1080, 1920)
        scale_x = target.width() / 1080
        scale_y = target.height() / 1920
        main_rect = QRectF(
            target.left() + main.x * scale_x,
            target.top() + main.y * scale_y,
            main.width * scale_x,
            main.height * scale_y,
        )

        painter.save()
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        painter.fillRect(main_rect, QColor(231, 173, 67, 20))
        painter.setPen(QPen(QColor("#e7ad43"), 1.3, Qt.PenStyle.DashLine))
        painter.drawRect(main_rect)
        self._draw_label(painter, main_rect, "REEL", QColor("#e7ad43"))

        brain_rect = self._mapped_transform(target)
        painter.fillRect(brain_rect, QColor(77, 255, 53, 18))
        painter.setPen(QPen(QColor("#4dff35"), 1.5, Qt.PenStyle.DashLine))
        painter.drawRect(brain_rect)
        self._draw_label(painter, brain_rect, "BRAINROT", QColor("#4dff35"))
        painter.restore()

    def _handle_rects(self, rect: QRectF) -> dict[str, QRectF]:
        size = 10.0
        half = size / 2
        points = {
            "nw": rect.topLeft(),
            "n": QPointF(rect.center().x(), rect.top()),
            "ne": rect.topRight(),
            "e": QPointF(rect.right(), rect.center().y()),
            "se": rect.bottomRight(),
            "s": QPointF(rect.center().x(), rect.bottom()),
            "sw": rect.bottomLeft(),
            "w": QPointF(rect.left(), rect.center().y()),
        }
        return {
            name: QRectF(point.x() - half, point.y() - half, size, size)
            for name, point in points.items()
        }

    def _draw_transform_handles(self, painter: QPainter, rect: QRectF) -> None:
        painter.save()
        painter.setPen(QPen(QColor("#4dff35"), 2))
        painter.drawRect(rect)
        for handle in self._handle_rects(rect).values():
            painter.fillRect(handle, QColor("#f7fff4"))
            painter.setPen(QPen(QColor("#151117"), 1))
            painter.drawRect(handle)
        painter.restore()

    @staticmethod
    def _draw_label(painter: QPainter, rect: QRectF, text: str, color: QColor) -> None:
        label = QRectF(rect.left() + 5, rect.top() + 5, 78, 20)
        painter.fillRect(label, QColor(8, 7, 9, 205))
        painter.setPen(color)
        painter.drawText(label, Qt.AlignmentFlag.AlignCenter, text)

    def _hit_mode(self, position: QPointF, rect: QRectF) -> str | None:
        for name, handle in self._handle_rects(rect).items():
            if handle.adjusted(-4, -4, 4, 4).contains(position):
                return name
        if rect.contains(position):
            return "move"
        return None

    def _set_cursor_for_mode(self, mode: str | None) -> None:
        cursors = {
            "move": Qt.CursorShape.SizeAllCursor,
            "n": Qt.CursorShape.SizeVerCursor,
            "s": Qt.CursorShape.SizeVerCursor,
            "e": Qt.CursorShape.SizeHorCursor,
            "w": Qt.CursorShape.SizeHorCursor,
            "nw": Qt.CursorShape.SizeFDiagCursor,
            "se": Qt.CursorShape.SizeFDiagCursor,
            "ne": Qt.CursorShape.SizeBDiagCursor,
            "sw": Qt.CursorShape.SizeBDiagCursor,
        }
        self.setCursor(cursors.get(mode, Qt.CursorShape.ArrowCursor))

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if (
            event.button() != Qt.MouseButton.LeftButton
            or not self._source_mode
            or not self._edit_enabled
        ):
            return super().mousePressEvent(event)
        target = self._video_rect()
        mode = self._hit_mode(event.position(), self._mapped_transform(target))
        if mode is None:
            return super().mousePressEvent(event)
        self._drag_mode = mode
        self._press_pos = event.position()
        self._press_transform = self._transform
        self._set_cursor_for_mode(mode)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        target = self._video_rect()
        if not self._drag_mode:
            if self._source_mode and self._edit_enabled:
                self._set_cursor_for_mode(
                    self._hit_mode(event.position(), self._mapped_transform(target))
                )
            return super().mouseMoveEvent(event)

        dx = (event.position().x() - self._press_pos.x()) / max(target.width(), 1.0)
        dy = (event.position().y() - self._press_pos.y()) / max(target.height(), 1.0)
        start = self._press_transform
        x, y, width, height = start.x, start.y, start.width, start.height
        mode = self._drag_mode

        if mode == "move":
            x += dx
            y += dy
        else:
            if "w" in mode:
                x += dx
                width -= dx
            if "e" in mode:
                width += dx
            if "n" in mode:
                y += dy
                height -= dy
            if "s" in mode:
                height += dy

        self._transform = clamp_normalized_rect(NormalizedRect(x, y, width, height))
        self.transform_changed.emit(
            self._transform.x,
            self._transform.y,
            self._transform.width,
            self._transform.height,
        )
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._drag_mode:
            self._drag_mode = None
            self._set_cursor_for_mode(None)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class PreviewPanel(QFrame):
    file_loaded = Signal(str)
    transform_changed = Signal(float, float, float, float)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("previewPanel")
        self.setMinimumWidth(340)
        self.setMaximumWidth(540)
        self._editable_source = False
        self._brain_path: Path | None = None

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.65)
        self.sink = QVideoSink(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoSink(self.sink)

        self.brain_player = QMediaPlayer(self)
        self.brain_sink = QVideoSink(self)
        self.brain_player.setVideoSink(self.brain_sink)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        self.title = QLabel("ПРЕДПРОСМОТР / СЦЕНА")
        self.title.setObjectName("previewTitle")
        self.source_label = QLabel("ожидает видео")
        self.source_label.setObjectName("previewSource")
        header.addWidget(self.title)
        header.addStretch(1)
        header.addWidget(self.source_label)
        layout.addLayout(header)

        self.canvas = PreviewCanvas()
        self.canvas.transform_changed.connect(self._on_transform_changed)
        layout.addWidget(self.canvas, 1)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderMoved.connect(self._seek)
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
        self.guides = QCheckBox("Зоны")
        self.guides.setChecked(True)
        self.guides.toggled.connect(self.canvas.set_guides)

        controls.addWidget(self.play_button)
        controls.addWidget(self.mute_button)
        controls.addWidget(self.time_label)
        controls.addStretch(1)
        controls.addWidget(self.guides)
        layout.addLayout(controls)

        editor_controls = QHBoxLayout()
        self.edit_box = QCheckBox("Редактировать brainrot")
        self.edit_box.setChecked(True)
        self.edit_box.toggled.connect(self.canvas.set_edit_enabled)
        self.batch_button = QPushButton("Резать пачку")
        self.batch_button.setObjectName("mediaButton")
        self.batch_button.clicked.connect(self._open_batch_mode)
        self.reset_button = QPushButton("Во всю нижнюю треть")
        self.reset_button.setObjectName("mediaButton")
        self.reset_button.clicked.connect(self.canvas.reset_brain_transform)
        editor_controls.addWidget(self.edit_box)
        editor_controls.addStretch(1)
        editor_controls.addWidget(self.batch_button)
        editor_controls.addWidget(self.reset_button)
        layout.addLayout(editor_controls)

        self.sink.videoFrameChanged.connect(self.canvas.set_frame)
        self.brain_sink.videoFrameChanged.connect(self.canvas.set_brain_frame)
        self.player.positionChanged.connect(self._position_changed)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.playbackStateChanged.connect(self._playback_changed)
        self.player.mediaStatusChanged.connect(self._media_status_changed)
        self.brain_player.mediaStatusChanged.connect(self._brain_media_status_changed)

        self._brainrot_watch = QTimer(self)
        self._brainrot_watch.setInterval(800)
        self._brainrot_watch.timeout.connect(self._refresh_saved_brainrot)
        self._brainrot_watch.start()
        QTimer.singleShot(0, self._refresh_saved_brainrot)

    def _on_transform_changed(self, x: float, y: float, width: float, height: float) -> None:
        safe = save_brainrot_transform(NormalizedRect(x, y, width, height))
        self.transform_changed.emit(safe.x, safe.y, safe.width, safe.height)

    def set_brain_transform(self, rect: NormalizedRect) -> None:
        self.canvas.set_brain_transform(rect)
        save_brainrot_transform(rect)

    def brain_transform(self) -> NormalizedRect:
        return self.canvas.brain_transform()

    def set_brain_zoom(self, zoom: float) -> None:
        self.canvas.set_brain_zoom(zoom)

    def _refresh_saved_brainrot(self) -> None:
        path = saved_brainrot_path()
        if path is None:
            return
        resolved = path.resolve()
        if self._brain_path != resolved:
            self.load_brainrot(resolved)

    def load_brainrot(self, path: Path) -> None:
        if not path.is_file():
            self.brain_player.stop()
            self.brain_player.setSource(QUrl())
            self.canvas.clear_brainrot()
            self._brain_path = None
            return
        resolved = path.resolve()
        if self._brain_path == resolved and not self.canvas._brain_image.isNull():
            return
        self._brain_path = resolved
        self.brain_player.stop()
        self.brain_player.setSource(QUrl.fromLocalFile(str(self._brain_path)))
        self.brain_player.setPosition(0)
        self.brain_player.play()

    def load_file(
        self,
        path: Path,
        *,
        autoplay: bool,
        title: str,
        editable_source: bool | None = None,
    ) -> None:
        if not path.is_file():
            return
        if editable_source is None:
            lowered = title.lower()
            editable_source = not any(
                marker in lowered
                for marker in ("готов", "тест", "preview", "result", "последний")
            )
        self._refresh_saved_brainrot()
        self._editable_source = bool(editable_source)
        self.canvas.set_source_mode(self._editable_source)
        self.edit_box.setEnabled(self._editable_source)
        self.reset_button.setEnabled(self._editable_source)
        self.player.stop()
        self.canvas.clear("Загружаю видео…")
        self.source_label.setText(title)
        self.player.setSource(QUrl.fromLocalFile(str(path.resolve())))
        self.file_loaded.emit(str(path))
        if self._editable_source and self._brain_path:
            self.brain_player.play()
        if autoplay:
            self.player.play()

    def clear(self, placeholder: str | None = None) -> None:
        self.player.stop()
        self.player.setSource(QUrl())
        self._editable_source = False
        self.canvas.set_source_mode(False)
        self.source_label.setText("ожидает тест")
        self.slider.setRange(0, 0)
        self.time_label.setText("00:00 / 00:00")
        self.canvas.clear(placeholder)

    def toggle_play(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            if self._editable_source:
                self.brain_player.pause()
        else:
            self.player.play()
            if self._editable_source and self._brain_path:
                self.brain_player.play()

    def toggle_mute(self) -> None:
        muted = not self.audio.isMuted()
        self.audio.setMuted(muted)
        self.mute_button.setText("Без звука" if muted else "Звук")

    def _seek(self, position: int) -> None:
        self.player.setPosition(position)
        if self._editable_source and self.brain_player.duration() > 0:
            self.brain_player.setPosition(position % self.brain_player.duration())

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

    def _brain_media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.brain_player.setPosition(0)
            if self._editable_source:
                self.brain_player.play()

    def _open_batch_mode(self) -> None:
        try:
            if getattr(sys, "frozen", False):
                command = [sys.executable, "--batch"]
            else:
                command = [sys.executable, "-m", "arara_factory.batch_app"]
            subprocess.Popen(command, close_fds=True)
        except OSError:
            self.source_label.setText("не удалось открыть пакетный режим")

    @staticmethod
    def _format_time(milliseconds: int) -> str:
        seconds = max(0, milliseconds // 1000)
        minutes, seconds = divmod(seconds, 60)
        return f"{minutes:02d}:{seconds:02d}"
