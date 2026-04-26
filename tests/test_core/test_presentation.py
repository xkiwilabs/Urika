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

    def test_title_slide_includes_keyboard_hint(self, tmp_path: Path) -> None:
        """Title slide should remind viewers about reveal.js shortcuts so
        they can find speaker notes (S), fullscreen (F), and the help
        overlay (?). Hint only appears on slide 1."""
        slide_data = {
            "title": "T",
            "subtitle": "",
            "slides": [{"type": "bullets", "title": "B", "bullets": ["x"]}],
        }
        output = render_presentation(slide_data, tmp_path / "pres", theme="light")
        html = (output / "index.html").read_text()
        # CSS rule + the markup both mention the class, but only the
        # markup uses an <aside> tag — there should be exactly one.
        assert html.count('<aside class="urika-keys-hint">') == 1
        assert "<kbd>S</kbd>" in html
        assert "<kbd>F</kbd>" in html
        assert "<kbd>?</kbd>" in html
        # The hint <aside> must live inside the title-slide section,
        # before the second <section> opens (the bullet slide).
        title_section = html.find('<section class="title-slide">')
        second_section = html.find("<section", title_section + 1)
        aside_pos = html.find('<aside class="urika-keys-hint">')
        assert title_section < aside_pos < second_section

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


class TestSpeakerNotes:
    def test_notes_render_as_reveal_aside(self, tmp_path: Path) -> None:
        data = {
            "title": "T",
            "subtitle": "S",
            "slides": [
                {
                    "type": "bullets",
                    "title": "Slide",
                    "bullets": ["a"],
                    "notes": "Hello notes.",
                },
                {
                    "type": "stat",
                    "title": "K",
                    "stat": "99%",
                    "stat_label": "label",
                    "notes": "Stat notes.",
                },
            ],
        }
        out = render_presentation(data, tmp_path)
        html = (out / "index.html").read_text()
        assert '<aside class="notes">Hello notes.</aside>' in html
        assert '<aside class="notes">Stat notes.</aside>' in html

    def test_notes_are_html_escaped(self, tmp_path: Path) -> None:
        data = {
            "title": "T",
            "subtitle": "",
            "slides": [
                {
                    "type": "bullets",
                    "title": "x",
                    "bullets": [],
                    "notes": "<script>x</script>",
                },
            ],
        }
        out = render_presentation(data, tmp_path)
        html = (out / "index.html").read_text()
        # The notes content must be escaped, so the raw <script> tag does not
        # appear inside any notes aside. Other parts of the template may
        # legitimately have unrelated <script> tags for reveal.js itself, so
        # assert on the escaped form.
        assert (
            '<aside class="notes">&lt;script&gt;x&lt;/script&gt;</aside>' in html
        )


class TestMissingFigurePlaceholder:
    def test_missing_figure_renders_placeholder(self, tmp_path: Path) -> None:
        """Agent-referenced figure that doesn't exist → visible placeholder, not broken <img>."""
        data = {
            "title": "T",
            "subtitle": "",
            "slides": [
                {
                    "type": "figure",
                    "title": "Results",
                    "figure": "artifacts/does_not_exist.png",
                    "figure_caption": "cap",
                    "notes": "n",
                },
            ],
        }
        out = render_presentation(data, tmp_path, experiment_dir=tmp_path / "nowhere")
        html = (out / "index.html").read_text()
        # Placeholder must be visible (not a broken image tag).
        assert "figure-missing" in html
        # The referenced path should be shown so the user can see what went wrong.
        assert "does_not_exist.png" in html
        # No <img> tag pointing at the missing figure.
        assert '<img src="figures/does_not_exist.png"' not in html

    def test_missing_figure_in_two_col_renders_placeholder(self, tmp_path: Path) -> None:
        data = {
            "title": "T",
            "subtitle": "",
            "slides": [
                {
                    "type": "figure-text",
                    "title": "Res",
                    "figure": "artifacts/nope.png",
                    "figure_caption": "cap",
                    "bullets": ["a"],
                    "notes": "n",
                },
            ],
        }
        out = render_presentation(data, tmp_path, experiment_dir=tmp_path / "nowhere")
        html = (out / "index.html").read_text()
        assert "figure-missing" in html
        assert "nope.png" in html

    def test_existing_figure_still_renders_as_img(self, tmp_path: Path) -> None:
        """Regression guard — existing figures must still produce <img>."""
        experiment_dir = tmp_path / "exp"
        (experiment_dir / "artifacts").mkdir(parents=True)
        (experiment_dir / "artifacts" / "real.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        data = {
            "title": "T",
            "subtitle": "",
            "slides": [
                {
                    "type": "figure",
                    "title": "Results",
                    "figure": "artifacts/real.png",
                    "figure_caption": "cap",
                    "notes": "n",
                },
            ],
        }
        out = render_presentation(data, tmp_path / "out", experiment_dir=experiment_dir)
        html = (out / "index.html").read_text()
        assert '<img src="figures/real.png"' in html
        assert "figure-missing" not in html


