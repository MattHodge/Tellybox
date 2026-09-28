"""Frame grabs and upload clean-up for show artwork and episode thumbnails (LM-2).

Test video and image files come from ffmpeg lavfi, like tests/test_media_format.py;
skipped if ffmpeg/ffprobe aren't installed.
"""

from __future__ import annotations

import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from tellybox import images
from tellybox.images import ImageError, clean_upload, grab_frame, save_episode_thumbnail, save_show_artwork

pytestmark = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg/ffprobe not installed"
)


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *args], check=True)


def _dims(data: bytes, tmp_path: Path, name: str = "probe.jpg") -> tuple[int, int]:
    path = tmp_path / name
    path.write_bytes(data)
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    w, h = out.stdout.strip().split(",")
    return int(w), int(h)


@pytest.fixture(scope="session")
def clip_5s(tmp_path_factory) -> Path:
    """A small 1280x720, 5 s clip with a burned-in running timecode, so frames at different times differ."""
    out = tmp_path_factory.mktemp("images") / "clip.mp4"
    _ffmpeg(
        "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=5:duration=5",
        "-vf", "drawtext=text='%{pts}':fontsize=64:fontcolor=white:x=10:y=10",
        "-c:v", "libx264", "-preset", "superfast", "-pix_fmt", "yuv420p", str(out),
    )
    return out


