from __future__ import annotations

import ctypes
import os
import subprocess
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any


def hidden_process_kwargs() -> dict[str, Any]:
    """Return subprocess options that keep child tools invisible on Windows."""
    if os.name != "nt":
        return {}

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "startupinfo": startupinfo,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }


def run_hidden(command: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    options = hidden_process_kwargs()
    options.update(kwargs)
    return subprocess.run(list(command), **options)


def popen_hidden(command: Sequence[str], **kwargs: Any) -> subprocess.Popen[str]:
    options = hidden_process_kwargs()
    options.update(kwargs)
    return subprocess.Popen(list(command), **options)


@contextmanager
def keep_system_awake() -> Iterator[None]:
    """Prevent Windows sleep while a long render queue is active."""
    if os.name != "nt":
        yield
        return

    execution_state = ctypes.windll.kernel32.SetThreadExecutionState
    continuous = 0x80000000
    system_required = 0x00000001
    display_required = 0x00000002
    execution_state(continuous | system_required | display_required)
    try:
        yield
    finally:
        execution_state(continuous)
