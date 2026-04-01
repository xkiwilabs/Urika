"""Task agent — runs experiments and records observations."""

from __future__ import annotations

from pathlib import Path

from urika.agents.config import (
    AgentConfig,
    AgentRole,
    SecurityPolicy,
    build_agent_env_for_endpoint,
    get_agent_model,
    load_runtime_config,
)
from urika.agents.prompt import load_prompt
from urika.core.hardware import hardware_summary

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def get_role() -> AgentRole:
    return AgentRole(
        name="task_agent",
        description="Runs analytical methods and records observations",
        build_config=build_config,
    )


def _build_data_privacy_block(project_dir: Path, privacy_mode: str) -> str:
    """Build data privacy instructions for hybrid/private mode prompts."""
    if privacy_mode not in ("hybrid", "private"):
        return ""

    import tomllib

    data_paths_str = "data/"
    toml_path = project_dir / "urika.toml"
    if toml_path.exists():
        try:
            with open(toml_path, "rb") as f:
                tdata = tomllib.load(f)
            data_paths = tdata.get("project", {}).get("data_paths", [])
            data_source = tdata.get("data", {}).get("source", "")
            all_paths = list(set(data_paths + ([data_source] if data_source else [])))
            if all_paths:
                data_paths_str = ", ".join(all_paths)
        except Exception:
            pass

    return (
        "## Data Privacy — CRITICAL\n\n"
        f"This project runs in **{privacy_mode}** mode. "
        "Raw data must NEVER be sent to cloud APIs.\n\n"
        "**NEVER** use Read, Glob, Grep, or Bash (cat/head/tail/less) "
        "to view raw data files:\n"
        f"  Data paths: {data_paths_str}\n\n"
        "Your Python scripts CAN import and process these files — "
        "scripts run locally on this machine.\n"
        "But do NOT read data file contents through your tools — "
        "that sends data to the cloud.\n\n"
        "Use the Data Agent's sanitized profile for column names, "
        "types, and statistics.\n"
        "If no profile exists, the experiment should not have started "
        "— report this as an error.\n"
    )


def build_config(
    project_dir: Path, *, experiment_id: str = "", **kwargs: object
) -> AgentConfig:
    runtime_config = load_runtime_config(project_dir)
    experiment_dir = project_dir / "experiments" / experiment_id

    data_privacy = _build_data_privacy_block(
        project_dir, runtime_config.privacy_mode
    )

    return AgentConfig(
        name="task_agent",
        system_prompt=load_prompt(
            _PROMPTS_DIR / "task_agent_system.md",
            variables={
                "project_dir": str(project_dir),
                "experiment_id": experiment_id,
                "experiment_dir": str(experiment_dir),
                "hardware_summary": hardware_summary(),
                "data_privacy_instructions": data_privacy,
            },
        ),
        allowed_tools=["Read", "Write", "Bash", "Glob", "Grep"],
        disallowed_tools=[],
        security=SecurityPolicy(
            writable_dirs=[experiment_dir],
            readable_dirs=[project_dir],
            allowed_bash_prefixes=["python ", "pip "],
            blocked_bash_patterns=["rm -rf", "git push", "git reset"],
        ),
        max_turns=25,
        cwd=project_dir,
        model=get_agent_model("task_agent", runtime_config),
        env=build_agent_env_for_endpoint(project_dir, "task_agent", runtime_config),
    )
