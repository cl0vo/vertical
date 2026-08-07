from __future__ import annotations

from pathlib import Path

from arara_factory.publishing import Platform, PublishQueue
from arara_factory.publishing_journal import append_publish_log, tail_publish_log
from arara_factory.publishing_reliable import (
    _create_upload_session,
    _http_error_message,
    _upload_file_resumable,
)
from arara_factory.publishing_reliable_ui import ReliablePublishWorker


def _video(tmp_path: Path, name: str = "reel.mp4", data: bytes = b"video") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


class FakeResponse:
    def __init__(self, status_code: int, *, headers=None, payload=None, text: str = "") -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


def test_persistent_publish_journal(tmp_path: Path, monkeypatch) -> None:
    log_path = tmp_path / "publishing.log"
    monkeypatch.setattr("arara_factory.publishing_journal.journal_path", lambda: log_path)
    line = append_publish_log("YouTube test diagnostic")
    assert "YouTube test diagnostic" in line
    assert "YouTube test diagnostic" in tail_publish_log()


def test_worker_persists_platform_error_in_queue_and_journal(tmp_path: Path, monkeypatch) -> None:
    log_path = tmp_path / "publishing.log"
    monkeypatch.setattr("arara_factory.publishing_journal.journal_path", lambda: log_path)
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


def test_create_youtube_resumable_session_returns_location() -> None:
    class Session:
        def post(self, url, **kwargs):
            assert "uploadType=resumable" in url
            assert kwargs["headers"]["X-Upload-Content-Length"] == "8"
            return FakeResponse(200, headers={"Location": "https://upload.example/session"})

    values = []
    location = _create_upload_session(
        Session(),
        {"snippet": {"title": "ARARA"}, "status": {"privacyStatus": "private"}},
        8,
        lambda value, text: values.append((value, text)),
    )
    assert location == "https://upload.example/session"
    assert values


def test_youtube_resumable_upload_advances_by_confirmed_ranges(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("arara_factory.publishing_reliable.YOUTUBE_CHUNK_SIZE", 4)
    video = _video(tmp_path, data=b"abcdefgh")
    ranges = []

    class Session:
        def put(self, url, *, data, headers, timeout):
            ranges.append(headers["Content-Range"])
            if len(ranges) == 1:
                return FakeResponse(308, headers={"Range": "bytes=0-3"})
            return FakeResponse(200, payload={"id": "yt-success"})

    result = _upload_file_resumable(
        Session(),
        "https://upload.example/session",
        video,
        lambda value, text: None,
    )
    assert result == "yt-success"
    assert ranges == ["bytes 0-3/8", "bytes 4-7/8"]


def test_youtube_timeout_queries_server_and_resumes_from_confirmed_byte(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("arara_factory.publishing_reliable.YOUTUBE_CHUNK_SIZE", 4)
    monkeypatch.setattr("arara_factory.publishing_reliable.time.sleep", lambda seconds: None)
    video = _video(tmp_path, data=b"abcdefgh")
    calls = []

    class Session:
        def put(self, url, *, data, headers, timeout):
            calls.append(headers["Content-Range"])
            if len(calls) == 1:
                # Simulate: Google received the first block, but our client never got the response.
                raise TimeoutError("read timed out")
            if len(calls) == 2:
                assert data == b""
                return FakeResponse(308, headers={"Range": "bytes=0-3"})
            assert data == b"efgh"
            return FakeResponse(200, payload={"id": "yt-after-timeout"})

    result = _upload_file_resumable(
        Session(),
        "https://upload.example/session",
        video,
        lambda value, text: None,
    )
    assert result == "yt-after-timeout"
    assert calls == ["bytes 0-3/8", "bytes */8", "bytes 4-7/8"]
