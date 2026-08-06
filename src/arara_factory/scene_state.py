from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

from .geometry import DEFAULT_BRAINROT_TRANSFORM, NormalizedRect, clamp_normalized_rect

ORGANIZATION = 'ARARA'
APPLICATION = 'ARARA Factory'
TRANSFORM_KEYS = (
    'scene/brainrot_x',
    'scene/brainrot_y',
    'scene/brainrot_width',
    'scene/brainrot_height',
)


def settings() -> QSettings:
    return QSettings(ORGANIZATION, APPLICATION)


def load_brainrot_transform() -> NormalizedRect:
    store = settings()
    default = DEFAULT_BRAINROT_TRANSFORM
    try:
        rect = NormalizedRect(
            float(store.value(TRANSFORM_KEYS[0], default.x)),
            float(store.value(TRANSFORM_KEYS[1], default.y)),
            float(store.value(TRANSFORM_KEYS[2], default.width)),
            float(store.value(TRANSFORM_KEYS[3], default.height)),
        )
    except (TypeError, ValueError):
        return default
    return clamp_normalized_rect(rect)


def save_brainrot_transform(rect: NormalizedRect) -> NormalizedRect:
    safe = clamp_normalized_rect(rect)
    store = settings()
    store.setValue(TRANSFORM_KEYS[0], safe.x)
    store.setValue(TRANSFORM_KEYS[1], safe.y)
    store.setValue(TRANSFORM_KEYS[2], safe.width)
    store.setValue(TRANSFORM_KEYS[3], safe.height)
    store.sync()
    return safe


def reset_brainrot_transform() -> NormalizedRect:
    return save_brainrot_transform(DEFAULT_BRAINROT_TRANSFORM)


def saved_brainrot_path() -> Path | None:
    value = str(settings().value('brainrot', '') or '').strip()
    if not value:
        return None
    path = Path(value)
    return path if path.is_file() else None
