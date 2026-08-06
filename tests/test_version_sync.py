from __future__ import annotations

import tomllib
from pathlib import Path

from arara_factory.version import __version__


def test_version_is_synchronized() -> None:
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    installer = (root / "installer" / "arara_factory.iss").read_text(encoding="utf-8")

    assert project["project"]["version"] == __version__
    assert f'#define MyAppVersion "{__version__}"' in installer
