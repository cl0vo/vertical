from __future__ import annotations

import json
import socket
import time
from pathlib import Path
from typing import Callable

from .publishing import Platform, publish_instagram, publish_tiktok
from .publishing_journal import append_publish_log
from .secure_store import load_credentials, update_platform_credentials

Progress = Callable[[int, str], None]


def _http_error_message(exc: Exception) -> str:
    status = int(getattr(getattr(exc, "resp", None), "status", 0) or 0)
    raw = getattr(exc, "content", b"") or b""
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="replace")
    else:
        text = str(raw)
    reason = ""
    try:
        payload = json.loads(text) if text else {}
        errors = ((payload.get("error") or {}).get("errors") or [])
        if errors:
            item = errors[0]
            reason = str(item.get("reason") or item.get("message") or "")
        if not reason:
            reason = str((payload.get("error") or {}).get("message") or "")
    except (TypeError, ValueError, json.JSONDecodeError):
        reason = text[-800:]
    suffix = f": {reason}" if reason else ""
    return f"YouTube HTTP {status or '?'}{suffix}"


def publish_youtube_reliable(
    video: Path,
    caption: str,
    credentials: dict,
    progress: Progress,
) -> str:
    try:
        import httplib2
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_httplib2 import AuthorizedHttp
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:
        raise RuntimeError("В сборке отсутствуют модули YouTube API.") from exc

    token_info = credentials.get("token") or {}
    if not token_info:
        raise RuntimeError("YouTube не подключён. Открой «Подключения» и войди в аккаунт.")

    scopes = ["https://www.googleapis.com/auth/youtube.upload"]
    creds = Credentials.from_authorized_user_info(token_info, scopes=scopes)
    if creds.expired and creds.refresh_token:
        progress(2, "YouTube · обновляю OAuth")
        creds.refresh(Request())
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
            "containsSyntheticMedia": bool(
                credentials.get("contains_synthetic_media", False)
            ),
        },
    }

    progress(4, "YouTube · подключаю API")
    # Explicit timeout is critical: without it an underlying HTTP request can look
    # frozen forever while the Qt worker itself remains alive.
    raw_http = httplib2.Http(timeout=75)
    authorized_http = AuthorizedHttp(creds, http=raw_http)
    service = build("youtube", "v3", http=authorized_http, cache_discovery=False)

    media = MediaFileUpload(
        str(video),
        mimetype="video/mp4",
        resumable=True,
        chunksize=2 * 1024 * 1024,
    )
    request = service.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
        notifySubscribers=False,
    )

    response = None
    transient_attempt = 0
    chunk_number = 0
    last_percent = 5
    progress(last_percent, "YouTube · начинаю загрузку")

    while response is None:
        chunk_number += 1
        progress(last_percent, f"YouTube · блок {chunk_number} · отправка")
        try:
            upload_status, response = request.next_chunk()
            transient_attempt = 0
            if upload_status is not None:
                last_percent = min(95, max(5, int(upload_status.progress() * 95)))
                progress(last_percent, f"YouTube · загружено {last_percent}%")
        except HttpError as exc:
            status = int(getattr(exc.resp, "status", 0) or 0)
            message = _http_error_message(exc)
            append_publish_log(message)
            if status not in {429, 500, 502, 503, 504} or transient_attempt >= 5:
                raise RuntimeError(message) from exc
            transient_attempt += 1
            delay = min(30, 2 ** transient_attempt)
            progress(
                last_percent,
                f"YouTube · временная ошибка {status} · повтор через {delay} сек",
            )
            time.sleep(delay)
        except (socket.timeout, TimeoutError, OSError, httplib2.HttpLib2Error) as exc:
            transient_attempt += 1
            message = f"YouTube сеть: {exc.__class__.__name__}: {exc}"
            append_publish_log(message)
            if transient_attempt > 5:
                raise RuntimeError(message) from exc
            delay = min(30, 2 ** transient_attempt)
            progress(
                last_percent,
                f"YouTube · сеть не ответила · повтор {transient_attempt}/5",
            )
            time.sleep(delay)

    video_id = str((response or {}).get("id") or "")
    if not video_id:
        raise RuntimeError(f"YouTube не подтвердил загрузку: {response}")

    progress(100, f"YouTube · готово · ID {video_id}")
    return video_id


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
