"""Prompt builders for the interactive project builder."""

from __future__ import annotations

from typing import Any

from urika.core.source_scanner import ScanResult
from urika.data.models import DataSummary


def build_scoping_prompt(
    scan_result: ScanResult,
    data_summary: DataSummary | None,
    description: str,
    context: str = "",
    question: str = "",
    extra_profiles: dict | None = None,
) -> str:
    """Build a prompt for the project builder agent to generate clarifying questions."""
    parts = [
        "## Research Description",
        description or "(No description provided)",
        "",
    ]
    if question:
        parts.extend(
            [
                "## Research Question",
                question,
                "",
            ]
        )
    parts.extend(
        [
            "## Source Scan",
            scan_result.summary(),
            "",
        ]
    )

    if data_summary is not None:
        parts.extend(
            [
                "## Data Profile (sample)",
                f"Rows: {data_summary.n_rows}",
                f"Columns: {data_summary.n_columns}",
                f"Column names: {', '.join(data_summary.columns)}",
                f"Data types: {data_summary.dtypes}",
                f"Missing values: {data_summary.missing_counts}",
                "",
            ]
        )

    if extra_profiles:
        parts.append("## Non-Tabular Data Profiles")
        for dtype, profile in extra_profiles.items():
            count = profile.get("count", 0)
            formats = ", ".join(profile.get("formats", []))
            parts.append(f"### {dtype.title()}: {count} files ({formats})")
            if "dimensions" in profile:
                parts.append(f"Dimensions: {profile['dimensions']}")
            if "total_duration_s" in profile:
                parts.append(f"Total duration: {profile['total_duration_s']}s")
            if "sample_rates" in profile:
                parts.append(f"Sample rates: {profile['sample_rates']}")
            if "hdf5_groups" in profile:
                parts.append(f"HDF5 groups: {profile['hdf5_groups']}")
            if "hdf5_datasets" in profile:
                parts.append(f"HDF5 datasets: {profile['hdf5_datasets']}")
            if "note" in profile:
                parts.append(f"Note: {profile['note']}")
            parts.append("")

    if context:
        parts.extend(["## Previous Answers", context, ""])

    parts.append(
        "Based on the above, generate the next clarifying question to scope this project.\n\n"
        "If the user has not yet described how the data was collected (the methods and "
        "procedures used), ask about this early — it is critical context for selecting "
        "appropriate analysis methods. Also ask about domain knowledge: are there relevant "
        "papers or established methods the agents should know about?"
    )
    return "\n".join(parts)


def build_suggestion_prompt(
    description: str,
    data_summary: DataSummary | None,
    answers: dict[str, str],
) -> str:
    """Build a prompt for the suggestion agent to propose initial approaches."""
    parts = [
        "## Project Scope",
        f"Description: {description}",
        "",
    ]

    if data_summary is not None:
        parts.extend(
            [
                "## Data",
                f"Rows: {data_summary.n_rows}, Columns: {data_summary.n_columns}",
                f"Columns: {', '.join(data_summary.columns)}",
                "",
            ]
        )

    if answers:
        parts.append("## User Answers")
        for q, a in answers.items():
            parts.append(f"Q: {q}")
            parts.append(f"A: {a}")
            parts.append("")

    parts.append(
        "Based on the above, propose 2-3 initial analytical approaches as suggestions."
    )
    return "\n".join(parts)


def build_planning_prompt(
    suggestions: dict[str, Any],
    description: str,
    data_summary: DataSummary | None,
) -> str:
    """Build a prompt for the planning agent to create an initial method plan."""
    import json

    parts = [
        "## Project Description",
        description,
        "",
        "## Suggestions",
        json.dumps(suggestions, indent=2),
        "",
    ]

    if data_summary is not None:
        parts.extend(
            [
                "## Data",
                f"Rows: {data_summary.n_rows}, Columns: {data_summary.n_columns}",
                f"Columns: {', '.join(data_summary.columns)}",
                "",
            ]
        )

    parts.append("Design a detailed initial method plan based on these suggestions.")
    return "\n".join(parts)
