from __future__ import annotations

from arara_factory.updater import is_newer_version, release_from_payload, version_tuple


def test_version_comparison() -> None:
    assert version_tuple("v0.10.0") == (0, 10, 0)
    assert is_newer_version("0.10.0", "0.9.0")
    assert is_newer_version("v1.0.0", "0.10.9")
    assert not is_newer_version("0.10.0", "0.10.0")
    assert not is_newer_version("0.9.9", "0.10.0")


def test_release_asset_is_selected() -> None:
    payload = {
        "tag_name": "v0.11.0",
        "assets": [
            {
                "name": "ARARA-Factory-Setup.exe",
                "browser_download_url": "https://github.com/cl0vo/vertical/releases/download/v0.11.0/ARARA-Factory-Setup.exe",
                "size": 123456,
                "digest": "sha256:" + "0" * 64,
            }
        ],
    }
    info = release_from_payload(payload, "0.10.0")
    assert info is not None
    assert info.version == "0.11.0"
    assert info.size == 123456


def test_current_or_missing_release_is_ignored() -> None:
    assert release_from_payload({"tag_name": "v0.10.0", "assets": []}, "0.10.0") is None
    assert release_from_payload({"tag_name": "v0.11.0", "assets": []}, "0.10.0") is None
