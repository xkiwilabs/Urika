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


@github.command("status")
@click.argument("project", required=False, default=None)
def github_status(project: str | None) -> None:
    """Show remote URL, branch, dirty count, and recent commits."""
    from urika.core import git as _git

    name = _ensure_project(project)
    project_dir, _config = _resolve_project(name)

    if not _git.is_git_repo(project_dir):
        click.secho(f"  not a git repo: {project_dir}", fg="yellow")
        click.echo("  run `urika github init <project>` first")
        return

    st = _git.status(project_dir)
    click.echo(f"  branch:        {st.branch or '(none)'}")
    click.echo(f"  remote:        {st.remote_url or '(not set)'}")
    click.echo(f"  uncommitted:   {st.dirty_count} file(s)")
    if st.last_commit_sha:
        click.echo(f"  last commit:   {st.last_commit_sha}  {st.last_commit_subject}")
    recent = _git.recent_commits(project_dir, limit=5)
    if recent:
        click.echo("  recent:")
        for c in recent:
            tag = f" [{c.event}]" if c.event else ""
            click.echo(f"    {c.sha}  {c.subject}{tag}")


@github.command("push")
@click.argument("project", required=False, default=None)
def github_push(project: str | None) -> None:
    """Stage everything, commit (after secret scan), and push to origin.

    The secret scanner runs on staged content *before* the commit lands.
    If anything matches a known credential pattern (Anthropic, GitHub PAT,
    AWS, OpenAI, etc.), the push aborts with exit code 3, the offending
    file:line is printed, and the index is reset so the working tree
    isn't left in a half-staged state.
    """
    from urika.core import git as _git

    name = _ensure_project(project)
    project_dir, _config = _resolve_project(name)

    if not _git.is_git_repo(project_dir):
        click.secho(f"  not a git repo: {project_dir}", fg="red", err=True)
        click.echo("  run `urika github init <project>` first", err=True)
        raise SystemExit(2)

    # 1. Stage everything so the secret scanner sees what we're about to commit.
    _git._git(project_dir, "add", "-A")

    # 2. Secret scan.
    matches = _git.scan_for_secrets(project_dir)
    if matches:
        for m in matches:
            click.secho(
                f"  ✗ [urika:secret-detected] {m.file}:{m.line} "
                f"({m.pattern_name})  match: {m.preview}",
                fg="red",
                err=True,
            )
        click.echo(
            "\n  Aborted commit. Remove the secret(s) from the file(s) above "
            "or add the file(s) to .gitignore, then re-run.",
            err=True,
        )
        # Un-stage so the user's tree isn't left in a weird state.
        _git._git(project_dir, "reset", "HEAD", check=False)
        raise SystemExit(3)

    # 3. Commit.
    subject = "urika: project state"
    body = "\n\nurika-event: manual\nurika-version: 0.6.0\n"
    commit = _git.commit_all(project_dir, message=subject + body)
    if commit.ok:
        click.echo(f"  committed {commit.sha}: {subject}")
    else:
        click.echo(f"  (no new commit: {commit.error})")

    # 4. Push.
    pushed = _git.push(project_dir)
    if pushed.ok:
        click.echo(f"  ✓ pushed {pushed.pushed_sha} to origin")
    else:
        click.secho("  ⚠ urika github push: failed", fg="yellow", err=True)
        click.echo(f"    {pushed.error}", err=True)
        click.echo(
            "    Retry with `urika github push <project>` once the underlying "
            "issue is resolved.",
            err=True,
        )
        raise SystemExit(1)


@github.command("pull")
@click.argument("project", required=False, default=None)
def github_pull(project: str | None) -> None:
    """Fetch + fast-forward-only merge from origin.

    Refuses on divergence — if local has commits that aren't on the
    remote (or vice versa in a non-ff way), the user must resolve that
    themselves with their own git tooling. Urika does not auto-merge.
    """
    from urika.core import git as _git

    name = _ensure_project(project)
    project_dir, _config = _resolve_project(name)

    if not _git.is_git_repo(project_dir):
        click.secho(f"  not a git repo: {project_dir}", fg="yellow", err=True)
        click.echo("  run `urika github init <project>` first", err=True)
        raise SystemExit(2)

    result = _git.pull(project_dir)
    if result.ok:
        click.echo("  ✓ pulled from origin")
    else:
        click.secho("  ⚠ urika github pull: failed", fg="yellow", err=True)
        click.echo(f"    {result.error}", err=True)
        raise SystemExit(1)
