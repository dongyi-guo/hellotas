"""Cover pictures: download the organiser's banner, check it is a real image, resize it and save it as JPEG
under static/images/happening/<slug>/<slug>-1.jpg (the path the Happening templates expect)."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .fetch import MAX_IMAGE_BYTES, Blocked, Fetcher, FetchError

Image.MAX_IMAGE_PIXELS = 50_000_000  # refuse decompression bombs
MAX_WIDTH = 1600
MIN_WIDTH = 400


def save_cover(fetcher: Fetcher, candidates: list[str], static_dir: Path, slug: str) -> tuple[str, str]:
    """(site path, note). The site path is '' when no candidate gave a usable picture."""
    notes = []
    for url in candidates[:4]:
        try:
            page = fetcher.get(url, accept="image/avif,image/webp,image/png,image/jpeg,image/*", limit=MAX_IMAGE_BYTES)
        except (Blocked, FetchError) as exc:
            notes.append(f"{url}: {exc}")
            continue
        try:
            with Image.open(io.BytesIO(page.body)) as img:
                img.load()
                img = ImageOps.exif_transpose(img)
                if img.width < MIN_WIDTH:
                    notes.append(f"{url}: too small ({img.width}px wide)")
                    continue
                if img.mode in ("RGBA", "LA", "P"):
                    img = img.convert("RGBA")
                    background = Image.new("RGB", img.size, (255, 255, 255))
                    background.paste(img, mask=img.getchannel("A"))
                    img = background
                else:
                    img = img.convert("RGB")
                if img.width > MAX_WIDTH:
                    img = img.resize((MAX_WIDTH, round(img.height * MAX_WIDTH / img.width)), Image.LANCZOS)
                folder = static_dir / "images" / "happening" / slug
                folder.mkdir(parents=True, exist_ok=True)
                target = folder / f"{slug}-1.jpg"
                img.save(target, "JPEG", quality=82, optimize=True, progressive=True)
                return f"/images/happening/{slug}/{slug}-1.jpg", ""
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            notes.append(f"{url}: not a usable image ({exc.__class__.__name__})")
    return "", "; ".join(notes)
