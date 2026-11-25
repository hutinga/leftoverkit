"""Build a launch still and looping replays from verified browser captures."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

GROUND = "#101216"
INK = "#f5f6f2"
ACCENT = "#8cf4bd"
MUTED = "#adb4bd"
FONT_CANDIDATES = (
    "/System/Library/Fonts/Menlo.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
)


def font(size: int):
    path = next((name for name in FONT_CANDIDATES if Path(name).is_file()), None)
    return ImageFont.truetype(path, size) if path else ImageFont.load_default(size=size)


def loop(source: Path, output: Path, filenames: list[str]) -> None:
    frames = []
    for filename in filenames:
        with Image.open(source / filename) as image:
            sized = image.convert("RGB").resize((1080, 693), Image.Resampling.LANCZOS)
            frames.append(sized.quantize(colors=176, method=Image.Quantize.MEDIANCUT))
    frames[0].save(
        output,
        save_all=True,
        append_images=frames[1:],
        duration=[1900, 360, 1700, 1350],
        loop=0,
        optimize=True,
        disposal=2,
    )


def still(source: Path, output: Path) -> None:
    image = Image.new("RGB", (1200, 680), GROUND)
    draw = ImageDraw.Draw(image)
    draw.text((55, 41), "LEFTOVERKIT", font=font(21), fill=ACCENT)
    draw.text((55, 81), "AI finished. The files stayed.", font=font(46), fill=INK)
    draw.text((55, 151), "991  →  0  →  991", font=font(77), fill=ACCENT)
    draw.text((57, 242), "Before cleanup", font=font(21), fill=MUTED)
    draw.text((634, 242), "After one command", font=font(21), fill=MUTED)
    for index, state in enumerate(("before", "after")):
        with Image.open(source / f"desktop-{state}.png") as screen:
            graphic = screen.crop((670, 228, 1360, 589)).resize((510, 267), Image.Resampling.LANCZOS)
        x = 54 + index * 576
        draw.rounded_rectangle((x, 279, x + 518, 554), radius=10, fill="#1b232c")
        image.paste(graphic, (x + 4, 283))
    draw.text((56, 590), "Source, .env, delivery and live log stayed put.", font=font(19), fill=INK)
    draw.text((56, 624), "Synthetic fixture verified by the real CLI.", font=font(17), fill=MUTED)
    image.save(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captures", type=Path)
    parser.add_argument("output_directory", type=Path)
    args = parser.parse_args()
    args.output_directory.mkdir(parents=True, exist_ok=True)
    loop(
        args.captures,
        args.output_directory / "cleanup.gif",
        [
            "desktop-before.png",
            "desktop-sweep.png",
            "desktop-after.png",
            "desktop-restored.png",
        ],
    )
    loop(
        args.captures,
        args.output_directory / "cleanup-zh.gif",
        [
            "desktop-zh.png",
            "desktop-zh-sweep.png",
            "desktop-zh-after.png",
            "desktop-zh-restored.png",
        ],
    )
    still(args.captures, args.output_directory / "cleanup.png")


if __name__ == "__main__":
    main()
