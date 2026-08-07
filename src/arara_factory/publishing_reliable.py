from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

from .publishing import Platform, publish_instagram, publish_tiktok
from .publishing_journal import append_publish_log
from .secure_store import load_credentials, update_platform_credentials

Progress = Callable[[int, str], None]

YOUTUBE_UPLOAD_ENDPOINT = "https://www.googleapis.com/upload/youtube/v3/videos"
YOUTUBE_CHUNK_SIZE = 1024 * 1024  # Must remain a multiple of 256 KiB.
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 30
MAX_TRANSIENT_RETRIES = 5


def _response_error(response: Any) -> str:
    status = int(getattr(response, "status_code", 0) or 0)
    text = str(getattr(response, "text", "") or "")
    reason = ""
    try:
        payload = response.json() if hasattr(response, "json") else json.loads(text)
        errors = ((payload.get("error") or {}).get("errors") or [])
        if errors:
            item = errors[0]
            reason = str(item.get("reason") or item.get("message") or "")
        if not reason:
            reason = str((payload.get("error") or {}).get("message") or "")
    except Exception:
        reason = text[-800:]
    suffix = f": {reason}" if reason else ""
    return f"YouTube HTTP {status or '?'}{suffix}"


def _http_error_message(exc: Exception) -> str:
    """Compatibility helper for tests and old googleapiclient HttpError objects."""
    status = int(getattr(getattr(exc, "resp", None), "status", 0) or 0)
    raw = getattr(exc, "content", b"") or b""
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="replace")
    else:
        text = str(raw)

    class LegacyResponse:
        status_code = status

        def json(self):
            return json.loads(text) if text else {}

        @property
        def text(self):
            return text

    return _response_error(LegacyResponse())


def _make_authorized_session(creds):
    from google.auth.transport.requests import AuthorizedSession

    return AuthorizedSession(creds)


def _retry_delay(attempt: int, response: Any | None = None) -> int:
    if response is not None:
        raw = str(getattr(response, "headers", {}).get("Retry-After", "") or "")
        try:
            return max(1, min(60, int(raw)))
        except ValueError:
            pass
    return min(30, 2 ** max(1, attempt))


def _parse_received_offset(response: Any, fallback: int = 0) -> int:
    raw = str(getattr(response, "headers", {}).get("Range", "") or "")
    if not raw:
        return fallback
    # YouTube returns Range: bytes=0-1048575 for resumable uploads.
    try:
        end = int(raw.rsplit("-", 1)[1])
        return end + 1
    except (ValueError, IndexError):
        return fallback


def _query_upload_status(session, upload_url: str, total: int, progress: Progress) -> tuple[int, dict | None]:
    """Ask YouTube which byte range was durably accepted by the upload session."""
    try:
        response = session.put(
            upload_url,
            data=b"",
            headers={
                "Content-Length": "0",
                "Content-Range": f"bytes */{total}",
            },
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        )
    except Exception as exc:
        raise RuntimeError(
            f"YouTube: не удалось проверить состояние загрузки: {exc.__class__.__name__}: {exc}"
        ) from exc

    if response.status_code in {200, 201}:
        try:
            payload = response.json()
        except Exception:
            payload = {}
        return total, payload if isinstance(payload, dict) else {}
    if response.status_code == 308:
        offset = _parse_received_offset(response, 0)
        percent = int(offset * 100 / total) if total else 0
        progress(min(95, max(5, percent)), f"YouTube · подтверждено {percent}%")
        return offset, None
    if response.status_code in {404, 410}:
        raise RuntimeError(
            "YouTube upload-session истекла. Видео не отмечено опубликованным; "
            "проверь канал перед ручным повтором."
        )
    raise RuntimeError(_response_error(response))


