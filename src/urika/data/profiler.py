"""Dataset profiling — basic statistics from a DataFrame."""

from __future__ import annotations

import struct
from pathlib import Path

import pandas as pd

from urika.data.models import DataSummary


def profile_dataset(df: pd.DataFrame) -> DataSummary:
    """Generate profiling stats from a DataFrame."""
    columns = list(df.columns)
    dtypes = {col: str(df[col].dtype) for col in columns}
    missing_counts = {col: int(df[col].isna().sum()) for col in columns}

    numeric_cols = df.select_dtypes(include="number").columns
    numeric_stats: dict[str, dict[str, float]] = {}
    for col in numeric_cols:
        series = df[col].dropna()
        if len(series) == 0:
            continue
        numeric_stats[col] = {
            "mean": float(series.mean()),
            "std": float(series.std()),
            "min": float(series.min()),
            "max": float(series.max()),
            "median": float(series.median()),
        }

    return DataSummary(
        n_rows=len(df),
        n_columns=len(columns),
        columns=columns,
        dtypes=dtypes,
        missing_counts=missing_counts,
        numeric_stats=numeric_stats,
    )


def profile_images(paths: list[Path]) -> dict:
    """Profile image files -- count, dimensions, formats."""
    info: dict = {"count": len(paths), "formats": [], "sizes": []}
    try:
        from PIL import Image

        for p in paths[:10]:  # sample first 10
            try:
                img = Image.open(p)
                info["formats"].append(img.format or p.suffix.upper().lstrip("."))
                info["sizes"].append(img.size)
                img.close()
            except Exception:
                info["formats"].append(p.suffix.upper().lstrip("."))
        info["formats"] = sorted(set(info["formats"]))
        if info["sizes"]:
            widths = [s[0] for s in info["sizes"]]
            heights = [s[1] for s in info["sizes"]]
            info["dimensions"] = (
                f"{min(widths)}-{max(widths)} x {min(heights)}-{max(heights)}"
            )
        del info["sizes"]
    except ImportError:
        info["formats"] = sorted({p.suffix.upper().lstrip(".") for p in paths})
        info["note"] = "PIL not installed -- install Pillow for detailed image profiling"
        del info["sizes"]
    return info


def profile_audio(paths: list[Path]) -> dict:
    """Profile audio files -- count, duration, sample rate."""
    info: dict = {"count": len(paths), "formats": set()}
    durations: list[float] = []
    sample_rates: list[int] = []
    for p in paths[:10]:
        info["formats"].add(p.suffix.lower())
        # Basic WAV header parsing (no dependency needed)
        if p.suffix.lower() == ".wav":
            try:
                with open(p, "rb") as f:
                    f.read(4)  # RIFF
                    f.read(4)  # size
                    f.read(4)  # WAVE
                    f.read(4)  # fmt
                    f.read(4)  # chunk size
                    f.read(2)  # audio format
                    _channels = struct.unpack("<H", f.read(2))[0]
                    sr = struct.unpack("<I", f.read(4))[0]
                    sample_rates.append(sr)
                    byte_rate = struct.unpack("<I", f.read(4))[0]
                    f.read(2)  # block align
                    f.read(2)  # bits per sample
                    # Find data chunk
                    while True:
                        chunk_id = f.read(4)
                        if not chunk_id:
                            break
                        chunk_size = struct.unpack("<I", f.read(4))[0]
                        if chunk_id == b"data":
                            if byte_rate > 0:
                                durations.append(chunk_size / byte_rate)
                            break
                        f.seek(chunk_size, 1)
            except Exception:
                pass
    info["formats"] = sorted(info["formats"])
    if durations:
        info["total_duration_s"] = round(sum(durations), 1)
        info["avg_duration_s"] = round(sum(durations) / len(durations), 1)
    if sample_rates:
        info["sample_rates"] = sorted(set(sample_rates))
    return info


def profile_timeseries(paths: list[Path]) -> dict:
    """Profile time series files -- count, formats, basic structure."""
    info: dict = {"count": len(paths), "formats": set()}
    for p in paths[:5]:
        info["formats"].add(p.suffix.lower())
    info["formats"] = sorted(info["formats"])
    # Try HDF5 if available
    h5_files = [p for p in paths if p.suffix.lower() in (".hdf5", ".h5", ".hdf")]
    if h5_files:
        try:
            import h5py

            with h5py.File(h5_files[0], "r") as f:
                info["hdf5_groups"] = list(f.keys())[:20]
                datasets: list[dict] = []

                def _visit(name: str, obj: object) -> None:
                    if isinstance(obj, h5py.Dataset):
                        datasets.append(
                            {
                                "name": name,
                                "shape": obj.shape,
                                "dtype": str(obj.dtype),
                            }
                        )

                f.visititems(_visit)
                info["hdf5_datasets"] = datasets[:20]
        except ImportError:
            info["note"] = "h5py not installed -- install for HDF5 profiling"
        except Exception:
            pass
    return info


def profile_spatial(paths: list[Path]) -> dict:
    """Profile spatial/3D files -- count, formats."""
    info: dict = {"count": len(paths), "formats": set()}
    for p in paths:
        info["formats"].add(p.suffix.lower())
    info["formats"] = sorted(info["formats"])
    return info
