"""EAN/UPC barcode recognition for a single on-device camera photo.

Runs entirely on our own server with zxing-cpp; no OpenAI call and no storage.
The result is a candidate GTIN, not verified nutritional content.
"""
from __future__ import annotations

import io
import re
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BARCODE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000


def gtin_checksum_ok(text: str) -> bool:
    """Support GTIN-8, UPC-12, EAN-13, GTIN-14 with their check digits."""
    if not re.fullmatch(r"\d{8}|\d{12}|\d{13}|\d{14}", text):
        return False
    weighted = sum(int(ch) * (3 if i % 2 == 0 else 1)
                   for i, ch in enumerate(reversed(text[:-1])))
    return (10 - weighted % 10) % 10 == int(text[-1])


def decode_ean_photo(raw: bytes) -> dict[str, str]:
    if not raw or len(raw) > MAX_BARCODE_BYTES:
        raise ValueError("Fotografie EAN je prázdná nebo příliš velká (max. 8 MB).")
    try:
        with Image.open(io.BytesIO(raw)) as opened:
            if opened.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("Použij fotografii EAN ve formátu JPEG, PNG nebo WebP.")
            if opened.width * opened.height > MAX_IMAGE_PIXELS:
                raise ValueError("Fotografie EAN má příliš vysoké rozlišení.")
            image = ImageOps.exif_transpose(opened).convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Nepodařilo se otevřít fotografii EAN.") from exc

    try:
        import zxingcpp
    except ImportError as exc:
        raise RuntimeError("Na serveru chybí knihovna zxing-cpp.") from exc
    for result in zxingcpp.read_barcodes(image):
        code = str(result.text).strip()
        barcode_type = (str(result.format).upper()
                        .replace('BARCODEFORMAT.', '').replace('-', '')
                        .replace('_', '').replace(' ', ''))
        if barcode_type in {'EAN8', 'EAN13', 'UPCA', 'UPCE', 'ITF'} and gtin_checksum_ok(code):
            return {"code": code, "format": barcode_type}
    raise ValueError("Na fotografii nebyl nalezen čitelný EAN/UPC. Zkus lepší světlo a celý kód v záběru.")
