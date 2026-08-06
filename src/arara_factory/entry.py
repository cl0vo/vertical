from __future__ import annotations

import ctypes
import os


_SINGLE_INSTANCE_HANDLE = None


def _acquire_single_instance() -> bool:
    global _SINGLE_INSTANCE_HANDLE
    if os.name != "nt":
        return True

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, "Local\\ARARA_Factory_Single_Instance")
    if not handle:
        return True
    _SINGLE_INSTANCE_HANDLE = handle
    already_exists = kernel32.GetLastError() == 183
    if already_exists:
        ctypes.windll.user32.MessageBoxW(
            None,
            "ARARA Factory уже открыта. Используй текущее окно программы.",
            "ARARA Factory",
            0x40,
        )
        return False
    return True


def main() -> None:
    if not _acquire_single_instance():
        return

    from . import app as app_module
    from .integrated_batch import install

    install(app_module)
    app_module.main()
