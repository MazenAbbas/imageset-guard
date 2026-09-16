"""Deterministic synthetic workload generator for imageset-guard benchmarks.

Not part of the imageset_guard package (excluded from the built wheel and
sdist) -- a development-only tool. Generates no downloaded or copyrighted
assets; every pixel is drawn locally by Pillow from a fixed seed.

Usage:
    python benchmarks/generate_workload.py <file_count> <output_dir> [--seed N]
"""

from __future__ import annotations

import argparse
import random
import shutil
from pathlib import Path

from PIL import Image, ImageDraw

CLASSES = (
    "cat", "dog", "bird", "car", "truck",
    "flower", "chair", "table", "shoe", "hat",
)
SPLIT_WEIGHTS = (("train", 0.8), ("validation", 0.1), ("test", 0.1))
FORMAT_WEIGHTS = (("JPEG", ".jpg", 0.7), ("PNG", ".png", 0.2), ("WEBP", ".webp", 0.1))
DUP_COPIES = 3
CORRUPT_COUNT = 3


def _pick(rng: random.Random, options: tuple) -> tuple:
    r = rng.random()
    acc = 0.0
    for opt in options:
        acc += opt[-1]
        if r <= acc:
            return opt
    return options[-1]


def _draw_noise(img: Image.Image, rng: random.Random) -> None:
    draw = ImageDraw.Draw(img)
    w, h = img.size
    for _ in range(20):
        x0, y0 = rng.randint(0, w - 1), rng.randint(0, h - 1)
        x1, y1 = rng.randint(0, w - 1), rng.randint(0, h - 1)
        draw.line(
            (x0, y0, x1, y1),
            fill=(rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255)),
            width=3,
        )


def _make_plain_image(path: Path, fmt: str, rng: random.Random) -> None:
    w, h = rng.randint(256, 1280), rng.randint(256, 1280)
    color = (rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255))
    img = Image.new("RGB", (w, h), color)
    _draw_noise(img, rng)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "JPEG":
        img.save(path, format="JPEG", quality=85)
    elif fmt == "PNG":
        img.save(path, format="PNG")
    else:
        img.save(path, format="WEBP", quality=85)


def generate(root: Path, total_files: int, seed: int) -> None:
    """Generate ``total_files`` files under ``root``, deterministic for ``seed``.

    Includes, embedded within the total: 3 deliberately corrupted files, 1
    EXIF-bearing image, 1 EXIF+GPS-bearing image, and 3 exact-duplicate
    copies (same split+class, cross-class, cross-split) -- every duplicate
    copy keeps its source's real extension, so none is an unintended
    format/extension mismatch.
    """
    if root.exists():
        shutil.rmtree(root)
    rng = random.Random(seed)

    base_count = total_files - DUP_COPIES
    corrupt_indices = {0, 1, 2}
    exif_index, gps_index = 3, 4
    dup_same_class_src, dup_cross_class_src, dup_cross_split_src = 5, 6, 7

    base_paths: list[Path] = []
    for i in range(base_count):
        split = _pick(rng, SPLIT_WEIGHTS)[0]
        cls = rng.choice(CLASSES)

        if i in corrupt_indices:
            _fmt, ext, _w = _pick(rng, FORMAT_WEIGHTS)
            path = root / split / cls / f"img_{i:06d}{ext}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"not a real image, deliberately corrupted" * 5)
        elif i == exif_index:
            path = root / split / cls / f"img_{i:06d}.jpg"
            exif = Image.Exif()
            exif[305] = "benchmark-camera"
            img = Image.new("RGB", (rng.randint(256, 1280), rng.randint(256, 1280)), "green")
            _draw_noise(img, rng)
            path.parent.mkdir(parents=True, exist_ok=True)
            img.save(path, format="JPEG", quality=85, exif=exif)
        elif i == gps_index:
            path = root / split / cls / f"img_{i:06d}.jpg"
            gps_exif = Image.Exif()
            gps_exif[34853] = {1: "N", 2: (40, 0, 0)}
            img = Image.new("RGB", (rng.randint(256, 1280), rng.randint(256, 1280)), "yellow")
            _draw_noise(img, rng)
            path.parent.mkdir(parents=True, exist_ok=True)
            img.save(path, format="JPEG", quality=85, exif=gps_exif)
        else:
            fmt, ext, _w = _pick(rng, FORMAT_WEIGHTS)
            path = root / split / cls / f"img_{i:06d}{ext}"
            _make_plain_image(path, fmt, rng)
        base_paths.append(path)

    same_class_src = base_paths[dup_same_class_src]
    same_class_dst = same_class_src.parent / f"dup_same_class{same_class_src.suffix}"
    shutil.copyfile(same_class_src, same_class_dst)

    cross_class_src = base_paths[dup_cross_class_src]
    src_split, src_class = cross_class_src.parent.parent.name, cross_class_src.parent.name
    other_class = next(c for c in CLASSES if c != src_class)
    cross_class_dst = root / src_split / other_class / f"dup_cross_class{cross_class_src.suffix}"
    cross_class_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(cross_class_src, cross_class_dst)

    cross_split_src = base_paths[dup_cross_split_src]
    src_split2, src_class2 = cross_split_src.parent.parent.name, cross_split_src.parent.name
    other_split = next(s for s, _w in SPLIT_WEIGHTS if s != src_split2)
    cross_split_dst = root / other_split / src_class2 / f"dup_cross_split{cross_split_src.suffix}"
    cross_split_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(cross_split_src, cross_split_dst)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file_count", type=int)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--seed", type=int, default=20260916)
    args = parser.parse_args()
    generate(args.output_dir, args.file_count, args.seed)
    total = sum(1 for _ in args.output_dir.rglob("*") if _.is_file())
    print(f"Generated {total} files under {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
