from __future__ import annotations

from pathlib import Path

from arara_factory.publishing import Platform, PublishQueue
from arara_factory.publishing_journal import append_publish_log, tail_publish_log
from arara_factory.publishing_reliable import _http_error_message
from arara_factory.publishing_reliable_ui import ReliablePublishWorker


def _video(tmp_path: Path, name: str = "reel.mp4") -> Path:
    path = tmp_path / name
    path.write_bytes(b"video")
    return path


def test_persistent_publish_journal(tmp_path: Path, monkeypatch) -> None:
    log_path = tmp_path / "publishing.log"
    monkeypatch.setattr("arara_factory.publishing_journal.journal_path", lambda: log_path)
    line = append_publish_log("YouTube test diagnostic")
    assert "YouTube test diagnostic" in line
    assert "YouTube test diagnostic" in tail_publish_log()


def test_worker_persists_platform_error_in_queue_and_journal(tmp_path: Path, monkeypatch) -> None:
    log_path = tmp_path / "publishing.log"
    monkeypatch.setattr("arara_factory.publishing_journal.journal_path", lambda: log_path)
    # publishing_reliable_ui imported append_publish_log directly; patch that binding too.
    monkeypatch.setattr(
        "arara_factory.publishing_reliable_ui.append_publish_log",
        append_publish_log,
    )

    queue = PublishQueue(tmp_path / "queue.json")
    video = _video(tmp_path)
    job = queue.enqueue(
        [video],
        [Platform.YOUTUBE],
        "ARARA",
        15,
        start_at=1.0,
    )[0]

    def fail_publish(platform, video, caption, progress):
        progress(10, "YouTube · подключаю API")
        raise RuntimeError("YouTube HTTP 403: quotaExceeded")

    monkeypatch.setattr(
        "arara_factory.publishing_reliable_ui.publish_platform_reliable",
        fail_publish,
    )

    worker = ReliablePublishWorker(queue, job)
    worker.run()

    restored = PublishQueue(tmp_path / "queue.json").jobs[0]
    state = restored.deliveries[Platform.YOUTUBE.value]
    assert state.status == "failed"
    assert "quotaExceeded" in state.error
    journal = tail_publish_log()
    assert "ОШИБКА" in journal
    assert "quotaExceeded" in journal


def test_failed_job_does_not_turn_back_to_pending_automatically(tmp_path: Path) -> None:
    queue = PublishQueue(tmp_path / "queue.json")
    first = _video(tmp_path, "first.mp4")
    second = _video(tmp_path, "second.mp4")
    jobs = queue.enqueue(
        [first, second],
        [Platform.YOUTUBE],
        "ARARA",
        15,
        start_at=1.0,
    )
    queue.update_delivery(
        jobs[0],
        Platform.YOUTUBE,
        status="failed",
        error="test",
    )
    assert jobs[0].deliveries["youtube"].status == "failed"
    assert jobs[1].deliveries["youtube"].status == "pending"


def test_http_error_message_extracts_youtube_reason() -> None:
    class Response:
        status = 403

    class FakeError(Exception):
        resp = Response()
        content = b'{"error":{"message":"Quota exceeded","errors":[{"reason":"quotaExceeded"}]}}'

    assert _http_error_message(FakeError()) == "YouTube HTTP 403: quotaExceeded"
