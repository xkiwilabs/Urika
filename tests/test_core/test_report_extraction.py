"""Tests for ``extract_report_markdown`` — the narration guard.

The report agent has no file-writing tools, so its reply IS the report.
When the agent instead NARRATES ("I'll write a comprehensive final
report…", "Let me read…", "I have successfully written…") that prose
must be rejected so it never gets written over a real report.
"""

from __future__ import annotations

from urika.core.report_writer import extract_report_markdown

# A real narration blob captured in the wild: prose first, a markdown
# heading only LATER in the text (so the weak "count('\n#') >= 2" guard
# would have let it through).
_NARRATION = (
    "I'll write a comprehensive final report for your Stroop effect "
    "analysis project.\n"
    "Let me start by reading all the necessary project files.\n"
    "Now let me read the evaluation files for each experiment.\n"
    "I have now read all the relevant files. Let me check if the report "
    "file already exists.\n"
    + ("Now I will compose the report carefully. " * 10)
    + "\n\n## Report Structure\n\n"
    + ("The report will cover the abstract and methods. " * 10)
    + "\nI have successfully written the report to the requested path.\n"
)

_REAL_REPORT = (
    "# The Stroop Interference Effect\n\n"
    "## Abstract\n\n"
    + ("This study quantifies the Stroop interference effect. " * 20)
    + "\n\n## Methods\n\nWe fit mixed-effects models.\n"
)


def test_narration_is_rejected() -> None:
    assert len(_NARRATION) > 500  # guard precondition: long enough to pass length
    assert extract_report_markdown(_NARRATION) is None


def test_real_report_returned_unchanged() -> None:
    assert len(_REAL_REPORT) > 500
    assert extract_report_markdown(_REAL_REPORT) == _REAL_REPORT.strip()


def test_leading_preamble_then_heading_returns_from_heading() -> None:
    text = "Here is the report:\n\n# Title\n\n" + ("Body prose. " * 60)
    body = extract_report_markdown(text)
    assert body is not None
    assert body.startswith("# Title")


def test_short_string_is_rejected() -> None:
    assert extract_report_markdown("# Title\n\ntoo short") is None


def test_none_is_rejected() -> None:
    assert extract_report_markdown(None) is None
