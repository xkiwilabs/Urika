"""``urika github`` Click subgroup — GitHub auto-backup CLI (v0.6.0).

Urika never sees a GitHub credential. The CLI shells out to the system
``git`` binary (and optionally ``gh``) and lets the user's existing
auth (PAT in their credential helper, SSH key, gh-stored credential)
do the work.

See ``dev/plans/2026-05-31-v0.6.0-github-design.md`` for the locked
design.
"""

from __future__ import annotations

import click

from urika.cli._base import cli
from urika.cli._helpers import _ensure_project, _resolve_project


@cli.group("github")
def github() -> None:
    """GitHub auto-backup commands.

    Urika never holds a GitHub credential — these commands shell out to
    the system ``git`` (and optionally ``gh``) CLI so your existing auth
    (HTTPS+PAT, SSH key, ``gh auth login``) does the work.
    """


@github.command("init")
@click.argument("project", required=False, default=None)
@click.option(
    "--remote",
    default=None,
    help="Remote URL (e.g. https://github.com/user/repo.git)",
)
@click.option(
    "--create",
    is_flag=True,
    help="Create the GitHub repo via `gh repo create` (lands in v0.6 T2.2).",
)
@click.option(
    "--public",
    is_flag=True,
    help="With --create: make the new repo public (default: private).",
)
def github_init(
    project: str | None, remote: str | None, create: bool, public: bool
) -> None:
    """Initialise a project as a git repo (+ optionally set the remote).

    Writes a researcher-safe ``.gitignore`` managed block, stages
    everything, and creates an initial commit. Idempotent — running
    twice on the same project is safe and just reports that nothing
    new needed committing.
    """
    from urika.core import git as _git

    name = _ensure_project(project)
    project_dir, _config = _resolve_project(name)

    already = _git.is_git_repo(project_dir)
    _git.init_repo(project_dir)
    _git.write_gitignore(project_dir)

    if remote:
        _git.add_remote(project_dir, remote)
        click.echo(f"  remote 'origin' -> {remote}")

    if create:
        # ``gh repo create --push`` initialises remote + pushes the
        # initial commit in one shot. On success we return early so we
        # don't redundantly run ``commit_all`` (which would either say
        # "nothing to commit" or — worse — create a duplicate commit).
        gh_result = _git.gh_create_repo(
            project_dir, name=project_dir.name, public=public
        )
        if gh_result.ok:
            click.echo(f"  ✓ created GitHub repo: {gh_result.repo_url}")
            return
        # Failure — surface error + install_hint.
        click.secho(f"  ✗ {gh_result.error}", fg="red", err=True)
        if gh_result.install_hint:
            click.echo(gh_result.install_hint, err=True)
        raise SystemExit(2)

    # Initial commit if there's something to commit.
    result = _git.commit_all(project_dir, message="urika: initial project state")
    if result.ok:
        click.echo(f"  initial commit {result.sha}")
    elif already:
        click.echo("  already initialised - nothing new to commit")
    else:
        # Edge: brand-new init but nothing to commit (empty dir). Fine.
        click.echo("  initialised (no tracked content yet)")
