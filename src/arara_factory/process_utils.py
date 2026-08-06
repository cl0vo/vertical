from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
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
