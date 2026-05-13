"""Integration: ``project_builder._read_data_file`` per-format.

The dispatcher at ``core/project_builder.py:431`` routes by file
extension to ``pd.read_csv`` / ``read_excel`` / ``read_parquet`` /
``read_json`` / ``read_feather`` / ``read_spss`` / ``read_stata``.
Pre-this-file, *only the CSV branch* was exercised by any test (every
other branch lives unused until a user uploads a `.xlsx`/`.parquet`/`.sav`/etc.
project — at which point a missing optional dep or a pandas API
break is discovered in production).

Each test writes a real small fixture via the matching pandas writer,
reads it back through ``_read_data_file``, and asserts the DataFrame
shape + a sample value. Marked ``integration`` because each test
exercises a real pandas reader and may need an optional dependency.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from urika.core.project_builder import _read_data_file

pytestmark = pytest.mark.integration


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {"x": [1, 2, 3, 4], "y": [10.0, 20.0, 30.0, 40.0], "g": ["a", "b", "a", "b"]}
    )


def _assert_round_trip(df: pd.DataFrame) -> None:
    assert len(df) == 4
    assert "x" in df.columns and "y" in df.columns and "g" in df.columns
    assert int(df["x"].iloc[0]) == 1
    assert float(df["y"].iloc[-1]) == 40.0


def test_read_csv(tmp_path: Path) -> None:
    p = tmp_path / "d.csv"
    _sample_df().to_csv(p, index=False)
    _assert_round_trip(_read_data_file(p))


def test_read_tsv(tmp_path: Path) -> None:
    p = tmp_path / "d.tsv"
    _sample_df().to_csv(p, sep="\t", index=False)
    _assert_round_trip(_read_data_file(p))


def test_read_xlsx(tmp_path: Path) -> None:
    pytest.importorskip("openpyxl")
    p = tmp_path / "d.xlsx"
    _sample_df().to_excel(p, index=False)
    _assert_round_trip(_read_data_file(p))


def test_read_parquet(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    p = tmp_path / "d.parquet"
    _sample_df().to_parquet(p, index=False)
    _assert_round_trip(_read_data_file(p))


def test_read_json(tmp_path: Path) -> None:
    # pandas ``read_json`` round-trips dict-of-columns format by default
    # when the writer uses ``orient="columns"``. ``to_json`` default is
    # ``columns`` which round-trips.
    p = tmp_path / "d.json"
    _sample_df().to_json(p)
    df = _read_data_file(p)
    assert set(df.columns) >= {"x", "y", "g"}
    assert int(df["x"].iloc[0]) == 1


def test_read_feather(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    p = tmp_path / "d.feather"
    _sample_df().to_feather(p)
    _assert_round_trip(_read_data_file(p))


def test_read_arrow_extension_via_feather_reader(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    p = tmp_path / "d.arrow"
    # ``.arrow`` routes through ``read_feather`` per the dispatcher.
    _sample_df().to_feather(p)
    _assert_round_trip(_read_data_file(p))


def test_read_stata(tmp_path: Path) -> None:
    p = tmp_path / "d.dta"
    df = _sample_df()
    # Stata can't write string columns straight from object dtype on all
    # pandas versions — coerce to ``category`` which writes as Stata
    # value-labelled int.
    df["g"] = df["g"].astype("category")
    df.to_stata(p, write_index=False)
    out = _read_data_file(p)
    assert len(out) == 4
    assert int(out["x"].iloc[0]) == 1


def test_read_spss(tmp_path: Path) -> None:
    pyreadstat = pytest.importorskip("pyreadstat")
    p = tmp_path / "d.sav"
    pyreadstat.write_sav(_sample_df(), str(p))
    out = _read_data_file(p)
    assert len(out) == 4
    assert int(out["x"].iloc[0]) == 1


def test_unknown_extension_falls_back_to_csv_reader(tmp_path: Path) -> None:
    """Belt-and-braces: the default branch reads via ``read_csv``."""
    p = tmp_path / "d.weird"
    _sample_df().to_csv(p, index=False)
    _assert_round_trip(_read_data_file(p))
