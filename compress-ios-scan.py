# /// script
# requires-python = ">=3.11"
# dependencies = ["pikepdf>=9", "pillow"]
# ///
"""
Compress an iOS "Scan Document" PDF (Notes / Files app scanner output).

These PDFs are usually a single high-bitdepth image per page, saved by
iOS's Quartz PDFContext with NO PNG-style row prediction on the FlateDecode
stream, and often placed on a bogus 1px=1pt MediaBox (e.g. a small receipt
ends up on a nominal 20x12 inch "page"). That combination means they compress
far worse than they need to, two independent ways:

  1. Lossless win (always safe): re-filter the image with adaptive PNG
     prediction + zopfli deflate (via oxipng if installed, else Python's
     own best-effort zlib) and splice the smaller stream back in. Pixels
     are byte-for-byte identical. Typically ~15-20% smaller.

  2. Lossy win (opt-in): re-encode the way a printer/scanner PDF does —
     JPEG (DCTDecode) at a real physical DPI, with paper-grain flattened
     to white and grayscale used when the page isn't actually in colour.
     Palette-quantized PNG is a bad fit for scans: it posters the page
     and still doesn't get small. Pass --size so DPI is judged at the
     document's true physical size, not the bogus oversized page.

Usage:
    uv run compress-ios-scan.py INPUT.pdf [INPUT2.pdf ...] \
        --quality {lossless,hq,balanced,small,tiny} \
        [--size SIZE]            # A4 / A4-landscape / ... or WIDTHxHEIGHT in centimetres, e.g. 8.5x5.3
        [--dpi N] [--jpeg-quality N]  # advanced: override the preset
        [--scale PCT]            # advanced: force a resolution scale (0-1), skips DPI math
        [--output-dir DIR]       # default: alongside input as <stem>_compressed.pdf

Quality presets. "small" is meant to land in the same 50-200 KB ballpark as
a typical MFP colour/greyscale PDF of a page, without the muddy look of
the old 64-colour PNG path. Pick a page size (A4, ...) so the DPI cap is
correct; without --size, long edge is capped as if the page were A4.
    lossless   PNG re-filter only, no quality loss                  (~15-20% smaller)
    hq         JPEG q=80, 300 dpi, 4:4:4 chroma
    balanced   JPEG q=72, 250 dpi
    small      JPEG q=65, 200 dpi   [default]   (~printer-scanner PDF)
    tiny       JPEG q=50, 150 dpi
"""

from __future__ import annotations

import argparse
import io
import shutil
import struct
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pikepdf
from pikepdf import Array, Dictionary, Name
from PIL import Image, ImageFilter

PRESETS = {
    # name: (jpeg_quality or None for lossless PNG, target_dpi, JPEG subsampling)
    # subsampling: 0 = 4:4:4, 2 = 4:2:0 (what MFPs use)
    "lossless": (None, 0, 0),
    "hq": (80, 300, 0),
    "balanced": (72, 250, 2),
    "small": (65, 200, 2),
    "tiny": (50, 150, 2),
}

CM_TO_PT = 72 / 2.54
CM_TO_IN = 1 / 2.54
# Fallback long-edge cap when the user didn't pass --size: treat as A4.
A4_LONG_CM = 29.7

# ISO 216 A-series, portrait then landscape, in centimetres.
PAGE_SIZES_CM: dict[str, tuple[float, float]] = {
    "a2": (42.0, 59.4),
    "a2-landscape": (59.4, 42.0),
    "a3": (29.7, 42.0),
    "a3-landscape": (42.0, 29.7),
    "a4": (21.0, 29.7),
    "a4-landscape": (29.7, 21.0),
    "a5": (14.8, 21.0),
    "a5-landscape": (21.0, 14.8),
    "a6": (10.5, 14.8),
    "a6-landscape": (14.8, 10.5),
}


def find_oxipng() -> str | None:
    exe = shutil.which("oxipng")
    if exe:
        return exe
    # winget default install location on Windows
    import glob

    candidates = glob.glob(
        r"C:\Users\*\AppData\Local\Microsoft\WinGet\Packages\Shssoichiro.Oxipng_*\oxipng-*\oxipng.exe"
    )
    return candidates[0] if candidates else None


