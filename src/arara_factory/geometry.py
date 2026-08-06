from __future__ import annotations

from dataclasses import dataclass

# Canonical PNG measured directly from Vertical overlay Arara(1).png.
REFERENCE_WIDTH = 941
REFERENCE_HEIGHT = 1672


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height


@dataclass(frozen=True)
class NormalizedRect:
    """A canvas rectangle stored as 0..1 fractions, independent of resolution."""

    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height


# Main transparent window in the canonical template.
MAIN_CONTENT = Rect(13, 592, 913, 553)

# Everything below the main window is the default brainrot zone.
# 913 / 513 = 1.7797, effectively a native 16:9 window.
FULL_LOWER_BRAINROT = Rect(13, 1145, 913, 513)

DEFAULT_BRAINROT_TRANSFORM = NormalizedRect(
    FULL_LOWER_BRAINROT.x / REFERENCE_WIDTH,
    FULL_LOWER_BRAINROT.y / REFERENCE_HEIGHT,
    FULL_LOWER_BRAINROT.width / REFERENCE_WIDTH,
    FULL_LOWER_BRAINROT.height / REFERENCE_HEIGHT,
)


def scale_rect(rect: Rect, target_width: int, target_height: int) -> Rect:
    """Scale canonical pixel coordinates to the final Reel without drift."""
    x1 = round(rect.x * target_width / REFERENCE_WIDTH)
    y1 = round(rect.y * target_height / REFERENCE_HEIGHT)
    x2 = round(rect.right * target_width / REFERENCE_WIDTH)
    y2 = round(rect.bottom * target_height / REFERENCE_HEIGHT)
    return Rect(x1, y1, x2 - x1, y2 - y1)


def clamp_normalized_rect(
    rect: NormalizedRect,
    *,
    minimum_width: float = 0.08,
    minimum_height: float = 0.06,
) -> NormalizedRect:
    width = min(1.0, max(minimum_width, float(rect.width)))
    height = min(1.0, max(minimum_height, float(rect.height)))
    x = min(1.0 - width, max(0.0, float(rect.x)))
    y = min(1.0 - height, max(0.0, float(rect.y)))
    return NormalizedRect(x, y, width, height)


def normalized_to_rect(rect: NormalizedRect, target_width: int, target_height: int) -> Rect:
    """Convert a saved normalized transform into stable integer output pixels."""
    safe = clamp_normalized_rect(rect)
    x1 = round(safe.x * target_width)
    y1 = round(safe.y * target_height)
    x2 = round(safe.right * target_width)
    y2 = round(safe.bottom * target_height)
    x1 = max(0, min(target_width - 2, x1))
    y1 = max(0, min(target_height - 2, y1))
    x2 = max(x1 + 2, min(target_width, x2))
    y2 = max(y1 + 2, min(target_height, y2))
    return Rect(x1, y1, x2 - x1, y2 - y1)


def rect_to_normalized(rect: Rect, target_width: int, target_height: int) -> NormalizedRect:
    if target_width <= 0 or target_height <= 0:
        return DEFAULT_BRAINROT_TRANSFORM
    return clamp_normalized_rect(
        NormalizedRect(
            rect.x / target_width,
            rect.y / target_height,
            rect.width / target_width,
            rect.height / target_height,
        )
    )


def canonical_layout(target_width: int, target_height: int) -> tuple[Rect, Rect]:
    """Return the main-content and default lower-third brainrot rectangles."""
    return (
        scale_rect(MAIN_CONTENT, target_width, target_height),
        scale_rect(FULL_LOWER_BRAINROT, target_width, target_height),
    )