def _create_upload_session(session, body: dict, total: int, progress: Progress) -> str:
    query = urlencode(
        {
            "uploadType": "resumable",
            "part": "snippet,status",
            "notifySubscribers": "false",
        }
    )
    url = f"{YOUTUBE_UPLOAD_ENDPOINT}?{query}"
    headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Length": str(total),
        "X-Upload-Content-Type": "video/mp4",
    }

    attempt = 0
    while True:
        attempt += 1
        progress(4, f"YouTube · создаю upload-session · попытка {attempt}")
        try:
            response = session.post(
                url,
                json=body,
                headers=headers,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            )
        except Exception as exc:
            if attempt >= MAX_TRANSIENT_RETRIES:
                raise RuntimeError(
                    f"YouTube: не удалось создать upload-session: {exc.__class__.__name__}: {exc}"
                ) from exc
            delay = _retry_delay(attempt)
            progress(4, f"YouTube · API не ответил · повтор через {delay} сек")
            time.sleep(delay)
            continue

        if response.status_code in {200, 201}:
            location = str(response.headers.get("Location", "") or "")
            if not location:
                raise RuntimeError("YouTube не вернул Location для resumable upload.")
            return location
        if response.status_code in {429, 500, 502, 503, 504} and attempt < MAX_TRANSIENT_RETRIES:
            delay = _retry_delay(attempt, response)
            progress(4, f"YouTube · HTTP {response.status_code} · повтор через {delay} сек")
            time.sleep(delay)
            continue
        raise RuntimeError(_response_error(response))


def _upload_file_resumable(
    session,
    upload_url: str,
    video: Path,
    progress: Progress,
) -> str:
    total = video.stat().st_size
    offset = 0
    transient_attempt = 0
    chunk_number = 0

    with video.open("rb") as handle:
        while offset < total:
            handle.seek(offset)
            chunk = handle.read(min(YOUTUBE_CHUNK_SIZE, total - offset))
            if not chunk:
                raise RuntimeError("YouTube: файл неожиданно закончился во время загрузки.")
            start = offset
            end = start + len(chunk) - 1
            chunk_number += 1
            current_percent = int(start * 100 / total) if total else 0
            progress(
                min(94, max(5, current_percent)),
                f"YouTube · блок {chunk_number} · {current_percent}% · ожидаю ответ до {READ_TIMEOUT} сек",
            )

            try:
                response = session.put(
                    upload_url,
                    data=chunk,
                    headers={
                        "Content-Type": "video/mp4",
                        "Content-Length": str(len(chunk)),
                        "Content-Range": f"bytes {start}-{end}/{total}",
                    },
                    timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                )
            except Exception as exc:
                transient_attempt += 1
                append_publish_log(
                    f"YouTube · блок {chunk_number} · сеть/таймаут: {exc.__class__.__name__}: {exc}"
                )
                progress(
                    min(94, max(5, current_percent)),
                    f"YouTube · блок {chunk_number} · таймаут, проверяю принятые байты",
                )
                try:
                    offset, payload = _query_upload_status(session, upload_url, total, progress)
                except Exception as query_exc:
                    if transient_attempt >= MAX_TRANSIENT_RETRIES:
                        raise RuntimeError(str(query_exc)) from query_exc
                    delay = _retry_delay(transient_attempt)
                    progress(
                        min(94, max(5, current_percent)),
                        f"YouTube · сеть недоступна · повтор проверки через {delay} сек",
                    )
                    time.sleep(delay)
                    continue
                if payload is not None:
                    video_id = str(payload.get("id") or "")
                    if video_id:
                        return video_id
                if transient_attempt >= MAX_TRANSIENT_RETRIES and offset <= start:
                    raise RuntimeError(
                        f"YouTube: блок {chunk_number} не подтверждён после {MAX_TRANSIENT_RETRIES} попыток."
                    )
                if offset <= start:
                    delay = _retry_delay(transient_attempt)
                    progress(
                        min(94, max(5, current_percent)),
                        f"YouTube · повтор блока {chunk_number} через {delay} сек",
                    )
                    time.sleep(delay)
                continue

            if response.status_code in {200, 201}:
                try:
                    payload = response.json()
                except Exception:
                    payload = {}
                video_id = str((payload or {}).get("id") or "")
                if not video_id:
                    raise RuntimeError(f"YouTube завершил upload без video_id: {response.text[-500:]}")
                progress(100, f"YouTube · готово · ID {video_id}")
                return video_id

            if response.status_code == 308:
                offset = _parse_received_offset(response, end + 1)
                transient_attempt = 0
                percent = int(offset * 100 / total) if total else 100
                progress(min(95, max(5, percent)), f"YouTube · загружено {percent}%")
                continue

            if response.status_code in {429, 500, 502, 503, 504}:
                transient_attempt += 1
                message = _response_error(response)
                append_publish_log(message)
                progress(
                    min(94, max(5, current_percent)),
                    f"YouTube · HTTP {response.status_code} · сверяю принятые байты",
                )
                offset, payload = _query_upload_status(session, upload_url, total, progress)
                if payload is not None:
                    video_id = str(payload.get("id") or "")
                    if video_id:
                        return video_id
                if transient_attempt >= MAX_TRANSIENT_RETRIES and offset <= start:
                    raise RuntimeError(message)
                if offset <= start:
                    delay = _retry_delay(transient_attempt, response)
                    time.sleep(delay)
                continue

            raise RuntimeError(_response_error(response))

    # A resumable session should return 200/201 on the final chunk. Query once if
    # the local byte pointer nevertheless reached EOF without that final response.
    _, payload = _query_upload_status(session, upload_url, total, progress)
    video_id = str((payload or {}).get("id") or "") if payload else ""
    if not video_id:
        raise RuntimeError("YouTube принял все байты, но не вернул video_id.")
    return video_id