def parse_png(data: bytes):
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    pos = 8
    idat = bytearray()
    plte = None
    width = height = bit_depth = color_type = None
    while pos < len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        ctype = data[pos + 4 : pos + 8]
        payload = data[pos + 8 : pos + 8 + length]
        if ctype == b"IHDR":
            width, height, bit_depth, color_type = struct.unpack(">IIBB", payload[:10])
        elif ctype == b"PLTE":
            plte = payload
        elif ctype == b"IDAT":
            idat += payload
        pos += 8 + length + 4
    return bytes(idat), plte, width, height, bit_depth, color_type


def optimize_png_bytes(png_bytes: bytes) -> bytes:
    """Losslessly re-optimize a PNG's compressed stream. Uses oxipng
    (adaptive filtering + zopfli) if available; falls back to re-deflating
    at level 9 with Pillow's own encoder otherwise."""
    oxipng = find_oxipng()
    if not oxipng:
        return png_bytes
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "img.png"
        p.write_bytes(png_bytes)
        subprocess.run(
            [oxipng, "-o", "max", "--zopfli", "-a", "--strip", "safe", str(p)],
            check=True,
            capture_output=True,
        )
        return p.read_bytes()


@dataclass
class ImageResult:
    data: bytes
    width: int
    height: int
    filter: Name
    colorspace: Name
    bits: int
    decode_parms: Dictionary | None
    note: str = ""


def to_rgb(im: Image.Image) -> Image.Image:
    if im.mode == "RGB":
        return im
    if im.mode in ("RGBA", "LA", "PA"):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        alpha = im.getchannel("A") if "A" in im.getbands() else None
        rgb = im.convert("RGB")
        if alpha is not None:
            bg.paste(rgb, mask=alpha)
            return bg
        return rgb
    return im.convert("RGB")


def flatten_paper(im: Image.Image) -> Image.Image:
    """Pull near-white paper to pure white, the way an MFP scan does.

    JPEG then spends bits on ink instead of paper grain — smaller *and*
    cleaner, not a quality loss for document pages.
    """
    rgb = to_rgb(im)
    sample_w = min(200, rgb.width)
    sample_h = min(200, rgb.height)
    sample = rgb.resize((sample_w, sample_h), Image.BILINEAR).convert("L")
    hist = sample.histogram()
    total = sum(hist) or 1
    acc = 0
    white = 255
    for i in range(255, -1, -1):
        acc += hist[i]
        if acc >= total * 0.02:
            white = i
            break
    if white >= 253:
        return rgb
    scale = 255.0 / white
    lut = [min(255, round(i * scale)) for i in range(256)]
    return rgb.point(lut * 3)


def is_nearly_gray(
    im: Image.Image, chroma_limit: int = 18, colorful_frac: float = 0.008
) -> bool:
    """True if almost none of the page has real colour (typical B&W document)."""
    sample = to_rgb(im).resize((96, 96), Image.BILINEAR)
    raw = sample.tobytes()
    n = len(raw) // 3 or 1
    colorful = 0
    for i in range(0, n * 3, 3):
        r, g, b = raw[i], raw[i + 1], raw[i + 2]
        if max(r, g, b) - min(r, g, b) > chroma_limit:
            colorful += 1
    return colorful / n < colorful_frac


def output_dimensions(
    width: int,
    height: int,
    size_cm: tuple[float, float] | None,
    target_dpi: int,
    scale_override: float | None,
) -> tuple[int, int]:
    if scale_override is not None:
        s = scale_override
        return max(1, round(width * s)), max(1, round(height * s))
    if target_dpi <= 0:
        return width, height
    if size_cm is not None:
        w_cm, h_cm = size_cm
        if (width > height) != (w_cm > h_cm):
            w_cm, h_cm = h_cm, w_cm
        target_w = w_cm * CM_TO_IN * target_dpi
        target_h = h_cm * CM_TO_IN * target_dpi
        scale = min(1.0, target_w / width, target_h / height)
    else:
        max_long = A4_LONG_CM * CM_TO_IN * target_dpi
        long_edge = max(width, height)
        scale = 1.0 if long_edge <= max_long else max_long / long_edge
    return max(1, round(width * scale)), max(1, round(height * scale))


