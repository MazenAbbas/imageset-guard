"""Generate a tiny, deterministic, local example dataset.

Used by ``imageset-guard example`` so a new user can try the tool
immediately without hunting for a real dataset. Every pixel is drawn by
Pillow at generation time -- there is no downloaded or copyrighted asset,
nothing is bundled in the package, and the result is small (a handful of
tiny images) and fully deterministic for a given seed.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Final

from PIL import Image, ImageDraw

_CLASSES: Final = ("circle", "square")
_IMAGES_PER_CLASS: Final = 4
_SIZE: Final = 64


def generate_example_dataset(output_dir: Path, *, seed: int = 0) -> int:
    """Create a tiny ``train/<class>/<image>.png`` dataset under ``output_dir``.

    Deterministic for a given ``seed``: the same seed always draws the
    same shapes, colors, and byte-for-byte identical PNG files. Returns
    the number of image files written. Raises :class:`FileExistsError` if
    ``output_dir`` already exists, so this never overwrites user data.
    """
    if output_dir.exists():
        raise FileExistsError(f"{output_dir} already exists; choose an empty destination")

    rng = random.Random(seed)
    written = 0
    for class_name in _CLASSES:
        class_dir = output_dir / "train" / class_name
        class_dir.mkdir(parents=True)
        for i in range(_IMAGES_PER_CLASS):
            path = class_dir / f"{class_name}_{i:02d}.png"
            _draw_example_image(path, class_name, rng)
            written += 1
    return written


def _draw_example_image(path: Path, class_name: str, rng: random.Random) -> None:
    background = (rng.randint(200, 255), rng.randint(200, 255), rng.randint(200, 255))
    shape_color = (rng.randint(0, 100), rng.randint(0, 100), rng.randint(0, 100))
    image = Image.new("RGB", (_SIZE, _SIZE), background)
    draw = ImageDraw.Draw(image)
    margin = _SIZE // 4
    box = (margin, margin, _SIZE - margin, _SIZE - margin)
    if class_name == "circle":
        draw.ellipse(box, fill=shape_color)
    else:
        draw.rectangle(box, fill=shape_color)
    image.save(path, format="PNG")
