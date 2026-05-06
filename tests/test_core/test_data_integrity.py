"""Tests for ``urika.core.data_integrity``.

v0.4.2 mitigation for the data-fabrication bug. The scanner inspects
an experiment's ``methods/*.py`` files and flags runs whose scripts
contain synthetic-data signals **without** any real-data references.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.core.data_integrity import (
    assess_run_data_source,
    format_suspect_warning,
)


def _seed_method(experiment_dir: Path, name: str, body: str) -> Path:
    methods = experiment_dir / "methods"
    methods.mkdir(parents=True, exist_ok=True)
    path = methods / name
    path.write_text(body, encoding="utf-8")
    return path


class TestRealDataDetection:
    def test_pd_read_csv_counts_as_real(self, tmp_path: Path) -> None:
        _seed_method(
            tmp_path,
            "linear.py",
            "import pandas as pd\ndf = pd.read_csv('data/inputs.csv')\n",
        )
        result = assess_run_data_source(tmp_path)
        assert result["real_data"] is True
        assert result["synthetic_only"] is False

    def test_data_paths_reference_counts_as_real(self, tmp_path: Path) -> None:
        _seed_method(
            tmp_path,
            "tree.py",
            "from urika.tools import load_table\n"
            "for p in data_paths:\n    load_table(p)\n",
        )
        result = assess_run_data_source(tmp_path)
        assert result["real_data"] is True

    def test_basename_match_via_project_data_paths(self, tmp_path: Path) -> None:
        """A script that hardcodes the dataset basename without a
        pandas read call still counts as real-data evidence when the
        basename comes from urika.toml::data_paths."""
        _seed_method(
            tmp_path,
            "ols.py",
            "with open('stroop.csv') as f:\n    rows = f.readlines()\n",
        )
        result = assess_run_data_source(tmp_path, project_data_paths=["data/stroop.csv"])
        assert result["real_data"] is True


class TestSyntheticOnlyFlagged:
    def test_make_classification_alone_is_suspect(self, tmp_path: Path) -> None:
        _seed_method(
            tmp_path,
            "demo.py",
            "from sklearn.datasets import make_classification\n"
            "X, y = make_classification(n_samples=200)\n",
        )
        result = assess_run_data_source(tmp_path)
        assert result["real_data"] is False
        assert result["synthetic_only"] is True
        assert any("make_classification" in h for h in result["synthetic_hits"])

    def test_simulate_helper_alone_is_suspect(self, tmp_path: Path) -> None:
        _seed_method(
            tmp_path,
            "sim.py",
            "import numpy as np\n"
            "def simulate_responses(n):\n"
            "    return np.random.normal(size=n)\n",
        )
        result = assess_run_data_source(tmp_path)
        assert result["synthetic_only"] is True

    def test_synthetic_comment_with_no_real_data_is_suspect(
        self, tmp_path: Path
    ) -> None:
        _seed_method(
            tmp_path,
            "fake.py",
            "import numpy as np\n"
            "# Generating synthetic example data\n"
            "X = np.random.normal(size=(100, 5))\n",
        )
        result = assess_run_data_source(tmp_path)
        assert result["synthetic_only"] is True


class TestSyntheticBesideRealIsAllowed:
    def test_bootstrap_off_real_data_not_flagged(self, tmp_path: Path) -> None:
        """A method that legitimately uses ``np.random`` for bootstrap
        resampling FROM real data should not be flagged. The scanner
        only flags ``synthetic_only`` (synthetic AND no real-data
        signal), so the presence of a pandas read call shields the
        run."""
        _seed_method(
            tmp_path,
            "boot.py",
            "import pandas as pd\n"
            "import numpy as np\n"
            "df = pd.read_csv('data/x.csv')\n"
            "rng = np.random.default_rng(0)\n"
            "boot_idx = rng.integers(0, len(df), size=len(df))\n",
        )
        result = assess_run_data_source(tmp_path)
        assert result["real_data"] is True
        assert result["synthetic_only"] is False

    def test_make_blobs_in_one_file_real_data_in_another(
        self, tmp_path: Path
    ) -> None:
        """If ANY method script in the experiment touches real data,
        the experiment as a whole isn't synthetic-only."""
        _seed_method(
            tmp_path,
            "real.py",
            "import pandas as pd\ndf = pd.read_csv('data/x.csv')\n",
        )
        _seed_method(
            tmp_path,
            "demo.py",
            "from sklearn.datasets import make_blobs\nX, y = make_blobs()\n",
        )
        result = assess_run_data_source(tmp_path)
        # Both signals fire; synthetic_only requires NO real-data signal.
        assert result["real_data"] is True
        assert result["synthetic_only"] is False


class TestEdgeCases:
    def test_no_methods_dir_returns_clean(self, tmp_path: Path) -> None:
        result = assess_run_data_source(tmp_path)
        assert result["real_data"] is False
        assert result["synthetic_only"] is False
        assert result["scripts_scanned"] == 0

    def test_empty_methods_dir(self, tmp_path: Path) -> None:
        (tmp_path / "methods").mkdir()
        result = assess_run_data_source(tmp_path)
        assert result["scripts_scanned"] == 0
        assert result["synthetic_only"] is False

    def test_unreadable_script_skipped_not_crashed(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """If a method file can't be read, scanner skips it instead of
        raising — the orchestrator should never be brought down by a
        permissions or encoding glitch."""
        path = _seed_method(tmp_path, "ok.py", "import pandas as pd\npd.read_csv('x')\n")
        # Simulate read failure by patching read_text to raise OSError.
        original_read = Path.read_text

        def boom(self, *args, **kwargs):
            if self.name == "ok.py":
                raise OSError("permission denied")
            return original_read(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", boom)
        result = assess_run_data_source(tmp_path)
        # We unreadable-skipped the only file → scripts_scanned still 0.
        assert result["scripts_scanned"] == 0
        assert result["real_data"] is False


class TestFormatSuspectWarning:
    def test_returns_empty_when_not_suspect(self) -> None:
        assert format_suspect_warning({"synthetic_only": False}) == ""

    def test_includes_pattern_sample(self) -> None:
        assessment = {
            "synthetic_only": True,
            "synthetic_hits": ["demo.py::make_classification"],
            "scripts_scanned": 1,
        }
        msg = format_suspect_warning(assessment)
        assert "SUSPECT" in msg
        assert "make_classification" in msg
