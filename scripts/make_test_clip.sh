#!/usr/bin/env bash
# Generate a synthetic test episode in the target format (CLAUDE.md "Environment"):
# 720p H.264 (Main@4.0, yuv420p) + AAC stereo, MP4 with faststart.
# A running timecode is burned in so seek/resume positions are visible on the TV,
# and an optional LABEL (e.g. "EP 1") is drawn large at the top so you can see which
# episode is playing.
#
# Usage: make_test_clip.sh [OUT] [SECONDS] [LABEL]
#   OUT      default media/test_clip.mp4
#   SECONDS  default 120
set -euo pipefail

out="${1:-media/test_clip.mp4}"
seconds="${2:-120}"
label="${3:-}"
mkdir -p "$(dirname "$out")"

filters="drawtext=text='%{pts\:hms}':fontsize=96:fontcolor=white:box=1:boxcolor=black@0.6:x=(w-tw)/2:y=h-th-60"
if [[ -n "$label" ]]; then
  # Read the label from a file so no characters need escaping in the filter graph.
  labelfile=$(mktemp)
  trap 'rm -f "$labelfile"' EXIT
  printf '%s' "$label" > "$labelfile"
  filters="drawtext=textfile=${labelfile}:expansion=none:fontsize=200:fontcolor=yellow:borderw=10:bordercolor=black:x=(w-tw)/2:y=60,${filters}"
fi

ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -i "testsrc2=size=1280x720:rate=25:duration=${seconds}" \
  -f lavfi -i "sine=frequency=440:beep_factor=4:sample_rate=48000:duration=${seconds}" \
  -vf "$filters" \
  -c:v libx264 -preset veryfast -profile:v main -level:v 4.0 -pix_fmt yuv420p -g 50 \
  -c:a aac -b:a 128k -ac 2 \
  -movflags +faststart \
  "$out"

# Verify the format the 1st-gen Chromecast needs. Prefer the app's own check
# (tellybox.media_format, stdlib only); fall back to the inline checks when the
# package isn't importable (e.g. a bare host without the repo on the path).
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$repo${PYTHONPATH:+:$PYTHONPATH}"
if python3 -c 'import tellybox.media_format' 2>/dev/null; then
  python3 -m tellybox.media_format verify "$out"  # exits non-zero listing every violation
  exit 0
else
  v=$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,profile,level,pix_fmt,width,height -of csv=p=0 "$out")
  a=$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of csv=p=0 "$out")
  echo "video: $v"
  echo "audio: $a"
  [[ "$v" == h264,Main,1280,720,yuv420p,40 ]] || { echo "unexpected video stream: $v" >&2; exit 1; }
  [[ "$a" == aac ]] || { echo "unexpected audio stream: $a" >&2; exit 1; }

  # faststart: the moov atom must come before mdat.
  python3 - "$out" <<'PY'
import struct, sys
with open(sys.argv[1], "rb") as f:
    order = []
    while len(order) < 10:
        hdr = f.read(8)
        if len(hdr) < 8:
            break
        size, kind = struct.unpack(">I4s", hdr)
        if size == 1:
            size = struct.unpack(">Q", f.read(8))[0]
            f.seek(size - 16, 1)
        else:
            f.seek(size - 8, 1)
        order.append(kind.decode())
print("atoms:", " ".join(order))
if order.index("moov") > order.index("mdat"):
    sys.exit("moov after mdat: faststart missing")
PY
fi
echo "ok: $out"
