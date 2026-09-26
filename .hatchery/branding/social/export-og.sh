#!/usr/bin/env bash
# Capture Hatchery / Hatchery Library OG slides and stitch a GIF.
# Requires: google-chrome (or chromium), Python 3 + Pillow.
#
# Usage:
#   bash .hatchery/branding/social/export-og.sh library   # default
#   bash .hatchery/branding/social/export-og.sh hatchery
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET="${1:-library}"
CHROME="${CHROME:-$(command -v google-chrome || command -v chromium || true)}"

case "$TARGET" in
  library)
    STEM="hatchery-library-og"
    ;;
  hatchery)
    STEM="hatchery-og"
    ;;
  *)
    echo "usage: $0 [library|hatchery]" >&2
    exit 1
    ;;
esac

HTML="file://${DIR}/${STEM}.html"
EXPORT_DIR="${DIR}/export/${TARGET}"

if [[ -z "$CHROME" ]]; then
  echo "error: google-chrome or chromium not found" >&2
  exit 1
fi

if [[ ! -f "${DIR}/${STEM}.html" ]]; then
  echo "error: missing ${DIR}/${STEM}.html" >&2
  exit 1
fi

mkdir -p "$EXPORT_DIR"

capture() {
  local slide="$1"
  local out="$2"
  echo "Capturing ${TARGET} slide ${slide}…"
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars --no-first-run \
    --window-size=1280,640 \
    --virtual-time-budget=4000 \
    --screenshot="$out" \
    "${HTML}?slide=${slide}" >/dev/null 2>&1
}

capture 1 "$EXPORT_DIR/slide-1.png"
capture 2 "$EXPORT_DIR/slide-2.png"
capture 3 "$EXPORT_DIR/slide-3.png"

cp "$EXPORT_DIR/slide-1.png" "$DIR/${STEM}.png"

echo "Building ${STEM}.gif (4s per frame)…"
OG_EXPORT_DIR="$EXPORT_DIR" OG_STEM="$STEM" OG_DIR="$DIR" python3 <<'PY'
import os
from pathlib import Path
from PIL import Image

export = Path(os.environ["OG_EXPORT_DIR"])
out_dir = Path(os.environ["OG_DIR"])
stem = os.environ["OG_STEM"]
paths = [export / f"slide-{i}.png" for i in (1, 2, 3)]
out = out_dir / f"{stem}.gif"

frames = [Image.open(p).convert("RGBA") for p in paths]
quantized = [f.convert("P", palette=Image.ADAPTIVE, colors=256) for f in frames]
quantized[0].save(
    out,
    save_all=True,
    append_images=quantized[1:],
    duration=4000,
    loop=0,
    disposal=2,
)
print(f"wrote {out} ({out.stat().st_size // 1024} KiB)")
for p in (*paths, out, out_dir / f"{stem}.png"):
    size = Image.open(p).size
    print(f"  {p.name}: {p.stat().st_size // 1024} KiB {size}")
PY

echo "Done. Open ${DIR}/${STEM}.gif (Slack) or ${DIR}/${STEM}.png (static)."
