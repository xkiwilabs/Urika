# Dashboard — Settings and Auth

Project + global settings pages, per-channel notification test-send, the per-project Secrets tab, and the `--auth-token` bearer-token gate. See [Pages and Navigation](18a-dashboard-pages.md), [Operations](18b-dashboard-operations.md), and [API](18d-dashboard-api.md) for the rest of the dashboard surface.

## Settings UI

Two settings pages share the same tabbed form pattern. Tabs are a small Alpine.js primitive — no router, no URL fragments — so saving a tab's form does not navigate away.

- **Project settings** (`/projects/<name>/settings`) — writes to that project's `urika.toml`. Five tabs:
  - **Basics**: name, mode, audience, research question.
  - **Data**: dataset path, target column, feature columns. Saving appends a new entry to `revisions.json` so changes are auditable.
  - **Models**: per-agent model overrides (planning, task, evaluator, advisor, etc.).
  - **Privacy**: an **Inherit / Override global** picker. Inherit removes the `[privacy]` block from `urika.toml` and the project falls back to the global default. Override exposes privacy mode (`local`, `hybrid`, `cloud`) and any path allow-listing.
  - **Notifications**: per-channel **Inherit / Enabled / Disabled** radios (slack, email, desktop) plus an editable extra-recipients list. Same inheritance pattern as Privacy.
- **Global settings** (`/settings`) — writes to `~/.urika/settings.toml` and seeds new projects. Four tabs:
  - **Privacy**: default privacy mode for new projects.
  - **Models**: default per-agent model assignments.
  - **Preferences**: default audience, max turns, theme preference.
  - **Notifications**: default notification configuration.

The Settings page also surfaces a **compliance banner above the form** whenever the dashboard process can't see `ANTHROPIC_API_KEY`. The banner explains that Anthropic's Consumer Terms §3.7 and the April 2026 Agent SDK clarification prohibit using a Pro/Max subscription with the Claude Agent SDK and points the user at `urika config api-key` (or `export ANTHROPIC_API_KEY=...`) to fix it. When the env var is set the banner does not render. See [Provider compliance](20-security.md#provider-compliance) for the underlying rationale.

Both pages POST to a `PUT /api/...` endpoint that validates the payload and saves through the same `_write_toml` helper used by the CLI's `urika config`. See [Configuration](14a-project-config.md) for the underlying file formats.

### Send-test notification button

The Notifications tab on the global Settings page includes a **Send test
notification** button. Clicking it:

1. Calls `POST /api/settings/notifications/test-send` with the current form
   contents (un-saved) so you can validate credentials before clicking Save.
2. The endpoint reloads `~/.urika/secrets.env` (so credentials added by
   `urika notifications` in another shell are visible without restarting
   the dashboard) and constructs each enabled channel.
3. Each channel's `health_check()` is called first (SMTP NOOP for email,
   `auth_test` for Slack, `Bot.get_me()` for Telegram); failures are
   reported with the SDK's actual error string.
4. Channels that pass health-check then send a synthetic test event.
5. Per-channel results render inline below the button — green tick for
   sent, red cross with the error message for failures.

This is the fastest way to debug a misconfigured channel: the button shows
the real auth error (e.g. Slack `invalid_auth`, Gmail `530 Authentication
Required`) instead of waiting for an experiment run to surface it.


## Auth

By default the dashboard binds `127.0.0.1` and accepts every connection. For shared or networked deployments use `--auth-token`:

```bash
urika dashboard --auth-token "$(openssl rand -hex 32)"
```

When set, every request other than `/healthz` and `/static/...` requires:

```
Authorization: Bearer <token>
```

The check uses `secrets.compare_digest` for constant-time comparison. `/healthz` is exempt so external health probes work; `/static/...` is exempt so a token-aware client can still load the CSS and JS.

**Limitation.** Browsers don't send `Authorization` headers on top-level page navigation, so the token mode is intended for token-aware HTTP clients (curl, internal tooling, reverse proxies that inject the header). For browser use over an untrusted network, front the dashboard with a reverse proxy that handles auth (e.g. an SSH tunnel, a VPN, or an OAuth proxy).


## See also

- [Dashboard — Pages and Navigation](18a-dashboard-pages.md)
- [Dashboard — Operations](18b-dashboard-operations.md)
- [Dashboard — API](18d-dashboard-api.md)
- [CLI Reference](16a-cli-projects.md)
- [Interactive TUI](17-interactive-tui.md)
- [Configuration](14a-project-config.md)