def encode_jpeg(im: Image.Image, quality: int, subsampling: int) -> bytes:
    buf = io.BytesIO()
    save_kwargs: dict = {
        "format": "JPEG",
        "quality": quality,
        "optimize": True,
        "progressive": False,
    }
    if im.mode != "L":
        save_kwargs["subsampling"] = subsampling
    im.save(buf, **save_kwargs)
    return buf.getvalue()


def process_image_lossless(im: Image.Image) -> ImageResult:
    rgb = to_rgb(im)
    buf = io.BytesIO()
    rgb.save(buf, format="PNG", optimize=True)
    png_bytes = optimize_png_bytes(buf.getvalue())
    idat, _plte, width, height, bit_depth, _color_type = parse_png(png_bytes)
    decode_parms = Dictionary(
        Predictor=15,
        Colors=3,
        BitsPerComponent=bit_depth,
        Columns=width,
    )
    return ImageResult(
        data=idat,
        width=width,
        height=height,
        filter=Name.FlateDecode,
        colorspace=Name.DeviceRGB,
        bits=bit_depth,
        decode_parms=decode_parms,
        note="PNG Flate + predictor 15",
    )


def process_image_jpeg(
    im: Image.Image,
    jpeg_quality: int,
    target_dpi: int,
    subsampling: int,
    size_cm: tuple[float, float] | None,
    scale_override: float | None,
) -> ImageResult:
    rgb = flatten_paper(im)
    w, h = output_dimensions(rgb.width, rgb.height, size_cm, target_dpi, scale_override)
    if (w, h) != rgb.size:
        rgb = rgb.resize((w, h), Image.LANCZOS)
        # LANCZOS can reintroduce a slight veil on white; re-flatten cheaply
        rgb = flatten_paper(rgb)
        rgb = rgb.filter(ImageFilter.UnsharpMask(radius=1.0, percent=70, threshold=2))

    gray = is_nearly_gray(rgb)
    out = rgb.convert("L") if gray else rgb
    data = encode_jpeg(out, jpeg_quality, subsampling)
    chroma = "gray" if gray else ("4:4:4" if subsampling == 0 else "4:2:0")
    return ImageResult(
        data=data,
        width=out.width,
        height=out.height,
        filter=Name.DCTDecode,
        colorspace=Name.DeviceGray if gray else Name.DeviceRGB,
        bits=8,
        decode_parms=None,
        note=f"JPEG q={jpeg_quality} {chroma} {out.width}x{out.height}",
    )


