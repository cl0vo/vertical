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


# Main transparent window in the canonical template.
MAIN_CONTENT = Rect(13, 592, 913, 553)

# Everything below the main window is the brainrot zone.
# 913 / 513 = 1.7797, effectively a native 16:9 window.
FULL_LOWER_BRAINROT = Rect(13, 1145, 913, 513)


def scale_rect(rect: Rect, target_width: int, target_height: int) -> Rect:
    """Scale canonical pixel coordinates to the final Reel without drift."""
    x1 = round(rect.x * target_width / REFERENCE_WIDTH)
    y1 = round(rect.y * target_height / REFERENCE_HEIGHT)
    x2 = round(rect.right * target_width / REFERENCE_WIDTH)
    y2 = round(rect.bottom * target_height / REFERENCE_HEIGHT)
    return Rect(x1, y1, x2 - x1, y2 - y1)


def canonical_layout(target_width: int, target_height: int) -> tuple[Rect, Rect]:
    """Return the main-content and full lower-third brainrot rectangles."""
    return (
        scale_rect(MAIN_CONTENT, target_width, target_height),
        scale_rect(FULL_LOWER_BRAINROT, target_width, target_height),
    )
