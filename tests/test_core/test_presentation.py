"""Tests for presentation renderer."""

from __future__ import annotations

from pathlib import Path

from urika.core.presentation import render_presentation, parse_slide_json


class TestParseSlideJson:
    def test_parses_valid_json(self) -> None:
        text = """Some text
```json
{
    "title": "Test",
    "subtitle": "Sub",
    "slides": [
        {"type": "bullets", "title": "Slide 1", "bullets": ["A", "B"]}
    ]
}
```
More text"""
        result = parse_slide_json(text)
        assert result is not None
        assert result["title"] == "Test"
        assert len(result["slides"]) == 1

    def test_returns_none_for_no_json(self) -> None:
        assert parse_slide_json("no json here") is None

    def test_returns_none_for_missing_slides(self) -> None:
        text = '```json\n{"title": "test"}\n```'
        assert parse_slide_json(text) is None


class TestRenderPresentation:
    def test_creates_output_directory(self, tmp_path: Path) -> None:
        slide_data = {
            "title": "Test Presentation",
            "subtitle": "Test · 2026",
            "slides": [{"type": "bullets", "title": "Intro", "bullets": ["Hello"]}],
        }
        output = render_presentation(
            slide_data, tmp_path / "presentation", theme="light"
        )
        assert output.exists()
        assert (output / "index.html").exists()

    def test_html_contains_title(self, tmp_path: Path) -> None:
        slide_data = {
            "title": "My Research",
            "subtitle": "Lab · 2026",
            "slides": [{"type": "bullets", "title": "Results", "bullets": ["Good"]}],
        }
        output = render_presentation(slide_data, tmp_path / "pres", theme="light")
        html = (output / "index.html").read_text()
        assert "My Research" in html

    def test_stat_slide_rendered(self, tmp_path: Path) -> None:
        slide_data = {
            "title": "Test",
            "subtitle": "",
            "slides": [
                {
                    "type": "stat",
                    "title": "Key Result",
                    "stat": "99.34%",
                    "stat_label": "Accuracy",
                    "bullets": ["Above baseline"],
                }
            ],
        }
        output = render_presentation(slide_data, tmp_path / "pres", theme="light")
        html = (output / "index.html").read_text()
        assert "99.34%" in html
        assert "Accuracy" in html

    def test_figure_slide_copies_image(self, tmp_path: Path) -> None:
        # Create a fake artifact
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        (artifacts / "plot.png").write_bytes(b"fake png data")

        slide_data = {
            "title": "Test",
            "subtitle": "",
            "slides": [
                {
                    "type": "figure",
                    "title": "Results",
                    "figure": "artifacts/plot.png",
                    "figure_caption": "My plot",
                }
            ],
        }
        output = render_presentation(
            slide_data,
            tmp_path / "presentation",
            theme="light",
            experiment_dir=tmp_path,
        )
        assert (output / "figures" / "plot.png").exists()

    def test_dark_theme(self, tmp_path: Path) -> None:
        slide_data = {
            "title": "Test",
            "subtitle": "",
            "slides": [{"type": "bullets", "title": "X", "bullets": ["Y"]}],
        }
        output = render_presentation(slide_data, tmp_path / "pres", theme="dark")
        html = (output / "index.html").read_text()
        assert "theme-dark" in html