class TestExplainerSlide:
    def test_explainer_slide_type(self, tmp_path: Path) -> None:
        data = {
            "title": "T",
            "subtitle": "",
            "slides": [
                {
                    "type": "explainer",
                    "title": "What is LOSO?",
                    "lead": "Leave-one-session-out cross-validation.",
                    "body": "Each session is held out in turn, training on the others.",
                    "notes": "Explainer notes.",
                },
            ],
        }
        out = render_presentation(data, tmp_path)
        html = (out / "index.html").read_text()
        assert "Leave-one-session-out" in html
        assert "training on the others" in html
        assert '<aside class="notes">Explainer notes.</aside>' in html


class TestEndToEndDeck:
    """Smoke test: a realistic deck with every current slide type renders
    cleanly, all notes land in <aside class="notes">, figure slides use the
    real <img>/placeholder split, and nothing is silently dropped.
    """

    def test_full_deck_with_all_slide_types_and_notes(self, tmp_path: Path) -> None:
        experiment_dir = tmp_path / "exp"
        (experiment_dir / "artifacts").mkdir(parents=True)
        (experiment_dir / "artifacts" / "chart.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        data = {
            "title": "DHT Target Selection",
            "subtitle": "Project · 2026-04-24",
            "slides": [
                {
                    "type": "bullets",
                    "title": "Motivation",
                    "bullets": ["Study of goal-directed reaching", "35 participants"],
                    "notes": "Notes for motivation slide.",
                },
                {
                    "type": "explainer",
                    "title": "What is LOSO?",
                    "lead": "Leave-one-session-out cross-validation.",
                    "body": "Each session is held out and the model trains on the others.",
                    "notes": "Narrated version of LOSO.",
                },
                {
                    "type": "figure",
                    "title": "Model comparison",
                    "figure": "artifacts/chart.png",
                    "figure_caption": "AUC by model family",
                    "notes": "Figure-slide notes.",
                },
                {
                    "type": "stat",
                    "title": "Headline",
                    "stat": "92.4%",
                    "stat_label": "AUC on held-out sessions",
                    "notes": "Headline-slide notes.",
                },
            ],
        }
        out = render_presentation(data, tmp_path / "deck", experiment_dir=experiment_dir)
        html = (out / "index.html").read_text()

        # Every slide's notes appeared as a speaker-notes aside.
        for note in (
            "Notes for motivation slide.",
            "Narrated version of LOSO.",
            "Figure-slide notes.",
            "Headline-slide notes.",
        ):
            assert f'<aside class="notes">{note}</aside>' in html, (
                f"missing speaker notes: {note}"
            )

        # Figure landed as a real <img>, not a placeholder.
        assert '<img src="figures/chart.png"' in html
        assert "figure-missing" not in html

        # Explainer body text is visible on-slide.
        assert "Each session is held out" in html

        # Stat slide carries the headline number.
        assert "92.4%" in html