def publish_youtube_reliable(
    video: Path,
    caption: str,
    credentials: dict,
    progress: Progress,
) -> str:
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError as exc:
        raise RuntimeError("В сборке отсутствуют модули Google OAuth.") from exc

    token_info = credentials.get("token") or {}
    if not token_info:
        raise RuntimeError("YouTube не подключён. Открой «Подключения» и войди в аккаунт.")
    if not video.is_file():
        raise RuntimeError(f"YouTube: файл не найден: {video}")
    total = video.stat().st_size
    if total <= 0:
        raise RuntimeError("YouTube: выбран пустой видеофайл.")

    scopes = ["https://www.googleapis.com/auth/youtube.upload"]
    creds = Credentials.from_authorized_user_info(token_info, scopes=scopes)
    if creds.expired and creds.refresh_token:
        progress(2, "YouTube · обновляю OAuth")
        try:
            creds.refresh(Request())
        except Exception as exc:
            raise RuntimeError(f"YouTube OAuth refresh: {exc}") from exc
        updated = dict(credentials)
        updated["token"] = json.loads(creds.to_json())
        update_platform_credentials(Platform.YOUTUBE.value, updated)
        credentials = updated

    title_line = next(
        (line.strip() for line in caption.splitlines() if line.strip()),
        "ARARA",
    )
    title = title_line[:90]
    if "#shorts" not in title.lower():
        title = (title + " #shorts")[:100]
    body = {
        "snippet": {
            "title": title,
            "description": caption[:5000],
            "categoryId": "20",
        },
        "status": {
            "privacyStatus": str(credentials.get("privacy_status") or "public"),
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": bool(credentials.get("contains_synthetic_media", False)),
        },
    }

    progress(3, "YouTube · подключаю API")
    session = _make_authorized_session(creds)
    upload_url = _create_upload_session(session, body, total, progress)
    progress(5, "YouTube · upload-session создана")
    return _upload_file_resumable(session, upload_url, video, progress)


def publish_platform_reliable(
    platform: Platform,
    video: Path,
    caption: str,
    progress: Progress,
) -> str:
    credentials = load_credentials().get(platform.value) or {}
    if platform == Platform.YOUTUBE:
        return publish_youtube_reliable(video, caption, credentials, progress)
    if platform == Platform.TIKTOK:
        return publish_tiktok(video, caption, credentials, progress)
    if platform == Platform.INSTAGRAM:
        return publish_instagram(video, caption, credentials, progress)
    raise RuntimeError(f"Неизвестная платформа: {platform}")
