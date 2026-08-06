from __future__ import annotations

from pathlib import Path

from arara_factory.publishing import (
    Platform,
    PublishQueue,
    publish_instagram,
    publish_tiktok,
)


def _video(tmp_path: Path, name: str = "reel.mp4", size: int = 1024) -> Path:
    path = tmp_path / name
    path.write_bytes(b"x" * size)
    return path


def test_queue_spaces_reels_by_at_least_fifteen_minutes(tmp_path: Path) -> None:
    queue = PublishQueue(tmp_path / "queue.json")
    first = _video(tmp_path, "one.mp4")
    second = _video(tmp_path, "two.mp4")
    jobs = queue.enqueue(
        [first, second],
        [Platform.TIKTOK, Platform.YOUTUBE],
        "ARARA {n} {filename}",
        5,
        start_at=1000.0,
    )
    assert len(jobs) == 2
    assert jobs[0].due_at == 1000.0
    assert jobs[1].due_at == 1900.0
    assert jobs[0].caption == "ARARA 1 one"


def test_new_batch_is_scheduled_after_existing_queue(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("arara_factory.publishing.time.time", lambda: 1000.0)
    queue = PublishQueue(tmp_path / "queue.json")
    first = _video(tmp_path, "one.mp4")
    second = _video(tmp_path, "two.mp4")
    queue.enqueue([first], [Platform.YOUTUBE], "ARARA", 15)
    added = queue.enqueue([second], [Platform.YOUTUBE], "ARARA", 15)
    assert added[0].due_at == 1900.0


def test_queue_never_readds_same_file_and_targets(tmp_path: Path) -> None:
    queue = PublishQueue(tmp_path / "queue.json")
    video = _video(tmp_path)
    first = queue.enqueue([video], [Platform.INSTAGRAM], "ARARA", 15)
    job = first[0]
    queue.update_delivery(job, Platform.INSTAGRAM, status="success", remote_id="ig1")
    second = queue.enqueue([video], [Platform.INSTAGRAM], "ARARA", 15)
    assert len(first) == 1
    assert second == []


def test_caption_keeps_unrelated_braces_without_format_error(tmp_path: Path) -> None:
    queue = PublishQueue(tmp_path / "queue.json")
    video = _video(tmp_path)
    job = queue.enqueue(
        [video],
        [Platform.YOUTUBE],
        "ARARA {n} {filename} text {not_a_variable}",
        15,
        start_at=1.0,
    )[0]
    assert job.caption == "ARARA 1 reel text {not_a_variable}"


def test_successful_platform_is_not_retried_after_other_platform_fails(tmp_path: Path) -> None:
    path = tmp_path / "queue.json"
    queue = PublishQueue(path)
    video = _video(tmp_path)
    job = queue.enqueue(
        [video],
        [Platform.TIKTOK, Platform.INSTAGRAM, Platform.YOUTUBE],
        "ARARA",
        15,
        start_at=1.0,
    )[0]
    queue.update_delivery(job, Platform.YOUTUBE, status="success", remote_id="yt123")
    queue.update_delivery(job, Platform.TIKTOK, status="failed", error="temporary")

    restored = PublishQueue(path)
    restored_job = restored.jobs[0]
    assert Platform.YOUTUBE not in restored_job.pending_platforms
    assert Platform.TIKTOK in restored_job.pending_platforms
    assert Platform.INSTAGRAM in restored_job.pending_platforms
    assert restored_job.deliveries[Platform.YOUTUBE.value].remote_id == "yt123"


def test_retry_failed_keeps_successful_deliveries(tmp_path: Path) -> None:
    queue = PublishQueue(tmp_path / "queue.json")
    video = _video(tmp_path)
    job = queue.enqueue(
        [video],
        [Platform.TIKTOK, Platform.YOUTUBE],
        "ARARA",
        15,
    )[0]
    queue.update_delivery(job, Platform.YOUTUBE, status="success", remote_id="done")
    queue.update_delivery(job, Platform.TIKTOK, status="failed", error="network")
    assert queue.retry_failed_now() == 1
    assert job.deliveries[Platform.TIKTOK.value].status == "pending"
    assert job.deliveries[Platform.YOUTUBE.value].status == "success"


def test_tiktok_uses_creator_privacy_and_confirms_publish_status(
    tmp_path: Path,
    monkeypatch,
) -> None:
    video = _video(tmp_path)
    calls: list[tuple[str, dict]] = []

    def fake_json(url: str, **kwargs):
        calls.append((url, kwargs))
        if "creator_info" in url:
            return {
                "data": {"privacy_level_options": ["SELF_ONLY"]},
                "error": {"code": "ok", "message": ""},
            }
        if "status/fetch" in url:
            return {
                "data": {
                    "status": "PUBLISH_COMPLETE",
                    "publicaly_available_post_id": [],
                },
                "error": {"code": "ok", "message": ""},
            }
        return {
            "data": {
                "publish_id": "publish-1",
                "upload_url": "https://upload.example/video",
            },
            "error": {"code": "ok", "message": ""},
        }

    monkeypatch.setattr("arara_factory.publishing._json_request", fake_json)
    monkeypatch.setattr(
        "arara_factory.publishing._upload_binary",
        lambda *args, **kwargs: None,
    )
    result = publish_tiktok(
        video,
        "ARARA",
        {
            "access_token": "token",
            "privacy_level": "PUBLIC_TO_EVERYONE",
            "expires_at": 99999999999,
        },
        lambda value, text: None,
    )
    assert result == "publish-1"
    init_payload = next(
        kwargs["payload"] for url, kwargs in calls if "video/init" in url
    )
    assert init_payload["post_info"]["privacy_level"] == "SELF_ONLY"
    assert init_payload["source_info"]["total_chunk_count"] == 1
    assert any("status/fetch" in url for url, _ in calls)


def test_instagram_resumable_upload_publishes_container(tmp_path: Path, monkeypatch) -> None:
    video = _video(tmp_path)
    calls: list[str] = []

    def fake_json(url: str, **kwargs):
        calls.append(url)
        if url.endswith("/media"):
            return {"id": "container-1", "uri": "https://upload.example/ig"}
        if "fields=status_code" in url:
            return {"status_code": "FINISHED"}
        if url.endswith("/media_publish"):
            return {"id": "media-1"}
        raise AssertionError(url)

    monkeypatch.setattr("arara_factory.publishing._json_request", fake_json)
    monkeypatch.setattr(
        "arara_factory.publishing._upload_binary",
        lambda *args, **kwargs: None,
    )
    result = publish_instagram(
        video,
        "ARARA",
        {
            "access_token": "token",
            "ig_user_id": "42",
            "api_version": "v25.0",
            "graph_host": "graph.instagram.com",
        },
        lambda value, text: None,
    )
    assert result == "media-1"
    assert any(url.endswith("/42/media") for url in calls)
    assert any(url.endswith("/42/media_publish") for url in calls)
