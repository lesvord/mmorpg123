#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tile_export.py — пакетная подготовка тайлов:
- PNG → @1x/@2x
- WebP (lossless или lossy) и AVIF (q↑, 4:4:4 если доступно)
- Пиксельно-чёткий ресайз (NEAREST). Можно включить «мягкий» режим флагом --smooth.
"""

import argparse
import concurrent.futures
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple
from PIL import Image

# Опционально подключаем AVIF
try:
    import pillow_avif  # noqa: F401
    AVIF_OK = True
except Exception:
    AVIF_OK = False

# ——— Настройки по умолчанию ———
DEFAULT_INPUT = os.path.join(".", "static", "tiles")
DEFAULT_TILE = 18
WEBP_QUALITY = 90
WEBP_METHOD = 6
WEBP_LOSSLESS_DEFAULT = True
AVIF_QUALITY = 72
AVIF_SPEED = 6

PNG_RX = re.compile(r"^(?P<stem>.+?)_(?P<idx>\d+)(?:@(?P<scale>\d+)x)?\.png$", re.IGNORECASE)


@dataclass
class Job:
    src_path: str
    stem: str
    idx: int
    out_dir: str
    size1: int
    size2: int
    do_resize: bool
    force: bool
    make_avif: bool
    pixel_art: bool
    webp_lossless: bool
    avif_quality: int
    webp_quality: int


def list_pngs(input_dir: str) -> List[str]:
    return sorted(
        os.path.join(input_dir, fn)
        for fn in os.listdir(input_dir)
        if fn.lower().endswith(".png")
    )


def parse_png_name(filename: str) -> Optional[Tuple[str, int]]:
    m = PNG_RX.match(os.path.basename(filename))
    if not m:
        return None
    stem = f"{m.group('stem')}_{m.group('idx')}"
    return stem, int(m.group('idx'))


def newer_or_equal(dst: str, src: str) -> bool:
    if not os.path.exists(dst):
        return False
    try:
        return os.path.getmtime(dst) >= os.path.getmtime(src)
    except Exception:
        return False


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def load_image_rgba(path: str) -> Image.Image:
    im = Image.open(path)
    return im.convert("RGBA")


def save_webp(img: Image.Image, out_path: str, *, lossless: bool, quality: int):
    kwargs = dict(
        format="WEBP",
        method=WEBP_METHOD,
        exact=True,
        optimize=True,
    )
    if lossless:
        kwargs.update(lossless=True, quality=100)
    else:
        kwargs.update(lossless=False, quality=quality)
    img.save(out_path, **kwargs)


def save_avif(img: Image.Image, out_path: str, *, quality: int):
    tried = False
    for kw in (
        dict(format="AVIF", quality=quality, speed=AVIF_SPEED, chroma_subsampling="444"),
        dict(format="AVIF", quality=quality, speed=AVIF_SPEED, subsampling="444"),
        dict(format="AVIF", quality=quality, speed=AVIF_SPEED),
    ):
        try:
            img.save(out_path, **kw)
            tried = True
            break
        except TypeError:
            continue
    if not tried:
        img.save(out_path, format="AVIF", quality=quality, speed=AVIF_SPEED)


def make_square_resize(src: Image.Image, size: int, *, pixel_art: bool, can_upscale: bool) -> Image.Image:
    w, h = src.size
    if w != h:
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        src = src.crop((left, top, left + side, top + side))

    resample = Image.Resampling.NEAREST if pixel_art else Image.Resampling.LANCZOS
    if not can_upscale and (src.width < size or src.height < size):
        return src.copy()
    if src.width == size and src.height == size:
        return src.copy()
    return src.resize((size, size), resample=resample)


def export_one(job: Job):
    src = job.src_path
    stem = job.stem
    out_dir = job.out_dir
    im = load_image_rgba(src)

    if job.do_resize:
        im1 = im.copy()
        im2 = im.copy()
    else:
        im1 = im.copy()
        im2 = im.copy()


    variants = [("@1x", im1), ("@2x", im2)]
    written = []
    skipped = []

    for suf, img in variants:
        out_webp = os.path.join(out_dir, f"{stem}{suf}.webp")
        if job.force or not newer_or_equal(out_webp, src):
            save_webp(img, out_webp, lossless=job.webp_lossless, quality=job.webp_quality)
            try:
                os.utime(out_webp, (time.time(), os.path.getmtime(src)))
            except Exception:
                pass
            written.append(out_webp)
        else:
            skipped.append(out_webp)

        if job.make_avif:
            out_avif = os.path.join(out_dir, f"{stem}{suf}.avif")
            if job.force or not newer_or_equal(out_avif, src):
                save_avif(img, out_avif, quality=job.avif_quality)
                try:
                    os.utime(out_avif, (time.time(), os.path.getmtime(src)))
                except Exception:
                    pass
                written.append(out_avif)
            else:
                skipped.append(out_avif)

    return src, written, skipped


def build_jobs(input_dir: str, size: int, force: bool, no_resize: bool,
               pixel_art: bool, webp_lossless: bool,
               avif_quality: int, webp_quality: int) -> List[Job]:
    files = list_pngs(input_dir)
    jobs: List[Job] = []
    for path in files:
        parsed = parse_png_name(path)
        if not parsed:
            continue
        stem, _idx = parsed
        jobs.append(Job(
            src_path=path,
            stem=stem,
            idx=_idx,
            out_dir=input_dir,
            size1=size,
            size2=size * 2,
            do_resize=not no_resize,
            force=force,
            make_avif=AVIF_OK,
            pixel_art=pixel_art,
            webp_lossless=webp_lossless,
            avif_quality=avif_quality,
            webp_quality=webp_quality
        ))
    return jobs


def main():
    parser = argparse.ArgumentParser(description="Экспорт тайлов в WebP/AVIF c @1x/@2x.")
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--tile-size", type=int, default=DEFAULT_TILE)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-resize", action="store_true")
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    parser.add_argument("--smooth", action="store_true")
    parser.add_argument("--webp-lossy-q", type=int, default=WEBP_QUALITY)
    parser.add_argument("--avif-q", type=int, default=AVIF_QUALITY)

    args = parser.parse_args()

    pixel_art = not args.smooth
    webp_lossless = WEBP_LOSSLESS_DEFAULT if not args.smooth else False
    avif_quality = args.avif_q
    webp_quality = args.webp_lossy_q

    input_dir = os.path.abspath(args.input)
    if not os.path.isdir(input_dir):
        print(f"[ERR] Нет папки: {input_dir}", file=sys.stderr)
        return 2

    jobs = build_jobs(
        input_dir=input_dir,
        size=args.tile_size,
        force=args.force,
        no_resize=args.no_resize,
        pixel_art=pixel_art,
        webp_lossless=webp_lossless,
        avif_quality=avif_quality,
        webp_quality=webp_quality
    )

    if not jobs:
        print("[INFO] PNG тайлы не найдены.")
        return 0

    print(f"[INFO] Найдено PNG: {len(jobs)}")
    print(f"[INFO] AVIF quality: {avif_quality}; WebP lossy q: {webp_quality}")

    written_total = 0
    skipped_total = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = [ex.submit(export_one, j) for j in jobs]
        for fut in concurrent.futures.as_completed(futures):
            src, written, skipped = fut.result()
            if written:
                print(f"[OK] {os.path.basename(src)} -> {len(written)} файлов")
            written_total += len(written)
            skipped_total += len(skipped)

    print(f"\n[SUMMARY] Создано/обновлено: {written_total} • Пропущено: {skipped_total}")
    if not AVIF_OK:
        print("[NOTE] AVIF пропущен (установите pillow-avif-plugin)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
