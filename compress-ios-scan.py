# /// script
# requires-python = ">=3.11"
# dependencies = ["pikepdf>=9", "pillow", "imagequant"]
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

  2. Lossy win (opt-in, ~90%+ smaller): color-quantize via libimagequant
     (the same quantizer pngquant uses) and optionally downsample. This
     only looks good if you also fix the page size to the document's real
     physical dimensions -- otherwise a low pixel count gets stretched
     across that oversized page and looks soft. Pass --size to do that.

Usage:
    uv run compress-ios-scan.py INPUT.pdf [INPUT2.pdf ...] \
        --quality {lossless,hq,balanced,small,tiny} \
        [--size SIZE]            # A4 / A4-landscape / ... or WIDTHxHEIGHT in centimetres, e.g. 8.5x5.3
        [--colors N] [--scale PCT]   # advanced: override the preset
        [--output PATH]              # default: <input>_compressed.pdf, never overwrites input

Quality presets (color count / resolution scale, before any --size DPI math).
Rule of thumb validated against real scans: with --size set (so resolution
is judged at the document's true physical size, not some bogus oversized
page), "small" holds up well even on fine dot-matrix print - that's the
default. Go to "hq"/"balanced" if you want more safety margin, "tiny" only
if you don't need to read small print off it later.
    lossless   no recompression loss at all, no resize            (~15-20% smaller)
    hq         256 colors, 100% resolution                        (~55-70% smaller)
    balanced   64 colors, 75% resolution                          (~80% smaller)
    small      64 colors, 50% resolution   [default]              (~90% smaller)
    tiny       64 colors, 33% resolution                          (~96% smaller, use with care)
"""
from __future__ import annotations

import argparse
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from dataclasses import dataclass
from pathlib import Path

import pikepdf
from pikepdf import Array, Dictionary, Name, String
from PIL import Image

try:
    import imagequant
except ImportError:
    imagequant = None


PRESETS = {
    # name:      (colors or None for lossless, scale 0-1)
    "lossless": (None, 1.0),
    "hq":       (256, 1.0),
    "balanced": (64, 0.75),
    "small":    (64, 0.50),
    "tiny":     (64, 0.33),
}

CM_TO_PT = 72 / 2.54

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
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        ctype = data[pos + 4:pos + 8]
        payload = data[pos + 8:pos + 8 + length]
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
            check=True, capture_output=True,
        )
        return p.read_bytes()


@dataclass
class ImageResult:
    idat: bytes
    plte: bytes | None
    width: int
    height: int
    bit_depth: int
    colors: int | None  # None if not indexed


def process_image(im: Image.Image, colors: int | None, scale: float) -> ImageResult:
    im = im.convert("RGBA" if colors is not None else "RGB")
    if scale < 1.0:
        w, h = im.size
        im = im.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)

    if colors is not None:
        if imagequant is None:
            raise RuntimeError("imagequant package not available - install it or use --quality lossless")
        im = imagequant.quantize_pil_image(im, dithering_level=1.0, max_colors=colors)
        import io
        buf = io.BytesIO()
        im.save(buf, format="PNG", optimize=True)
        png_bytes = optimize_png_bytes(buf.getvalue())
        idat, plte, width, height, bit_depth, color_type = parse_png(png_bytes)
        assert color_type == 3, "expected indexed PNG"
        return ImageResult(idat, plte, width, height, bit_depth, len(plte) // 3)
    else:
        import io
        buf = io.BytesIO()
        im.save(buf, format="PNG", optimize=True)
        png_bytes = optimize_png_bytes(buf.getvalue())
        idat, plte, width, height, bit_depth, color_type = parse_png(png_bytes)
        return ImageResult(idat, None, width, height, bit_depth, None)


def compress_pdf(
    src: Path,
    dst: Path,
    quality: str,
    size_cm: tuple[float, float] | None,
    colors_override: int | None,
    scale_override: float | None,
) -> None:
    preset_colors, preset_scale = PRESETS[quality]
    colors = colors_override if colors_override is not None else preset_colors
    scale = scale_override if scale_override is not None else preset_scale

    pdf = pikepdf.open(src)
    producer = str(pdf.docinfo.get("/Producer", ""))
    if "iOS" not in producer and "Quartz" not in producer:
        print(f"Note: /Producer is '{producer}' - this doesn't look like a typical "
              f"iOS-scan PDF, but proceeding anyway.", file=sys.stderr)

    total_before = src.stat().st_size

    for page in pdf.pages:
        xobjs = page.get("/Resources", {}).get("/XObject", {})
        for name, obj in list(xobjs.items()):
            if obj.get("/Subtype") != Name.Image:
                continue

            pdf_image = pikepdf.PdfImage(obj)
            pil_im = pdf_image.as_pil_image()
            before_len = len(obj.read_raw_bytes())

            result = process_image(pil_im, colors, scale)

            if result.colors is not None:
                base_colorspace = obj.ColorSpace
                palette_obj = pdf.make_indirect(String(result.plte))
                obj.ColorSpace = Array([Name.Indexed, base_colorspace, result.colors - 1, palette_obj])
                obj.BitsPerComponent = result.bit_depth
                decode_parms = Dictionary(Predictor=15, Colors=1,
                                           BitsPerComponent=result.bit_depth, Columns=result.width)
            else:
                obj.BitsPerComponent = result.bit_depth
                decode_parms = Dictionary(Predictor=15, Colors=3,
                                           BitsPerComponent=result.bit_depth, Columns=result.width)

            if len(result.idat) >= before_len:
                print(f"  {name}: re-encode wasn't smaller ({len(result.idat)} >= {before_len}), keeping original")
                continue

            obj.Width = result.width
            obj.Height = result.height
            obj.write(result.idat, filter=Name.FlateDecode, decode_parms=decode_parms)

            # Fix page size to the real physical document size, if given.
            if size_cm is not None:
                w_pt = size_cm[0] * CM_TO_PT
                h_pt = size_cm[1] * CM_TO_PT
                page.MediaBox = Array([0, 0, w_pt, h_pt])
                content = f"q {w_pt:.4f} 0 0 {h_pt:.4f} 0 0 cm /{name} Do Q".encode("latin1")
                page.Contents = pdf.make_stream(content)

    pdf.save(dst, compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate)
    pdf.close()

    total_after = dst.stat().st_size
    pct = 100 * (1 - total_after / total_before)
    print(f"{src.name}: {total_before/1024:.1f} KB -> {dst.name}: {total_after/1024:.1f} KB "
          f"({pct:.1f}% smaller)")
    if size_cm is not None:
        print(f"  page fixed to {size_cm[0]:g} x {size_cm[1]:g} cm")


def parse_size(s: str) -> tuple[float, float]:
    raw = s.strip().lower().replace("cm", "").replace(" ", "").replace("_", "-").replace("×", "x")
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
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", type=Path)
    ap.add_argument("--quality", choices=list(PRESETS), default="small")
    ap.add_argument("--size", type=parse_size, default=None,
                     help="physical page size: ISO A-series name (A4, A4-landscape, ...) "
                          "or WIDTHxHEIGHT in centimetres, e.g. 8.5x5.3")
    ap.add_argument("--colors", type=int, default=None, help="override preset color count")
    ap.add_argument("--scale", type=float, default=None, help="override preset resolution scale (0-1)")
    ap.add_argument("--output-dir", type=Path, default=None,
                     help="directory for output files (default: same as input)")
    args = ap.parse_args()

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
        compress_pdf(src, dst, args.quality, args.size, args.colors, args.scale)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
