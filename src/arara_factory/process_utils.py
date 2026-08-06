from __future__ import annotations

import ctypes
import os
import subprocess
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any


ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002


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


def set_system_awake(enabled: bool, *, keep_display_on: bool = False) -> None:
    """Set or clear the current process' Windows sleep requirement."""
    if os.name != "nt":
        return
    execution_state = ctypes.windll.kernel32.SetThreadExecutionState
    execution_state.argtypes = [ctypes.c_uint32]
    execution_state.restype = ctypes.c_uint32
    flags = ES_CONTINUOUS
    if enabled:
        flags |= ES_SYSTEM_REQUIRED
        if keep_display_on:
            flags |= ES_DISPLAY_REQUIRED
    execution_state(flags)


@contextmanager
def keep_system_awake() -> Iterator[None]:
    """Prevent Windows sleep while a long render queue is active."""
    set_system_awake(True, keep_display_on=False)
    try:
        yield
    finally:
        set_system_awake(False)
