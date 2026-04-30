"""Tests for ``urika.data.data_hash`` (v0.4 Track 4)."""

from __future__ import annotations

from pathlib import Path


def test_hash_data_file_returns_sha256_hex(tmp_path: Path) -> None:
    from urika.data.data_hash import hash_data_file

    f = tmp_path / "x.csv"
    f.write_bytes(b"a,b,c\n1,2,3\n")
    h = hash_data_file(f)
    assert isinstance(h, str)
    assert len(h) == 64  # SHA-256 hex digest length
    # Idempotent: same content → same hash.
    assert hash_data_file(f) == h


def test_hash_data_file_returns_empty_for_missing(tmp_path: Path) -> None:
    from urika.data.data_hash import hash_data_file

    assert hash_data_file(tmp_path / "nope.csv") == ""


def test_hash_data_file_distinguishes_content(tmp_path: Path) -> None:
    from urika.data.data_hash import hash_data_file

    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_bytes(b"hello")
    b.write_bytes(b"world")
    assert hash_data_file(a) != hash_data_file(b)


def test_hash_data_files_dict_round_trip(tmp_path: Path) -> None:
    from urika.data.data_hash import hash_data_files

    f1 = tmp_path / "one.csv"
    f2 = tmp_path / "two.csv"
    f1.write_bytes(b"alpha")
    f2.write_bytes(b"beta")
    out = hash_data_files([str(f1), str(f2)])
    assert set(out) == {str(f1), str(f2)}
    assert all(len(v) == 64 for v in out.values())


def test_detect_drift_returns_empty_when_unchanged(tmp_path: Path) -> None:
    from urika.data.data_hash import detect_drift, hash_data_files

    f = tmp_path / "x.csv"
    f.write_bytes(b"unchanged")
    recorded = hash_data_files([str(f)])
    assert detect_drift(recorded, [str(f)]) == []


def test_detect_drift_flags_changed_file(tmp_path: Path) -> None:
    from urika.data.data_hash import detect_drift, hash_data_files

    f = tmp_path / "x.csv"
    f.write_bytes(b"original")
    recorded = hash_data_files([str(f)])
    f.write_bytes(b"edited")
    drift = detect_drift(recorded, [str(f)])
    assert len(drift) == 1
    assert drift[0]["path"] == str(f)
    assert drift[0]["old_hash"] != drift[0]["new_hash"]


def test_detect_drift_flags_missing_file(tmp_path: Path) -> None:
    from urika.data.data_hash import detect_drift, hash_data_files

    f = tmp_path / "x.csv"
    f.write_bytes(b"original")
    recorded = hash_data_files([str(f)])
    f.unlink()
    drift = detect_drift(recorded, [str(f)])
    assert len(drift) == 1
    assert drift[0]["new_hash"] == ""


def test_detect_drift_skips_unrecorded_paths(tmp_path: Path) -> None:
    """Files in the input list that aren't in *recorded* are not drift."""
    from urika.data.data_hash import detect_drift

    f = tmp_path / "x.csv"
    f.write_bytes(b"new file, no record")
    drift = detect_drift({}, [str(f)])
    assert drift == []
