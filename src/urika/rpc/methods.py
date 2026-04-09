"""RPC method registry — maps JSON-RPC method names to handler functions."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from urika.rpc.protocol import Registry


def build_registry() -> Registry:
    """Build and return the complete RPC method registry.

    Each handler takes a ``params: dict`` and returns a JSON-serializable result.
    Path strings in params are converted to ``pathlib.Path`` objects automatically.
    Dataclass results are converted via ``.to_dict()`` where applicable.
    """
    return {
        "project.list": _project_list,
        "project.load_config": _project_load_config,
        "experiment.create": _experiment_create,
        "experiment.list": _experiment_list,
        "experiment.load": _experiment_load,
        "progress.append_run": _progress_append_run,
        "progress.load": _progress_load,
        "progress.get_best_run": _progress_get_best_run,
        "session.start": _session_start,
        "session.pause": _session_pause,
        "session.resume": _session_resume,
        "criteria.load": _criteria_load,
        "criteria.append": _criteria_append,
        "methods.register": _methods_register,
        "methods.list": _methods_list,
        "usage.record": _usage_record,
        "tools.list": _tools_list,
        "tools.run": _tools_run,
        "code.execute": _code_execute,
        "data.profile": _data_profile,
        "knowledge.ingest": _knowledge_ingest,
        "knowledge.search": _knowledge_search,
        "knowledge.list": _knowledge_list,
        "labbook.update_notes": _labbook_update_notes,
        "labbook.generate_summary": _labbook_generate_summary,
        "report.results_summary": _report_results_summary,
        "report.key_findings": _report_key_findings,
        "project.summarize": _project_summarize,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _path(params: dict[str, Any], key: str = "project_dir") -> Path:
    """Extract a Path from params, converting from string."""
    return Path(params[key])


# ---------------------------------------------------------------------------
# project.*
# ---------------------------------------------------------------------------


def _project_list(params: dict[str, Any]) -> list[dict[str, Any]]:
    from urika.core.registry import ProjectRegistry

    registry = ProjectRegistry()
    projects = registry.list_all()
    return [{"name": name, "path": str(path)} for name, path in projects.items()]


def _project_summarize(params: dict[str, Any]) -> dict[str, Any]:
    """Aggregate project state into a concise summary — no LLM, pure data."""
    from urika.core.experiment import list_experiments
    from urika.core.progress import load_progress
    from urika.core.criteria import load_criteria
    from urika.core.method_registry import load_methods
    from urika.core.workspace import load_project_config

    project_dir = _path(params)
    config = load_project_config(project_dir)

    # Experiments summary
    experiments = list_experiments(project_dir)
    exp_summaries = []
    total_runs = 0
    for exp in experiments:
        progress = load_progress(project_dir, exp.experiment_id)
        runs = progress.get("runs", [])
        total_runs += len(runs)
        status = progress.get("status", "unknown")
        best_metrics = {}
        for run in runs:
            for k, v in run.get("metrics", {}).items():
                if isinstance(v, (int, float)):
                    if k not in best_metrics or v > best_metrics[k]:
                        best_metrics[k] = v
        exp_summaries.append({
            "id": exp.experiment_id,
            "name": exp.name,
            "status": status,
            "runs": len(runs),
            "best_metrics": best_metrics,
        })

    # Methods summary — top 5 by first metric
    methods = load_methods(project_dir)
    top_methods = sorted(
        methods,
        key=lambda m: max(m.get("metrics", {}).values()) if m.get("metrics") else 0,
        reverse=True,
    )[:5]

    # Criteria
    criteria_version = load_criteria(project_dir)
    criteria_summary = criteria_version.to_dict() if criteria_version else None

    return {
        "project": config.name if hasattr(config, "name") else str(project_dir),
        "question": config.question if hasattr(config, "question") else "",
        "total_experiments": len(experiments),
        "total_runs": total_runs,
        "completed_experiments": sum(
            1 for e in exp_summaries if e["status"] == "completed"
        ),
        "experiments": exp_summaries[:10],  # first 10 only
        "top_methods": [
            {"name": m.get("name"), "metrics": m.get("metrics")}
            for m in top_methods
        ],
        "criteria": criteria_summary,
        "total_methods": len(methods),
    }


def _project_load_config(params: dict[str, Any]) -> dict[str, Any]:
    from urika.core.workspace import load_project_config

    config = load_project_config(_path(params))
    return {
        "name": config.name,
        "question": config.question,
        "mode": config.mode,
        "description": config.description,
        "data_paths": config.data_paths,
        "success_criteria": config.success_criteria,
        "audience": config.audience,
    }


# ---------------------------------------------------------------------------
# experiment.*
# ---------------------------------------------------------------------------


def _experiment_create(params: dict[str, Any]) -> dict[str, Any]:
    from urika.core.experiment import create_experiment

    exp = create_experiment(
        _path(params),
        name=params["name"],
        hypothesis=params["hypothesis"],
        builds_on=params.get("builds_on"),
    )
    return exp.to_dict()


def _experiment_list(params: dict[str, Any]) -> list[dict[str, Any]]:
    from urika.core.experiment import list_experiments

    experiments = list_experiments(_path(params))
    return [e.to_dict() for e in experiments]


def _experiment_load(params: dict[str, Any]) -> dict[str, Any]:
    from urika.core.experiment import load_experiment

    exp = load_experiment(_path(params), params["experiment_id"])
    return exp.to_dict()


# ---------------------------------------------------------------------------
# progress.*
# ---------------------------------------------------------------------------


def _progress_append_run(params: dict[str, Any]) -> None:
    from urika.core.models import RunRecord
    from urika.core.progress import append_run

    run = RunRecord.from_dict(params["run"])
    append_run(_path(params), params["experiment_id"], run)
    return None


def _progress_load(params: dict[str, Any]) -> dict[str, Any]:
    from urika.core.progress import load_progress

    # load_progress already returns a plain dict
    return load_progress(_path(params), params["experiment_id"])


def _progress_get_best_run(params: dict[str, Any]) -> dict[str, Any] | None:
    from urika.core.progress import get_best_run

    # get_best_run already returns a plain dict or None
    return get_best_run(
        _path(params),
        params["experiment_id"],
        metric=params["metric"],
        direction=params["direction"],
    )


# ---------------------------------------------------------------------------
# session.*
# ---------------------------------------------------------------------------


def _session_start(params: dict[str, Any]) -> dict[str, Any]:
    from urika.core.session import start_session

    state = start_session(
        _path(params),
        params["experiment_id"],
        max_turns=params.get("max_turns"),
    )
    return state.to_dict()


def _session_pause(params: dict[str, Any]) -> dict[str, Any]:
    from urika.core.session import pause_session

    state = pause_session(_path(params), params["experiment_id"])
    return state.to_dict()


def _session_resume(params: dict[str, Any]) -> dict[str, Any]:
    from urika.core.session import resume_session

    state = resume_session(_path(params), params["experiment_id"])
    return state.to_dict()


# ---------------------------------------------------------------------------
# criteria.*
# ---------------------------------------------------------------------------


def _criteria_load(params: dict[str, Any]) -> dict[str, Any] | None:
    from urika.core.criteria import load_criteria

    cv = load_criteria(_path(params))
    if cv is None:
        return None
    return cv.to_dict()


def _criteria_append(params: dict[str, Any]) -> dict[str, Any]:
    from urika.core.criteria import append_criteria

    cv = append_criteria(
        _path(params),
        params["criteria"],
        set_by=params["set_by"],
        turn=params["turn"],
        rationale=params["rationale"],
    )
    return cv.to_dict()


# ---------------------------------------------------------------------------
# methods.*
# ---------------------------------------------------------------------------


def _methods_register(params: dict[str, Any]) -> None:
    from urika.core.method_registry import register_method

    register_method(
        _path(params),
        name=params["name"],
        description=params["description"],
        script=params["script"],
        experiment=params["experiment"],
        turn=params["turn"],
        metrics=params["metrics"],
        status=params.get("status", "active"),
    )
    return None


def _methods_list(params: dict[str, Any]) -> list[dict[str, Any]]:
    from urika.core.method_registry import load_methods

    # load_methods already returns list[dict]
    return load_methods(_path(params))


# ---------------------------------------------------------------------------
# usage.*
# ---------------------------------------------------------------------------


def _usage_record(params: dict[str, Any]) -> None:
    from urika.core.usage import record_session

    record_session(
        _path(params),
        started=params["started"],
        ended=params["ended"],
        duration_ms=params["duration_ms"],
        tokens_in=params.get("tokens_in", 0),
        tokens_out=params.get("tokens_out", 0),
        cost_usd=params.get("cost_usd", 0.0),
        agent_calls=params.get("agent_calls", 0),
        experiments_run=params.get("experiments_run", 0),
    )
    return None


# ---------------------------------------------------------------------------
# tools.*
# ---------------------------------------------------------------------------


def _tools_list(params: dict[str, Any]) -> list[str]:
    from urika.tools.registry import ToolRegistry

    reg = ToolRegistry()
    reg.discover()
    project_dir = params.get("project_dir")
    if project_dir:
        reg.discover_project(Path(project_dir) / "tools")
    return reg.list_all()


def _tools_run(params: dict[str, Any]) -> dict[str, Any]:
    from urika.data.loader import load_dataset
    from urika.tools.registry import ToolRegistry

    reg = ToolRegistry()
    reg.discover()
    project_dir = params.get("project_dir")
    if project_dir:
        reg.discover_project(Path(project_dir) / "tools")

    tool = reg.get(params["name"])
    if tool is None:
        raise ValueError(f"Tool not found: {params['name']}")

    data_path = Path(params["data_path"])
    dataset = load_dataset(data_path)
    tool_params = params.get("params", {})

    result = tool.run(dataset, tool_params)
    return {
        "outputs": result.outputs,
        "artifacts": result.artifacts,
        "metrics": result.metrics,
        "valid": result.valid,
        "error": result.error,
    }


# ---------------------------------------------------------------------------
# code.*
# ---------------------------------------------------------------------------


def _code_execute(params: dict[str, Any]) -> dict[str, Any]:
    code = params["code"]
    timeout = params.get("timeout", 30)
    cwd = params.get("cwd")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        f.flush()
        script_path = f.name

    try:
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        return {
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Execution timed out after {timeout}s",
        }
    finally:
        Path(script_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# data.*
# ---------------------------------------------------------------------------


def _data_profile(params: dict[str, Any]) -> dict[str, Any]:
    from urika.data.loader import load_dataset

    path = Path(params["path"])
    name = params.get("name")
    dataset = load_dataset(path, name=name)

    summary = dataset.summary
    return {
        "name": dataset.spec.name,
        "format": dataset.spec.format,
        "n_rows": summary.n_rows,
        "n_columns": summary.n_columns,
        "columns": summary.columns,
        "dtypes": summary.dtypes,
        "missing_counts": summary.missing_counts,
        "numeric_stats": summary.numeric_stats,
    }


# ---------------------------------------------------------------------------
# knowledge.*
# ---------------------------------------------------------------------------


def _knowledge_ingest(params: dict[str, Any]) -> dict[str, Any]:
    from urika.knowledge.store import KnowledgeStore

    store = KnowledgeStore(_path(params))
    entry = store.ingest(
        params["source"],
        source_type=params.get("source_type"),
    )
    return entry.to_dict()


def _knowledge_search(params: dict[str, Any]) -> list[dict[str, Any]]:
    from urika.knowledge.store import KnowledgeStore

    store = KnowledgeStore(_path(params))
    entries = store.search(params["query"])
    return [e.to_dict() for e in entries]


def _knowledge_list(params: dict[str, Any]) -> list[dict[str, Any]]:
    from urika.knowledge.store import KnowledgeStore

    store = KnowledgeStore(_path(params))
    entries = store.list_all()
    return [e.to_dict() for e in entries]


# ---------------------------------------------------------------------------
# labbook.*
# ---------------------------------------------------------------------------


def _labbook_update_notes(params: dict[str, Any]) -> None:
    from urika.core.labbook import update_experiment_notes

    update_experiment_notes(_path(params), params["experiment_id"])
    return None


def _labbook_generate_summary(params: dict[str, Any]) -> None:
    from urika.core.labbook import generate_experiment_summary

    generate_experiment_summary(_path(params), params["experiment_id"])
    return None


# ---------------------------------------------------------------------------
# report.*
# ---------------------------------------------------------------------------


def _report_results_summary(params: dict[str, Any]) -> None:
    from urika.core.labbook import generate_results_summary

    generate_results_summary(_path(params))
    return None


def _report_key_findings(params: dict[str, Any]) -> None:
    from urika.core.labbook import generate_key_findings

    generate_key_findings(_path(params))
    return None
