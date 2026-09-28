"""Media probing and conversion to the Chromecast target format (CI-2, NF-6, NF-8).

Inputs are generated with ffmpeg lavfi once per session; clips are 1 s and small
except where a 720p / 1080p frame size is the point of the test.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from tellybox import media_format
from tellybox.media_format import (
    MediaError,
    Plan,
    StreamInfo,
    convert,
    main,
    moov_before_mdat,
    plan_for,
    probe,
    verify,
)

pytestmark = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg/ffprobe not installed"
)


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *args], check=True)


def _video(size: str, rate: int = 25) -> list[str]:
    return ["-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}:duration=1"]


def _audio(channels: int = 2) -> list[str]:
    layout = "stereo" if channels == 2 else ("mono" if channels == 1 else "5.1")
    return ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1", "-af", f"aformat=channel_layouts={layout}"]


X264_FAST = ["-c:v", "libx264", "-preset", "superfast", "-pix_fmt", "yuv420p"]


@pytest.fixture(scope="session")
def clips(tmp_path_factory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("clips")
    c = {name: d / name for name in (
        "720.mp4", "720_nofaststart.mp4", "1080.mp4", "h264_opus.mkv", "vp9_opus.webm",
        "noaudio.mp4", "yuv444.mp4", "surround.mp4",
    )}
    # Target format already: H.264 Main@4.0 720p yuv420p + AAC stereo, faststart.
    _ffmpeg(*_video("1280x720"), *_audio(), *X264_FAST, "-profile:v", "main", "-level:v", "4.0",
            "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(c["720.mp4"]))
    _ffmpeg("-i", str(c["720.mp4"]), "-c", "copy", str(c["720_nofaststart.mp4"]))
    _ffmpeg(*_video("1920x1080"), *_audio(), *X264_FAST, "-profile:v", "high", "-level:v", "4.0",
            "-c:a", "aac", "-b:a", "64k", str(c["1080.mp4"]))
    _ffmpeg(*_video("320x240"), *_audio(), *X264_FAST, "-profile:v", "high",
            "-c:a", "libopus", "-b:a", "48k", str(c["h264_opus.mkv"]))
    _ffmpeg(*_video("320x240"), *_audio(), "-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8",
            "-b:v", "200k", "-c:a", "libopus", "-b:a", "48k", str(c["vp9_opus.webm"]))
    _ffmpeg(*_video("320x240"), *X264_FAST, "-profile:v", "main", "-movflags", "+faststart", str(c["noaudio.mp4"]))
    _ffmpeg(*_video("320x240"), "-c:v", "libx264", "-preset", "superfast", "-pix_fmt", "yuv444p",
            "-c:a", "aac", str(c["yuv444.mp4"]))
    _ffmpeg(*_video("320x240"), *_audio(6), *X264_FAST, "-profile:v", "main",
            "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(c["surround.mp4"]))
    return c


def good_info(**kw) -> StreamInfo:
    base = StreamInfo(
        duration_s=60.0, video_codec="h264", video_profile="High", video_level=40, pix_fmt="yuv420p",
        width=1280, height=720, fps=25.0, audio_codec="aac", audio_channels=2, faststart=True,
    )
    return replace(base, **kw)


# --- probe ---------------------------------------------------------------------------------


def test_probe_reads_720p_h264_aac(clips):
    info = probe(clips["720.mp4"])
    assert info.video_codec == "h264"
    assert info.video_profile == "Main"
    assert info.video_level == 40
    assert info.pix_fmt == "yuv420p"
    assert (info.width, info.height) == (1280, 720)
    assert info.fps == pytest.approx(25.0)
    assert info.audio_codec == "aac"
    assert info.audio_channels == 2
    assert info.duration_s == pytest.approx(1.0, abs=0.1)
    assert info.faststart is True


def test_probe_without_audio(clips):
    info = probe(clips["noaudio.mp4"])
    assert info.audio_codec is None
    assert info.audio_channels is None


def test_probe_non_mp4_container_has_no_faststart(clips):
    info = probe(clips["vp9_opus.webm"])
    assert info.video_codec == "vp9"
    assert info.audio_codec == "opus"
    assert info.faststart is None


def test_probe_unreadable_file_raises(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video at all")
    with pytest.raises(MediaError):
        probe(bad)
    with pytest.raises(MediaError):
        probe(tmp_path / "missing.mp4")


def test_probe_audio_only_raises(tmp_path):
    a = tmp_path / "a.m4a"
    _ffmpeg(*_audio(), "-c:a", "aac", str(a))
    with pytest.raises(MediaError, match="video"):
        probe(a)


# --- faststart (moov before mdat) ------------------------------------------------------------


def test_faststart_detection(clips):
    assert moov_before_mdat(clips["720.mp4"]) is True
    assert moov_before_mdat(clips["720_nofaststart.mp4"]) is False
    assert probe(clips["720_nofaststart.mp4"]).faststart is False


def _atom(kind: bytes, payload: bytes = b"") -> bytes:
    return struct.pack(">I", 8 + len(payload)) + kind + payload


def test_faststart_handles_64bit_size_and_size_zero(tmp_path):
    # 64-bit mdat header (size field 1, then 8-byte largesize) followed by moov.
    big = struct.pack(">I", 1) + b"mdat" + struct.pack(">Q", 16 + 4) + b"data"
    p = tmp_path / "a.mp4"
    p.write_bytes(_atom(b"ftyp", b"isom") + big + _atom(b"moov"))
    assert moov_before_mdat(p) is False

    # moov first, then a size-0 mdat running to EOF.
    p.write_bytes(_atom(b"ftyp", b"isom") + _atom(b"moov") + struct.pack(">I", 0) + b"mdat" + b"x" * 50)
    assert moov_before_mdat(p) is True

    # 64-bit sized free atom before moov; size-0 mdat after.
    free = struct.pack(">I", 1) + b"free" + struct.pack(">Q", 16 + 3) + b"abc"
    p.write_bytes(_atom(b"ftyp") + free + _atom(b"moov") + struct.pack(">I", 0) + b"mdat")
    assert moov_before_mdat(p) is True

    # Truncated / garbage: no moov found.
    p.write_bytes(b"\x00\x00")
    assert moov_before_mdat(p) is False


# --- plan_for decision table (CI-2: remux existing H.264 where possible) -----------------------


@pytest.mark.parametrize(
    ("info", "expected"),
    [
        # H.264 High@4.0 720p + AAC stereo: remux only.
        (good_info(), Plan(copy_video=True, copy_audio=True, scale_to_720=False, has_audio=True)),
        (good_info(video_profile="Constrained Baseline", video_level=31, width=640, height=360),
         Plan(True, True, False, True)),
        (good_info(video_profile="Main", video_level=41), Plan(True, True, False, True)),
        # 1080p H.264: re-encode and scale down.
        (good_info(width=1920, height=1080), Plan(False, True, True, True)),
        # Level too high for the 1st-gen Chromecast.
        (good_info(video_level=51), Plan(False, True, False, True)),
        # Unsupported profile / pixel format.
        (good_info(video_profile="High 10", pix_fmt="yuv420p10le"), Plan(False, True, False, True)),
        (good_info(video_profile="High 4:4:4 Predictive", pix_fmt="yuv444p"), Plan(False, True, False, True)),
        (good_info(pix_fmt="yuv444p"), Plan(False, True, False, True)),
        # Unknown level: don't trust it.
        (good_info(video_level=None), Plan(False, True, False, True)),
        # VP9 + Opus (webm/mkv): encode both.
        (good_info(video_codec="vp9", video_profile="Profile 0", video_level=None, audio_codec="opus", faststart=None),
         Plan(False, False, False, True)),
        # H.264 + Opus: copy video, encode audio.
        (good_info(audio_codec="opus", faststart=None), Plan(True, False, False, True)),
        # AAC with more than 2 channels: downmix.
        (good_info(audio_channels=6), Plan(True, False, False, True)),
        # No audio.
        (good_info(audio_codec=None, audio_channels=None), Plan(True, False, False, False)),
        # Missing faststart alone is fixed by a remux.
        (good_info(faststart=False), Plan(True, True, False, True)),
    ],
)
def test_plan_for(info, expected):
    assert plan_for(info) == expected


def test_remux_only():
    assert Plan(True, True, False, True).remux_only
    assert Plan(True, False, False, False).remux_only
    assert not Plan(True, False, False, True).remux_only
    assert not Plan(False, True, False, True).remux_only


def test_plan_for_probed_clips(clips):
    assert plan_for(probe(clips["720.mp4"])).remux_only
    assert plan_for(probe(clips["1080.mp4"])) == Plan(False, True, True, True)
    assert plan_for(probe(clips["h264_opus.mkv"])) == Plan(True, False, False, True)
    assert plan_for(probe(clips["vp9_opus.webm"])) == Plan(False, False, False, True)
    assert plan_for(probe(clips["yuv444.mp4"])).copy_video is False
    assert plan_for(probe(clips["noaudio.mp4"])).has_audio is False
    assert plan_for(probe(clips["surround.mp4"])).copy_audio is False


# --- convert (CI-2, NF-6, NF-8) -----------------------------------------------------------------


def _convert(src: Path, dst: Path) -> list[float]:
    progress: list[float] = []
    info = probe(src)
    convert(src, dst, plan_for(info), duration_s=info.duration_s, on_progress=progress.append)
    return progress


def test_convert_remux_adds_faststart(clips, tmp_path):
    dst = tmp_path / "out.mp4"
    _convert(clips["720_nofaststart.mp4"], dst)
    info = verify(dst)
    assert info.faststart is True
    assert (info.video_profile, info.video_level) == ("Main", 40)  # copied, not re-encoded


def test_convert_audio_only_transcode(clips, tmp_path):
    dst = tmp_path / "out.mp4"
    _convert(clips["h264_opus.mkv"], dst)
    info = verify(dst)
    assert info.audio_codec == "aac"
    assert info.audio_channels == 2
    assert info.video_profile == "High"  # H.264 copied


def test_convert_1080p_encodes_to_720p(clips, tmp_path):
    dst = tmp_path / "out.mp4"
    progress = _convert(clips["1080.mp4"], dst)
    info = verify(dst)
    assert (info.width, info.height) == (1280, 720)
    assert info.video_level is not None and info.video_level <= 41
    assert progress == sorted(progress)
    assert progress[-1] == pytest.approx(1.0)
    assert all(0.0 <= p <= 1.0 for p in progress)
    assert [p.name for p in tmp_path.iterdir()] == ["out.mp4"]  # no temp leftovers


def test_convert_vp9_opus_and_surround_and_noaudio(clips, tmp_path):
    for name in ("vp9_opus.webm", "surround.mp4", "noaudio.mp4", "yuv444.mp4"):
        dst = tmp_path / f"{name}.out.mp4"
        _convert(clips[name], dst)
        info = verify(dst)
        assert info.faststart is True
        if name == "noaudio.mp4":
            assert info.audio_codec is None


def test_convert_progress_without_duration_probes_source(clips, tmp_path):
    progress: list[float] = []
    convert(clips["720.mp4"], tmp_path / "o.mp4", Plan(True, True, False, True), on_progress=progress.append)
    assert progress and progress[-1] == pytest.approx(1.0)


def test_failing_convert_leaves_no_dst(tmp_path):
    src = tmp_path / "bad.mkv"
    src.write_bytes(b"\x1a\x45\xdf\xa3 garbage garbage")
    dst = tmp_path / "out.mp4"
    with pytest.raises(MediaError) as exc:
        convert(src, dst, Plan(False, False, False, True), duration_s=1.0)
    assert str(exc.value)  # carries ffmpeg's stderr tail
    assert [p.name for p in tmp_path.iterdir()] == ["bad.mkv"]


def test_convert_timeout(clips, tmp_path):
    dst = tmp_path / "out.mp4"
    with pytest.raises(MediaError, match="timed out"):
        convert(clips["1080.mp4"], dst, Plan(False, True, True, True), timeout=0.01)
    assert list(tmp_path.iterdir()) == []


def test_convert_command_uses_nice_and_target_settings(monkeypatch, tmp_path):
    calls: list[list[str]] = []

    class Boom(Exception):
        pass

    def fake_popen(cmd, **kw):
        calls.append(cmd)
        raise Boom

    monkeypatch.setattr(media_format.subprocess, "Popen", fake_popen)
    with pytest.raises(Boom):
        convert(tmp_path / "in.webm", tmp_path / "o.mp4", Plan(False, False, True, True), duration_s=1.0, nice=10)
    cmd = calls[0]
    assert cmd[:3] == ["nice", "-n", "10"] or cmd[0].endswith("/nice")
    s = " ".join(cmd)
    for part in ("-c:v libx264", "-preset veryfast", "-crf 23", "-profile:v high", "-level:v 4.1",
                 "-pix_fmt yuv420p", "scale=-2:720", "-c:a aac", "-b:a 128k", "-ac 2",
                 "-movflags +faststart", "-map 0:v:0", "-map 0:a:0?", "-progress pipe:1"):
        assert part in s, part

    calls.clear()
    with pytest.raises(Boom):
        convert(tmp_path / "in.mp4", tmp_path / "o.mp4", Plan(True, True, False, True), duration_s=1.0, nice=0)
    cmd = calls[0]
    assert "nice" not in cmd[0]
    s = " ".join(cmd)
    assert "-c:v copy" in s and "-c:a copy" in s and "libx264" not in s


# --- verify ---------------------------------------------------------------------------------------


def test_verify_accepts_target_format(clips):
    assert verify(clips["720.mp4"]).height == 720
    verify(clips["noaudio.mp4"])  # no audio is fine


def test_verify_lists_every_violation(clips):
    with pytest.raises(MediaError) as exc:
        verify(clips["vp9_opus.webm"])
    msg = str(exc.value)
    assert "vp9" in msg and "opus" in msg and "container" in msg.lower()

    with pytest.raises(MediaError) as exc:
        verify(clips["1080.mp4"])
    msg = str(exc.value)
    assert "1080" in msg and "faststart" in msg.lower()

    with pytest.raises(MediaError, match="channels"):
        verify(clips["surround.mp4"])
    with pytest.raises(MediaError, match="yuv444p"):
        verify(clips["yuv444.mp4"])


# --- CLI ------------------------------------------------------------------------------------------


def test_cli_verify_and_probe(clips, capsys):
    assert main(["verify", str(clips["720.mp4"])]) == 0
    assert "h264" in capsys.readouterr().out
    assert main(["verify", str(clips["1080.mp4"])]) == 1
    assert "1080" in capsys.readouterr().err
    assert main(["probe", str(clips["vp9_opus.webm"])]) == 0
    assert "vp9" in capsys.readouterr().out
    assert main(["probe", "/nonexistent.mp4"]) == 1


def test_cli_as_module(clips):
    r = subprocess.run(
        [sys.executable, "-m", "tellybox.media_format", "verify", str(clips["720.mp4"])],
        capture_output=True, text=True, cwd=Path(__file__).parents[1],
    )
    assert r.returncode == 0, r.stderr
