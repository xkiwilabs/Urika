from datetime import datetime, timezone, timedelta
import os

import urika.core.project_memory as pm


def test_list_archive_returns_entries_by_month(tmp_path):
    proj = tmp_path / "proj"
    (proj / "memory").mkdir(parents=True)
    pm.save_entry(proj, mem_type="user", description="a", body="body content")
    name = pm.list_entries(proj)[0]["filename"]
    pm.archive_entry(proj, name)
    entries = pm.list_archive(proj)
    assert len(entries) == 1
    assert entries[0]["filename"] == name
    assert "month" in entries[0]
    # Month format is YYYY-MM
    assert len(entries[0]["month"]) == 7 and entries[0]["month"][4] == "-"


def test_list_archive_empty_when_no_archive_dir(tmp_path):
    proj = tmp_path / "proj"
    (proj / "memory").mkdir(parents=True)
    assert pm.list_archive(proj) == []


def test_list_archive_filters_by_month(tmp_path):
    proj = tmp_path / "proj"
    (proj / "memory").mkdir(parents=True)
    # Manually create archive/<YYYY-MM>/ files since we can't time-travel
    (proj / "memory" / "archive" / "2024-01").mkdir(parents=True)
    (proj / "memory" / "archive" / "2024-02").mkdir(parents=True)
    (proj / "memory" / "archive" / "2024-01" / "user_jan.md").write_text(
        "---\nname: jan\ntype: user\n---\nbody"
    )
    (proj / "memory" / "archive" / "2024-02" / "user_feb.md").write_text(
        "---\nname: feb\ntype: user\n---\nbody"
    )
    jan_only = pm.list_archive(proj, month="2024-01")
    assert len(jan_only) == 1
    assert jan_only[0]["month"] == "2024-01"


def test_diff_between_classifies_added(tmp_path):
    proj = tmp_path / "proj"
    (proj / "memory").mkdir(parents=True)
    t0 = datetime.now(timezone.utc) - timedelta(hours=1)
    t2 = datetime.now(timezone.utc) + timedelta(hours=1)
    pm.save_entry(proj, mem_type="user", description="new", body="b")
    diff = pm.diff_between(proj, from_ts=t0, to_ts=t2)
    assert len(diff["added"]) == 1


def test_diff_between_classifies_archived(tmp_path):
    proj = tmp_path / "proj"
    (proj / "memory").mkdir(parents=True)
    t0 = datetime.now(timezone.utc) - timedelta(hours=1)
    t2 = datetime.now(timezone.utc) + timedelta(hours=1)
    pm.save_entry(proj, mem_type="user", description="old", body="b")
    name = pm.list_entries(proj)[0]["filename"]
    pm.archive_entry(proj, name)
    diff = pm.diff_between(proj, from_ts=t0, to_ts=t2)
    # Note: the archive_entry moved it, so 'added' is empty (the file no longer
    # lives in memory_dir) and 'archived' contains it.
    assert len(diff["archived"]) == 1
    assert diff["archived"][0]["filename"] == name
    assert diff["archived"][0]["month"]  # YYYY-MM populated


def test_diff_between_excludes_outside_window(tmp_path):
    proj = tmp_path / "proj"
    (proj / "memory").mkdir(parents=True)
    pm.save_entry(proj, mem_type="user", description="x", body="b")
    name = pm.list_entries(proj)[0]["filename"]
    # Backdate the file
    old_mtime = (datetime.now(timezone.utc) - timedelta(days=10)).timestamp()
    os.utime(proj / "memory" / name, (old_mtime, old_mtime))
    # Window is recent
    diff = pm.diff_between(
        proj,
        from_ts=datetime.now(timezone.utc) - timedelta(hours=1),
        to_ts=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    assert diff["added"] == []


def test_diff_between_handles_empty_project(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()  # no memory/ dir
    diff = pm.diff_between(
        proj,
        from_ts=datetime.now(timezone.utc) - timedelta(hours=1),
        to_ts=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    assert diff == {"added": [], "archived": [], "trashed": []}
