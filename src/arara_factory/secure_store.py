from __future__ import annotations

import base64
import ctypes
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_uint32),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    target = base / "ARARA Factory"
    target.mkdir(parents=True, exist_ok=True)
    return target


def credentials_path() -> Path:
    return _root() / "publishing-credentials.dat"


def _protect_windows(data: bytes) -> bytes:
    buffer = ctypes.create_string_buffer(data)
    input_blob = _DataBlob(
        len(data),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    output_blob = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        "ARARA Factory publishing credentials",
        None,
        None,
        None,
        0,
        ctypes.byref(output_blob),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


def _unprotect_windows(data: bytes) -> bytes:
    buffer = ctypes.create_string_buffer(data)
    input_blob = _DataBlob(
        len(data),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    output_blob = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(output_blob),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


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
