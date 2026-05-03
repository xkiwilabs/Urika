#!/usr/bin/env python3
"""Regenerate ``docs/assets/header.svg`` and ``docs/assets/header.png``
for a release.

Reads the version from ``pyproject.toml`` by default; pass
``--version 0.4.2`` to override (useful when running before the
version-bump commit).

Strategy: re-render the actual ``urika.cli_display.print_header``
output via Rich's ``Console(record=True)`` so the image matches the
real CLI exactly (box borders, version label in the top-left, ASCII
art logo, blue/dim colours). Rich's ``export_svg`` produces a
terminal-styled SVG; cairosvg rasterises it to PNG at 2× DPI.

Usage:
    # Regenerate from the version in pyproject.toml
    python dev/scripts/update-header.py

    # Override version (e.g. before the bump commit)
    python dev/scripts/update-header.py --version 0.4.2

    # Print what would happen, write nothing
    python dev/scripts/update-header.py --dry-run

Run as part of the release workflow before invoking
``release-to-main.sh`` so both artifacts ship with the new version
embedded.
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import tomllib
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = REPO_ROOT / "src"
PYPROJECT = REPO_ROOT / "pyproject.toml"
ASSETS_DIR = REPO_ROOT / "docs" / "assets"
SVG_PATH = ASSETS_DIR / "header.svg"
PNG_PATH = ASSETS_DIR / "header.png"

# ANSI SGR escape pattern used to translate ``print_header``'s raw
# ANSI output into Rich markup. ``print_header`` only uses these
# codes (see urika/cli_display.py:_C):
#   34 = blue, 1 = bold, 2 = dim, 0 = reset
_ANSI_RE = re.compile(r"\x1b\[(\d+)m")
_ANSI_TO_RICH = {
    "0": "/",          # reset — close all
    "1": "bold",
    "2": "dim",
    "34": "blue",
}


def _read_version_from_pyproject() -> str:
    if not PYPROJECT.exists():
        raise SystemExit(f"pyproject.toml not found at {PYPROJECT}")
    with open(PYPROJECT, "rb") as f:
        data = tomllib.load(f)
    v = data.get("project", {}).get("version", "")
    if not v:
        raise SystemExit("pyproject.toml has no [project].version")
    return v


def _capture_header_ansi(version: str) -> str:
    """Run ``urika.cli_display.print_header`` with ANSI codes enabled
    and return the captured text.

    ``print_header`` reads the version from importlib.metadata, so we
    monkeypatch ``importlib.metadata.version`` to return the version
    we want — this lets us regenerate the header for a release before
    its package metadata is installed.
    """
    sys.path.insert(0, str(SRC_PATH))
    try:
        # Force colour on even though stdout is being captured.
        import os
        os.environ["FORCE_COLOR"] = "1"
        os.environ.pop("NO_COLOR", None)

        import importlib.metadata as _imd
        original_version = _imd.version

        def _patched_version(name: str) -> str:
            if name == "urika":
                return version
            return original_version(name)

        _imd.version = _patched_version  # type: ignore[assignment]

        # cli_display.disable() is called at import time when stdout
        # isn't a TTY (which it isn't here — we're redirecting to a
        # StringIO). Restore the ANSI codes on the _C palette so
        # print_header emits the colours we need to capture.
        import urika.cli_display as cli_display
        cli_display._C.BLUE = "\033[34m"
        cli_display._C.BOLD = "\033[1m"
        cli_display._C.DIM = "\033[2m"
        cli_display._C.RESET = "\033[0m"

        buf = io.StringIO()
        with redirect_stdout(buf):
            cli_display.print_header()
        return buf.getvalue()
    finally:
        sys.path.pop(0)


def _ansi_to_rich_text(ansi: str):
    """Convert ``print_header``'s ANSI-colored text into a Rich Text
    object that preserves the colour spans.

    ``print_header`` emits a small fixed set of SGR codes (0/1/2/34);
    we walk the string, applying / closing styles as the codes flip,
    so the output renders identically when Rich emits it again.
    """
    from rich.text import Text

    out = Text()
    pos = 0
    style_stack: list[str] = []

    for m in _ANSI_RE.finditer(ansi):
        if m.start() > pos:
            chunk = ansi[pos:m.start()]
            style = " ".join(style_stack) if style_stack else None
            out.append(chunk, style=style)
        code = m.group(1)
        rich_style = _ANSI_TO_RICH.get(code)
        if rich_style == "/":
            style_stack.clear()
        elif rich_style:
            style_stack.append(rich_style)
        # Unknown codes (none expected from print_header) are dropped.
        pos = m.end()

    if pos < len(ansi):
        chunk = ansi[pos:]
        style = " ".join(style_stack) if style_stack else None
        out.append(chunk, style=style)
    return out


def _ensure_jetbrains_mono() -> None:
    """Install JetBrains Mono into ``~/.local/share/fonts`` if missing.

    Cairosvg uses fontconfig to resolve font-family declarations.
    Without a programming font that handles box-drawing glyphs
    cell-perfectly (DejaVu Sans Mono — the usual fontconfig fallback
    — does not), the URIKA ASCII art renders with row overlap
    because the glyph cell height exceeds the line height. JetBrains
    Mono is SIL-OFL licensed, free to bundle, and renders box-
    drawing characters at a single cell height.
    """
    import shutil
    import subprocess
    import urllib.request
    import zipfile

    fonts_dir = Path.home() / ".local" / "share" / "fonts"
    target = fonts_dir / "JetBrainsMono-Regular.ttf"
    if target.exists():
        return

    print("  installing JetBrains Mono into ~/.local/share/fonts ...",
          file=sys.stderr)
    fonts_dir.mkdir(parents=True, exist_ok=True)
    url = (
        "https://github.com/JetBrains/JetBrainsMono/releases/download/"
        "v2.304/JetBrainsMono-2.304.zip"
    )
    zip_path = fonts_dir / ".jbm-tmp.zip"
    urllib.request.urlretrieve(url, zip_path)
    with zipfile.ZipFile(zip_path) as z:
        for name in (
            "fonts/ttf/JetBrainsMono-Regular.ttf",
            "fonts/ttf/JetBrainsMono-Bold.ttf",
        ):
            with z.open(name) as src, open(
                fonts_dir / Path(name).name, "wb"
            ) as dst:
                shutil.copyfileobj(src, dst)
    zip_path.unlink()
    if shutil.which("fc-cache"):
        subprocess.run(
            ["fc-cache", "-f", str(fonts_dir)],
            check=False, capture_output=True,
        )


def _patch_svg_font(svg_text: str) -> str:
    """Swap Rich's default font-family for JetBrains Mono so cairosvg
    rasterises the box-drawing ASCII art cell-perfectly.

    Rich's SVG_EXPORT template names ``Fira Code`` first; cairosvg
    can't resolve the cdn ``@font-face`` URL offline so it falls
    through to whatever fontconfig picks for ``monospace`` (usually
    DejaVu Sans Mono on Linux), whose box-drawing glyphs are too
    tall for the line height. Substituting JetBrains Mono in CSS
    fixes the rendering without touching Rich internals.
    """
    return svg_text.replace(
        '"Fira Code"',
        '"JetBrains Mono", "Fira Code"',
    )


def _render_svg(version: str) -> str:
    """Render the captured header into a Rich-exported SVG.

    Uses Rich's ``SVG_EXPORT`` terminal theme for a true blue (vs.
    MONOKAI's purple-leaning blue) on a dark grey background that
    reads as "screenshot of a real terminal". Width is fixed at
    90 cols which matches the CLI's print_header bounds.
    """
    _ensure_jetbrains_mono()

    from rich.console import Console
    from rich.terminal_theme import SVG_EXPORT_THEME

    ansi = _capture_header_ansi(version)
    text = _ansi_to_rich_text(ansi)

    console = Console(
        record=True,
        width=90,
        legacy_windows=False,
        color_system="truecolor",
        file=io.StringIO(),  # discard live output
        force_terminal=True,
    )
    console.print(text)
    svg = console.export_svg(theme=SVG_EXPORT_THEME, title="urika")
    return _patch_svg_font(svg)


def _render_png(svg_text: str, scale: int = 2) -> bytes:
    """SVG → PNG via cairosvg at *scale*× resolution. cairosvg's
    raster output is crisp enough for README display at 2×.
    """
    import cairosvg

    # Parse the SVG's intrinsic dimensions so the rasterised PNG
    # preserves aspect ratio. Rich's exported SVG declares width /
    # height in px on the root <svg>.
    w_match = re.search(r'width="(\d+(?:\.\d+)?)"', svg_text)
    h_match = re.search(r'height="(\d+(?:\.\d+)?)"', svg_text)
    if w_match and h_match:
        out_w = int(float(w_match.group(1)) * scale)
        out_h = int(float(h_match.group(1)) * scale)
    else:
        out_w = out_h = None  # let cairosvg use defaults

    return cairosvg.svg2png(
        bytestring=svg_text.encode("utf-8"),
        output_width=out_w,
        output_height=out_h,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version",
        default=None,
        help="Version string (default: read from pyproject.toml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would happen but write nothing.",
    )
    args = parser.parse_args()

    version = args.version or _read_version_from_pyproject()
    print(f"Generating header for v{version}", file=sys.stderr)

    svg_text = _render_svg(version)
    png_bytes = _render_png(svg_text)

    if args.dry_run:
        print(f"  would write {SVG_PATH} ({len(svg_text)} bytes)",
              file=sys.stderr)
        print(f"  would write {PNG_PATH} ({len(png_bytes)} bytes)",
              file=sys.stderr)
        return

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    SVG_PATH.write_text(svg_text, encoding="utf-8")
    print(f"  wrote {SVG_PATH} ({len(svg_text)} bytes)", file=sys.stderr)
    PNG_PATH.write_bytes(png_bytes)
    print(f"  wrote {PNG_PATH} ({len(png_bytes)} bytes)", file=sys.stderr)


if __name__ == "__main__":
    main()
