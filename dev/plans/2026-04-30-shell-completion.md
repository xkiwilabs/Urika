# Shell Completion — v0.4

**Status:** active (design)
**Date:** 2026-04-30
**Track:** 4
**Effort:** 0.5 dev-days

## Goal

Native bash / zsh / fish completion for `urika`. Click 8 has the
generator built-in (`_URIKA_COMPLETE=bash_source urika`). One CLI
command (`urika completion install [bash|zsh|fish]`) and a docs blurb.
Heavy CLI users (Urika's explicit audience per `feedback_cli_ux.md`)
expect this.

## Behavior

```
$ urika completion install
  Detected shell: bash
  Installed completion to: ~/.urika/completions/urika.bash
  To activate immediately:  source ~/.urika/completions/urika.bash
  To activate every shell:  add the source line above to ~/.bashrc
```

Subcommands: `install [bash|zsh|fish]` (auto-detect from `$SHELL`
when not specified), `script [bash|zsh|fish]` (print to stdout for
manual install), `uninstall` (remove the completion file + leave
shell rc untouched).

`urika setup` could prompt to install completion during first-run
setup (low-pressure, one-line).

## Implementation

New file `src/urika/cli/completion.py`. Click's
`shell_completion.get_completion_class(shell)` produces the script;
write it to `~/.urika/completions/urika.<shell>`. The `Group` is
already `cli` in `cli/_base.py`; no additional plumbing.

## Tests

Trivial — `CliRunner.invoke(cli, ["completion", "script", "bash"])`
returns a non-empty stdout that includes the right shell-specific
function name. No filesystem assertions for `install` (use a tmp
home dir).

## Files

- `src/urika/cli/completion.py` (new)
- `src/urika/cli/__init__.py` (register the new group)
- `tests/test_cli/test_completion.py` (new)
- `docs/01-getting-started.md` Step 4 (mention `urika completion
  install` as part of post-install setup)
