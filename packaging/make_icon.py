"""Generate assets/icon.ico from the tray icon drawing."""

from __future__ import annotations

from pathlib import Path

from screenshot_aligner.tray import build_icon_image


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "assets" / "icon.ico"
    out.parent.mkdir(parents=True, exist_ok=True)
    image = build_icon_image(256)
    image.save(
        out,
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
