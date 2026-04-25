"""Jinja humanize filter."""
from urika.dashboard.filters import humanize


def test_humanize_replaces_hyphens_and_titlecases():
    assert humanize("exp-001-baseline") == "Exp 001 Baseline"


def test_humanize_handles_underscores():
    assert humanize("linear_regression") == "Linear Regression"


def test_humanize_returns_empty_for_none():
    assert humanize(None) == ""
    assert humanize("") == ""


def test_humanize_keeps_already_capitalized():
    assert humanize("Already Capitalized") == "Already Capitalized"


def test_humanize_keeps_numbers():
    assert humanize("v123") == "V123"
    assert humanize("exp-123") == "Exp 123"
