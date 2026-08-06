from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtMultimedia import QMediaPlayer, QVideoFrame

from .preview import PreviewPanel


def install_preview_preroll() -> None:
    """Patch PreviewPanel so paused source previews still decode frame zero.

    QMediaPlayer does not necessarily decode a frame after setSource() until
    playback starts. The scene editor normally opens source recordings paused,
    which previously left the canvas on "Загружаю видео…" forever while the
    separate brainrot player was already visible.
    """
    if getattr(PreviewPanel, "_arara_preroll_installed", False):
        return

    original_init = PreviewPanel.__init__
    original_load_file = PreviewPanel.load_file
    original_clear = PreviewPanel.clear

    def patched_init(self: PreviewPanel) -> None:
        original_init(self)
        self._arara_preroll_pending = False
        self._arara_preroll_generation = 0
        self._arara_preroll_previous_muted = False
        self._arara_preroll_frame_seen = False
        self.sink.videoFrameChanged.connect(
            lambda frame, panel=self: _first_frame_arrived(panel, frame)
        )
        self.player.errorOccurred.connect(
            lambda *args, panel=self: _media_error(panel, *args)
        )

    def patched_load_file(
        self: PreviewPanel,
        path: Path,
        *,
        autoplay: bool,
        title: str,
        editable_source: bool | None = None,
    ) -> None:
        self._arara_preroll_generation += 1
        generation = self._arara_preroll_generation
        self._arara_preroll_pending = not autoplay
        self._arara_preroll_frame_seen = False
        self._arara_preroll_previous_muted = self.audio.isMuted()

        # Prevent a tiny audio click while decoding the first paused frame.
        if not autoplay:
            self.audio.setMuted(True)

        # Always start playback once. For non-autoplay previews the callback
        # below pauses both layers immediately after the first valid frame.
        original_load_file(
            self,
            path,
            autoplay=True,
            title=title,
            editable_source=editable_source,
        )

        if not autoplay:
            QTimer.singleShot(
                4500,
                lambda panel=self, token=generation: _preroll_watchdog(panel, token),
            )

    def patched_clear(self: PreviewPanel, placeholder: str | None = None) -> None:
        self._arara_preroll_generation += 1
        self._arara_preroll_pending = False
        self._arara_preroll_frame_seen = False
        if hasattr(self, "_arara_preroll_previous_muted"):
            self.audio.setMuted(self._arara_preroll_previous_muted)
        original_clear(self, placeholder)

    PreviewPanel.__init__ = patched_init
    PreviewPanel.load_file = patched_load_file
    PreviewPanel.clear = patched_clear
    PreviewPanel._arara_preroll_installed = True


def _first_frame_arrived(panel: PreviewPanel, frame: QVideoFrame) -> None:
    if not getattr(panel, "_arara_preroll_pending", False):
        return
    if not frame.isValid():
        return
    image = frame.toImage()
    if image.isNull():
        return

    panel._arara_preroll_frame_seen = True
    generation = panel._arara_preroll_generation
    QTimer.singleShot(
        0,
        lambda current=panel, token=generation: _finish_preroll(current, token),
    )


def _finish_preroll(panel: PreviewPanel, generation: int) -> None:
    if generation != getattr(panel, "_arara_preroll_generation", -1):
        return
    if not getattr(panel, "_arara_preroll_pending", False):
        return

    panel._arara_preroll_pending = False
    panel.player.pause()
    panel.player.setPosition(0)

    if getattr(panel, "_editable_source", False):
        panel.brain_player.pause()
        panel.brain_player.setPosition(0)

    panel.audio.setMuted(panel._arara_preroll_previous_muted)
    panel.play_button.setText("▶")
    panel.time_label.setText(
        f"00:00 / {panel._format_time(panel.player.duration())}"
    )


def _preroll_watchdog(panel: PreviewPanel, generation: int) -> None:
    if generation != getattr(panel, "_arara_preroll_generation", -1):
        return
    if not getattr(panel, "_arara_preroll_pending", False):
        return

    # One retry handles media backends that need a seek after LoadedMedia.
    if not getattr(panel, "_arara_preroll_frame_seen", False):
        panel.player.setPosition(1)
        panel.player.play()
        if getattr(panel, "_editable_source", False) and panel._brain_path:
            panel.brain_player.setPosition(0)
            panel.brain_player.play()
        QTimer.singleShot(
            3500,
            lambda current=panel, token=generation: _final_watchdog(current, token),
        )


def _final_watchdog(panel: PreviewPanel, generation: int) -> None:
    if generation != getattr(panel, "_arara_preroll_generation", -1):
        return
    if not getattr(panel, "_arara_preroll_pending", False):
        return

    panel._arara_preroll_pending = False
    panel.audio.setMuted(panel._arara_preroll_previous_muted)
    panel.player.pause()
    if getattr(panel, "_editable_source", False):
        panel.brain_player.pause()
    panel.canvas.clear(
        "Qt не отдал первый кадр. Нажми ▶ — рендер и нарезка при этом работают."
    )
    panel.source_label.setText("кадр предпросмотра не загрузился")


def _media_error(panel: PreviewPanel, *args: Any) -> None:
    if not getattr(panel, "_arara_preroll_pending", False):
        return
    panel._arara_preroll_pending = False
    panel.audio.setMuted(panel._arara_preroll_previous_muted)
    message = panel.player.errorString().strip() or "неизвестная ошибка медиаплеера"
    panel.canvas.clear(f"Не удалось открыть Reel в предпросмотре:\n{message}")
    panel.source_label.setText("ошибка предпросмотра")