@pytest.fixture(scope="session")
def clip_hd(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("images") / "hd.mp4"
    _ffmpeg("-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=5:duration=1",
           "-c:v", "libx264", "-preset", "superfast", "-pix_fmt", "yuv420p", str(out))
    return out


@pytest.fixture(scope="session")
def jpeg_bytes(tmp_path_factory) -> bytes:
    out = tmp_path_factory.mktemp("images") / "a.jpg"
    _ffmpeg("-f", "lavfi", "-i", "color=c=red:s=64x64:d=1", "-frames:v", "1", str(out))
    return out.read_bytes()


@pytest.fixture(scope="session")
def png_bytes(tmp_path_factory) -> bytes:
    out = tmp_path_factory.mktemp("images") / "a.png"
    _ffmpeg("-f", "lavfi", "-i", "color=c=blue:s=64x64:d=1", "-frames:v", "1", str(out))
    return out.read_bytes()


@pytest.fixture(scope="session")
def webp_bytes(tmp_path_factory) -> bytes:
    out = tmp_path_factory.mktemp("images") / "a.webp"
    _ffmpeg("-f", "lavfi", "-i", "color=c=green:s=64x64:d=1", "-frames:v", "1", str(out))
    return out.read_bytes()


@pytest.fixture(scope="session")
def wide_jpeg_bytes(tmp_path_factory) -> bytes:
    out = tmp_path_factory.mktemp("images") / "wide.jpg"
    _ffmpeg("-f", "lavfi", "-i", "color=c=yellow:s=2000x500:d=1", "-frames:v", "1", str(out))
    return out.read_bytes()


# --- grab_frame --------------------------------------------------------------------------------


def test_grab_frame_returns_jpeg_at_time(clip_5s, tmp_path):
    data = grab_frame(clip_5s, 2.0)
    assert data.startswith(b"\xff\xd8\xff")
    w, h = _dims(data, tmp_path)
    assert (w, h) == (1280, 720)


def test_grab_frame_different_times_differ(clip_5s):
    a = grab_frame(clip_5s, 0.5)
    b = grab_frame(clip_5s, 4.0)
    assert a != b  # the burned-in timecode differs


def test_grab_frame_clamps_past_the_end(clip_5s, tmp_path):
    data = grab_frame(clip_5s, 999.0)
    assert data.startswith(b"\xff\xd8\xff")
    _dims(data, tmp_path)  # doesn't raise: a real frame came back


def test_grab_frame_clamps_negative(clip_5s):
    data = grab_frame(clip_5s, -5.0)
    assert data.startswith(b"\xff\xd8\xff")


def test_grab_frame_scales_to_max_width(clip_hd, tmp_path):
    data = grab_frame(clip_hd, 0.2)
    w, h = _dims(data, tmp_path)
    assert w == 1280
    assert h % 2 == 0


def test_grab_frame_bad_video_raises(tmp_path):
    bogus = tmp_path / "not-a-video.mp4"
    bogus.write_bytes(b"not a video file")
    with pytest.raises(ImageError):
        grab_frame(bogus, 0.0)


def test_grab_frame_missing_file_raises(tmp_path):
    with pytest.raises(ImageError):
        grab_frame(tmp_path / "missing.mp4", 0.0)


# --- clean_upload --------------------------------------------------------------------------------


def test_clean_upload_jpeg(jpeg_bytes, tmp_path):
    out = clean_upload(jpeg_bytes)
    assert out.startswith(b"\xff\xd8\xff")
    w, h = _dims(out, tmp_path)
    assert w <= 1280


def test_clean_upload_png(png_bytes, tmp_path):
    out = clean_upload(png_bytes)
    assert out.startswith(b"\xff\xd8\xff")  # re-encoded to JPEG regardless of source format
    _dims(out, tmp_path)


def test_clean_upload_webp(webp_bytes, tmp_path):
    out = clean_upload(webp_bytes)
    assert out.startswith(b"\xff\xd8\xff")
    _dims(out, tmp_path)


def test_clean_upload_scales_down_to_max_width(wide_jpeg_bytes, tmp_path):
    src_w, src_h = _dims(wide_jpeg_bytes, tmp_path, "src.jpg")
    assert src_w > 1280
    out = clean_upload(wide_jpeg_bytes)
    w, h = _dims(out, tmp_path, "out.jpg")
    assert w <= 1280
    assert w / h == pytest.approx(src_w / src_h, rel=0.05)  # aspect kept


def test_clean_upload_does_not_upscale(jpeg_bytes, tmp_path):
    # jpeg_bytes is 64x64, well under the cap.
    out = clean_upload(jpeg_bytes)
    w, h = _dims(out, tmp_path)
    assert (w, h) == (64, 64)


def test_clean_upload_rejects_oversized_file():
    data = b"\xff\xd8\xff" + b"\x00" * (images.MAX_UPLOAD_BYTES + 1)
    with pytest.raises(ImageError, match="too large"):
        clean_upload(data)


def test_clean_upload_rejects_text_file():
    with pytest.raises(ImageError, match="not a JPEG, PNG or WebP"):
        clean_upload(b"hello, this is not an image\n" * 10)


def test_clean_upload_rejects_gif():
    with pytest.raises(ImageError, match="not a JPEG, PNG or WebP"):
        clean_upload(b"GIF89a" + b"\x00" * 100)


def test_clean_upload_ignores_filename_and_content_type(jpeg_bytes):
    # clean_upload only takes bytes: there is no filename or content-type to be fooled by.
    assert clean_upload(jpeg_bytes).startswith(b"\xff\xd8\xff")


# --- save helpers --------------------------------------------------------------------------------


def test_save_show_artwork_fresh_name_each_time(tmp_path, jpeg_bytes):
    rel1 = save_show_artwork(tmp_path, 7, jpeg_bytes)
    rel2 = save_show_artwork(tmp_path, 7, jpeg_bytes)
    assert rel1 != rel2
    assert rel1.startswith("art/show-7-") and rel1.endswith(".jpg")
    for rel in (rel1, rel2):
        path = tmp_path / rel
        assert path.read_bytes() == jpeg_bytes
        assert stat.S_IMODE(path.stat().st_mode) == 0o644


def test_save_episode_thumbnail_fresh_name_each_time(tmp_path, jpeg_bytes):
    rel1 = save_episode_thumbnail(tmp_path, 3, jpeg_bytes)
    rel2 = save_episode_thumbnail(tmp_path, 3, jpeg_bytes)
    assert rel1 != rel2
    assert rel1.startswith("thumbs/episode-3-") and rel1.endswith(".jpg")
    assert (tmp_path / rel1).exists() and (tmp_path / rel2).exists()


def test_save_leaves_no_temp_file_behind(tmp_path, jpeg_bytes):
    save_show_artwork(tmp_path, 1, jpeg_bytes)
    leftovers = [p for p in (tmp_path / "art").iterdir() if p.name.startswith(".")]
    assert leftovers == []