def compress_pdf(
    src: Path,
    dst: Path,
    quality: str,
    size_cm: tuple[float, float] | None,
    jpeg_quality_override: int | None,
    dpi_override: int | None,
    scale_override: float | None,
) -> None:
    preset_q, preset_dpi, preset_sub = PRESETS[quality]
    jpeg_quality = (
        jpeg_quality_override if jpeg_quality_override is not None else preset_q
    )
    target_dpi = dpi_override if dpi_override is not None else preset_dpi

    pdf = pikepdf.open(src)
    producer = str(pdf.docinfo.get("/Producer", ""))
    if "iOS" not in producer and "Quartz" not in producer:
        print(
            f"Note: /Producer is '{producer}' - this doesn't look like a typical "
            f"iOS-scan PDF, but proceeding anyway.",
            file=sys.stderr,
        )

    total_before = src.stat().st_size

    for page in pdf.pages:
        xobjs = page.get("/Resources", {}).get("/XObject", {})
        for name, obj in list(xobjs.items()):
            if obj.get("/Subtype") != Name.Image:
                continue

            pdf_image = pikepdf.PdfImage(obj)
            pil_im = pdf_image.as_pil_image()
            before_len = len(obj.read_raw_bytes())

            if jpeg_quality is None:
                result = process_image_lossless(pil_im)
            else:
                result = process_image_jpeg(
                    pil_im,
                    jpeg_quality,
                    target_dpi,
                    preset_sub,
                    size_cm,
                    scale_override,
                )

            if len(result.data) >= before_len:
                print(
                    f"  {name}: re-encode wasn't smaller ({len(result.data)} >= {before_len}), keeping original"
                )
                continue

            obj.Width = result.width
            obj.Height = result.height
            obj.BitsPerComponent = result.bits
            obj.ColorSpace = result.colorspace
            if Name.SMask in obj:
                del obj[Name.SMask]
            if result.decode_parms is None:
                obj.write(result.data, filter=result.filter)
                if Name.DecodeParms in obj:
                    del obj[Name.DecodeParms]
            else:
                obj.write(
                    result.data, filter=result.filter, decode_parms=result.decode_parms
                )

            # Fix page size to the real physical document size, if given.
            if size_cm is not None:
                w_pt = size_cm[0] * CM_TO_PT
                h_pt = size_cm[1] * CM_TO_PT
                page.MediaBox = Array([0, 0, w_pt, h_pt])
                content = f"q {w_pt:.4f} 0 0 {h_pt:.4f} 0 0 cm /{name} Do Q".encode(
                    "latin1"
                )
                page.Contents = pdf.make_stream(content)

            print(f"  {name}: {result.note}")

    pdf.save(
        dst, compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate
    )
    pdf.close()

    total_after = dst.stat().st_size
    pct = 100 * (1 - total_after / total_before)
    print(
        f"{src.name}: {total_before / 1024:.1f} KB -> {dst.name}: {total_after / 1024:.1f} KB "
        f"({pct:.1f}% smaller)"
    )
    if size_cm is not None:
        print(f"  page fixed to {size_cm[0]:g} x {size_cm[1]:g} cm")


def parse_size(s: str) -> tuple[float, float]:
    raw = (
        s.strip()
        .lower()
        .replace("cm", "")
        .replace(" ", "")
        .replace("_", "-")
        .replace("×", "x")
    )
    if raw in PAGE_SIZES_CM:
        return PAGE_SIZES_CM[raw]
    try:
        w, h = raw.split("x")
        return float(w), float(h)
    except Exception as e:
        named = ", ".join(PAGE_SIZES_CM)
        raise argparse.ArgumentTypeError(
            f"expected a European page size ({named}) or WIDTHxHEIGHT in centimetres, "
            f"e.g. 8.5x5.3, got {s!r}"
        ) from e


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("inputs", nargs="+", type=Path)
    ap.add_argument("--quality", choices=list(PRESETS), default="small")
    ap.add_argument(
        "--size",
        type=parse_size,
        default=None,
        help="physical page size: ISO A-series name (A4, A4-landscape, ...) "
        "or WIDTHxHEIGHT in centimetres, e.g. 8.5x5.3",
    )
    ap.add_argument(
        "--jpeg-quality",
        type=int,
        default=None,
        dest="jpeg_quality",
        help="override JPEG quality 1-95 (lossy presets only)",
    )
    ap.add_argument(
        "--dpi", type=int, default=None, help="override target DPI (lossy presets only)"
    )
    ap.add_argument(
        "--scale",
        type=float,
        default=None,
        help="force resolution scale 0-1, skipping DPI math",
    )
    ap.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="directory for output files (default: same as input)",
    )
    args = ap.parse_args()

    if args.quality == "lossless" and (
        args.jpeg_quality is not None or args.dpi is not None
    ):
        print("Note: --jpeg-quality/--dpi ignored for lossless.", file=sys.stderr)

    for src in args.inputs:
        if not src.exists():
            print(f"Missing file: {src}", file=sys.stderr)
            return 1
        out_dir = args.output_dir or src.parent
        dst = out_dir / f"{src.stem}_compressed.pdf"
        if dst.exists():
            i = 2
            while (out_dir / f"{src.stem}_compressed_{i}.pdf").exists():
                i += 1
            dst = out_dir / f"{src.stem}_compressed_{i}.pdf"
        compress_pdf(
            src,
            dst,
            args.quality,
            args.size,
            args.jpeg_quality,
            args.dpi,
            args.scale,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
