"""Context summarization for inter-agent communication."""

from __future__ import annotations

import json
from pathlib import Path


def summarize_progress(project_dir: Path, experiment_id: str, *, for_role: str = "") -> str:
    """Build a compact progress summary tailored to an agent role.

    for_role: 'evaluator', 'advisor', 'planning', or '' for full summary.
    """
    from urika.core.progress import load_progress

    data = load_progress(project_dir, experiment_id)
    runs = data.get("runs", [])
    if not runs:
        return "No runs recorded yet."

    lines = [f"Experiment: {experiment_id} — {len(runs)} run(s)"]

    if for_role == "evaluator":
        # Evaluator only needs the latest run and best metrics
        last = runs[-1]
        lines.append(f"Latest run: {last.get('method', '?')} — metrics: {json.dumps(last.get('metrics', {}))}")
        if last.get("observation"):
            lines.append(f"Observation: {last['observation'][:200]}")
    elif for_role == "advisor":
        # Advisor needs metric trends and recent observations
        lines.append("Metric progression:")
        for r in runs[-5:]:
            m = r.get("metrics", {})
            metric_str = ", ".join(f"{k}={v:.4g}" if isinstance(v, float) else f"{k}={v}" for k, v in m.items())
            lines.append(f"  {r.get('method', '?')}: {metric_str}")
        last = runs[-1]
        if last.get("observation"):
            lines.append(f"Latest observation: {last['observation'][:300]}")
        if last.get("next_step"):
            lines.append(f"Suggested next: {last['next_step'][:200]}")
    else:
        # Full summary for planning agent
        lines.append("Methods tried:")
        for r in runs:
            m = r.get("metrics", {})
            metric_str = ", ".join(f"{k}={v:.4g}" if isinstance(v, float) else f"{k}={v}" for k, v in m.items())
            lines.append(f"  {r.get('method', '?')}: {metric_str}")
        last = runs[-1]
        if last.get("observation"):
            lines.append(f"Latest: {last['observation'][:200]}")
        if last.get("next_step"):
            lines.append(f"Next: {last['next_step'][:200]}")

    return "\n".join(lines)


def summarize_methods(project_dir: Path) -> str:
    """Build a compact methods summary from methods.json."""
    methods_path = project_dir / "methods.json"
    if not methods_path.exists():
        return ""
    try:
        data = json.loads(methods_path.read_text())
        methods = data.get("methods", [])
        if not methods:
            return ""
        lines = [f"Methods registry ({len(methods)} methods):"]
        for m in methods:
            metrics = m.get("metrics", {})
            status = m.get("status", "")
            metric_str = ", ".join(
                f"{k}={v:.4g}" if isinstance(v, float) else f"{k}={v}"
                for k, v in metrics.items()
                if isinstance(v, (int, float))
            )
            line = f"  {m['name']}"
            if metric_str:
                line += f": {metric_str}"
            if status and status != "active":
                line += f" [{status}]"
            lines.append(line)
        return "\n".join(lines)
    except Exception:
        return ""


def summarize_task_output(text: str) -> str:
    """Extract structured content from task agent output, stripping verbose code/logs.

    Keeps JSON run record blocks and brief observations, removes code blocks and
    pip install output.
    """
    import re

    # Extract JSON blocks (the structured data we need)
    json_blocks = []
    for match in re.finditer(r"```(?:json|JSON)\s*\n(.*?)```", text, re.DOTALL):
        json_blocks.append(match.group(0))

    # Extract non-code text (observations, summaries)
    # Remove code blocks and their content
    cleaned = re.sub(r"```(?:python|bash|sh|pip)?\s*\n.*?```", "", text, flags=re.DOTALL)
    # Remove long pip install output lines
    cleaned = re.sub(r"(?:Successfully installed|Collecting|Downloading|Installing).*\n?", "", cleaned)
    # Collapse multiple newlines
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    # Combine: observations + JSON blocks
    parts = []
    if cleaned:
        # Truncate observations to keep context reasonable
        if len(cleaned) > 1000:
            cleaned = cleaned[:1000] + "\n... (truncated)"
        parts.append(cleaned)
    parts.extend(json_blocks)

    return "\n\n".join(parts)
