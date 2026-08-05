from __future__ import annotations

from pathlib import Path
from PIL import Image

CANVAS_W = 1080
CANVAS_H = 1920


def build_hero_overlay(source: Path, target: Path) -> None:
    """Convert the supplied ARARA artwork into a render overlay.

    The central black content window and the whole lower content area become
    transparent, while the character, gold borders and bright ornament remain.
    Coordinates are normalized from the supplied 941x1672 master artwork.
    """
    image = Image.open(source).convert('RGBA').resize((CANVAS_W, CANVAS_H), Image.Resampling.LANCZOS)
    pixels = image.load()

    # Measured from the supplied ARARA vertical artwork, scaled to 1080x1920.
    main_box = (12, 667, 1068, 1302)
    lower_box = (8, 1410, 1072, 1912)

    def clear_dark_region(box: tuple[int, int, int, int], preserve_ornament: bool) -> None:
        left, top, right, bottom = box
        for y in range(top, bottom):
            for x in range(left, right):
                r, g, b, a = pixels[x, y]
                if preserve_ornament:
                    # Keep bright gold/pink ornament and lettering, clear the dark scene.
                    brightness = max(r, g, b)
                    gold = r > 95 and g > 55 and b < 75
                    pink = r > 90 and b > 55 and r > g * 1.2
                    if brightness < 105 and not gold and not pink:
                        pixels[x, y] = (r, g, b, 0)
                else:
                    # The main window is intentionally black; remove only near-black pixels.
                    if max(r, g, b) < 35:
                        pixels[x, y] = (r, g, b, 0)

    clear_dark_region(main_box, preserve_ornament=False)
    clear_dark_region(lower_box, preserve_ornament=True)
    image.save(target)
