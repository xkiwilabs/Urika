"""Specialized profilers in ``data/profiler.py`` — images, audio,
timeseries (HDF5), spatial.

Lines 54-169 in profiler.py had zero coverage. The WAV header parsing,
PIL fallback, and HDF5 group walk would silently produce empty/wrong
output on malformed inputs.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest


# ── profile_images ─────────────────────────────────────────────


def test_profile_images_empty() -> None:
    from urika.data.profiler import profile_images

    info = profile_images([])
    assert info["count"] == 0
    assert info["formats"] == []


def test_profile_images_via_pil_when_available(tmp_path: Path) -> None:
    """When PIL is installed, format + dimensions are extracted from
    each file. PIL is in the dev deps so should be available."""
    PIL = pytest.importorskip("PIL")

    img = PIL.Image.new("RGB", (50, 40), color=(0, 0, 0))
    p1 = tmp_path / "x.png"
    img.save(p1)
    img2 = PIL.Image.new("RGB", (100, 80), color=(255, 255, 255))
    p2 = tmp_path / "y.png"
    img2.save(p2)

    from urika.data.profiler import profile_images

    info = profile_images([p1, p2])
    assert info["count"] == 2
    assert "PNG" in info["formats"] or "png" in [f.lower() for f in info["formats"]]
    # Dimensions string includes min-max range.
    assert "dimensions" in info


def test_profile_images_unreadable_files_skipped(tmp_path: Path) -> None:
    """A bogus 'image' file (truncated bytes) — fallback to extension
    only, no crash."""
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not-actually-an-image")

    from urika.data.profiler import profile_images

    info = profile_images([bad])
    assert info["count"] == 1
    # Either falls back to .PNG (from extension) or empty — must not crash.
    assert isinstance(info["formats"], list)


# ── profile_audio ──────────────────────────────────────────────


def test_profile_audio_empty() -> None:
    from urika.data.profiler import profile_audio

    info = profile_audio([])
    assert info["count"] == 0


def test_profile_audio_wav_header_parsing(tmp_path: Path) -> None:
    """Construct a minimal WAV with a known sample rate and assert
    the header parser extracts it."""
    sample_rate = 44100
    bytes_per_sample = 2
    channels = 1
    duration_s = 0.1
    n_samples = int(sample_rate * duration_s)
    byte_rate = sample_rate * channels * bytes_per_sample
    data_size = n_samples * channels * bytes_per_sample

    wav = bytearray()
    wav += b"RIFF"
    wav += struct.pack("<I", 36 + data_size)
    wav += b"WAVE"
    wav += b"fmt "
    wav += struct.pack("<I", 16)
    wav += struct.pack("<H", 1)  # audio format = PCM
    wav += struct.pack("<H", channels)
    wav += struct.pack("<I", sample_rate)
    wav += struct.pack("<I", byte_rate)
    wav += struct.pack("<H", channels * bytes_per_sample)
    wav += struct.pack("<H", bytes_per_sample * 8)
    wav += b"data"
    wav += struct.pack("<I", data_size)
    wav += b"\x00" * data_size

    p = tmp_path / "a.wav"
    p.write_bytes(bytes(wav))

    from urika.data.profiler import profile_audio

    info = profile_audio([p])
    assert info["count"] == 1
    assert sample_rate in info.get("sample_rates", [])
    # Duration roughly correct (allow some rounding).
    assert info.get("total_duration_s", 0) > 0
    assert ".wav" in info["formats"]


def test_profile_audio_skips_truncated_wav(tmp_path: Path) -> None:
    """A truncated WAV file — parser bails on the read but the
    profiler still records the count + format extension."""
    p = tmp_path / "trunc.wav"
    p.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")  # header but no fmt chunk

    from urika.data.profiler import profile_audio

    info = profile_audio([p])
    assert info["count"] == 1
    assert ".wav" in info["formats"]


def test_profile_audio_non_wav_files_counted(tmp_path: Path) -> None:
    p = tmp_path / "song.mp3"
    p.write_bytes(b"\x00")  # we don't parse mp3
    from urika.data.profiler import profile_audio

    info = profile_audio([p])
    assert info["count"] == 1
    assert ".mp3" in info["formats"]


# ── profile_timeseries ─────────────────────────────────────────


def test_profile_timeseries_empty() -> None:
    from urika.data.profiler import profile_timeseries

    info = profile_timeseries([])
    assert info["count"] == 0


def test_profile_timeseries_classifies_formats(tmp_path: Path) -> None:
    p1 = tmp_path / "ts.hdf5"
    p2 = tmp_path / "rec.edf"
    p1.write_bytes(b"\x00")
    p2.write_bytes(b"\x00")
    from urika.data.profiler import profile_timeseries

    info = profile_timeseries([p1, p2])
    assert info["count"] == 2
    formats = info["formats"]
    assert ".hdf5" in formats
    assert ".edf" in formats


def test_profile_timeseries_hdf5_groups_when_h5py(tmp_path: Path) -> None:
    """Real HDF5 file → group/dataset walk via h5py."""
    h5py = pytest.importorskip("h5py")
    import numpy as np

    p = tmp_path / "x.h5"
    with h5py.File(p, "w") as f:
        f.create_group("trial1")
        f.create_dataset("trial1/eeg", data=np.zeros((10, 64)))
        f.create_dataset("trial2/audio", data=np.zeros(100))

    from urika.data.profiler import profile_timeseries

    info = profile_timeseries([p])
    assert "hdf5_groups" in info
    assert "hdf5_datasets" in info
    assert len(info["hdf5_datasets"]) >= 2


# ── profile_spatial ────────────────────────────────────────────


def test_profile_spatial_classifies_extensions(tmp_path: Path) -> None:
    paths = []
    for ext in (".ply", ".pcd", ".c3d", ".obj"):
        p = tmp_path / f"x{ext}"
        p.write_bytes(b"\x00")
        paths.append(p)
    from urika.data.profiler import profile_spatial

    info = profile_spatial(paths)
    assert info["count"] == 4
    assert set(info["formats"]) == {".ply", ".pcd", ".c3d", ".obj"}


def test_profile_spatial_empty() -> None:
    from urika.data.profiler import profile_spatial

    info = profile_spatial([])
    assert info["count"] == 0
