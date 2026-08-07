from __future__ import annotations

import os
import threading
from datetime import datetime
from pathlib import Path


_lock = threading.Lock()


def _root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    target = base / "ARARA Factory"
    target.mkdir(parents=True, exist_ok=True)
    return target


def journal_path() -> Path:
    return _root() / "publishing.log"


def append_publish_log(message: str) -> str:
    text = str(message).strip()
    if not text:
        return ""
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {text}"
    path = journal_path()
    with _lock:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    return line


def tail_publish_log(limit: int = 250) -> str:
    path = journal_path()
    if not path.is_file():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-max(1, int(limit)):])


def clear_publish_log() -> None:
    path = journal_path()
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
