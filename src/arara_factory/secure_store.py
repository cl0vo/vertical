from __future__ import annotations

import base64
import ctypes
import json
import os
from pathlib import Path
from typing import Any


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_uint32),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


CRYPTPROTECT_UI_FORBIDDEN = 0x1


def _root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    target = base / "ARARA Factory"
    target.mkdir(parents=True, exist_ok=True)
    return target


def credentials_path() -> Path:
    return _root() / "publishing-credentials.dat"


def _windows_apis():
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    blob_pointer = ctypes.POINTER(_DataBlob)

    crypt32.CryptProtectData.argtypes = [
        blob_pointer,
        ctypes.c_wchar_p,
        blob_pointer,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        blob_pointer,
    ]
    crypt32.CryptProtectData.restype = ctypes.c_int
    crypt32.CryptUnprotectData.argtypes = [
        blob_pointer,
        ctypes.c_void_p,
        blob_pointer,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        blob_pointer,
    ]
    crypt32.CryptUnprotectData.restype = ctypes.c_int
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    return crypt32, kernel32


def _protect_windows(data: bytes) -> bytes:
    buffer = ctypes.create_string_buffer(data)
    input_blob = _DataBlob(
        len(data),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    output_blob = _DataBlob()
    crypt32, kernel32 = _windows_apis()
    if not crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        "ARARA Factory publishing credentials",
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(output_blob.pbData, ctypes.c_void_p))


def _unprotect_windows(data: bytes) -> bytes:
    buffer = ctypes.create_string_buffer(data)
    input_blob = _DataBlob(
        len(data),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    output_blob = _DataBlob()
    crypt32, kernel32 = _windows_apis()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        None,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(output_blob.pbData, ctypes.c_void_p))


def save_credentials(payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if os.name == "nt":
        encoded = b"DPAPI\0" + _protect_windows(raw)
    else:
        # Development/test fallback. Production Windows builds always use DPAPI.
        encoded = b"BASE64\0" + base64.b64encode(raw)
    target = credentials_path()
    temp = target.with_suffix(".tmp")
    temp.write_bytes(encoded)
    temp.replace(target)


def load_credentials() -> dict[str, Any]:
    target = credentials_path()
    if not target.is_file():
        return {}
    try:
        encoded = target.read_bytes()
        if encoded.startswith(b"DPAPI\0"):
            raw = _unprotect_windows(encoded[6:])
        elif encoded.startswith(b"BASE64\0"):
            raw = base64.b64decode(encoded[7:])
        else:
            return {}
        payload = json.loads(raw.decode("utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}


def update_platform_credentials(platform: str, values: dict[str, Any]) -> None:
    payload = load_credentials()
    payload[platform] = values
    save_credentials(payload)


def clear_platform_credentials(platform: str) -> None:
    payload = load_credentials()
    payload.pop(platform, None)
    save_credentials(payload)
